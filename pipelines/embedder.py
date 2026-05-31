"""Chunk documents, embed with OpenAI, and upsert to ChromaDB.

Chunking strategy:
  1. Parse filing into sections (Item 1, Item 1A, Item 7, etc.)
  2. Within each section, split prose by tokens (tiktoken cl100k_base, 512 tokens)
  3. Extract tables as separate markdown chunks with chunk_type="table"
  4. Tag every chunk with section_name + chunk_type metadata
  5. Fallback to flat-text chunking if section parsing fails
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass

import chromadb
import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chunk, Filing
from pipelines.hashing import content_hash

logger = logging.getLogger(__name__)

# Parent-document chunking. We embed *small* child chunks for retrieval
# precision (a tight chunk → a sharp, un-blurred embedding), but feed the
# LLM the *parent* block the child came from, so it sees full surrounding
# context instead of a 500-token sliver. See chunk_filing().
CHILD_CHUNK_SIZE = 500      # tokens — embedded + retrieved + reranked
CHILD_CHUNK_OVERLAP = 80    # tokens
PARENT_CHUNK_SIZE = 2000    # tokens — the block handed to the LLM
PARENT_CHUNK_OVERLAP = 200  # tokens

# Back-compat aliases (legacy callers / tests reference these names).
CHUNK_SIZE = CHILD_CHUNK_SIZE
CHUNK_OVERLAP = CHILD_CHUNK_OVERLAP

EMBEDDING_MODEL = "text-embedding-3-large"
COLLECTION_NAME = "finsight_filings"

# tiktoken encoder for OpenAI models (cl100k_base covers text-embedding-3)
_encoding = tiktoken.get_encoding("cl100k_base")

# OpenAI's embeddings endpoint rejects any request over 300,000 tokens or
# 2,048 inputs. A full 10-K's worth of chunks blows past the token cap, so
# embed_texts() splits into sub-requests below these limits.
#
# The token budget is deliberately well under 300k: the API's own token
# accounting runs noticeably higher than a local tiktoken cl100k_base count
# (observed ~1.25x on table-heavy filings — a batch measured at 243k tokens
# was billed as 305k and rejected). 150k gives ~2x headroom over that gap,
# at the cost of a few more requests per filing — embeddings calls are cheap.
_MAX_TOKENS_PER_REQUEST = 150_000
_MAX_INPUTS_PER_REQUEST = 2_048


def _token_len(text: str) -> int:
    """Count tokens using tiktoken cl100k_base encoding."""
    return len(_encoding.encode(text))


# Token-level splitters. The same separator ladder is used for both
# granularities; only the target size differs.
_SEPARATORS = ["\n\n", "\n", ". ", " "]

_child_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHILD_CHUNK_SIZE,
    chunk_overlap=CHILD_CHUNK_OVERLAP,
    length_function=_token_len,
    separators=_SEPARATORS,
)
_parent_splitter = RecursiveCharacterTextSplitter(
    chunk_size=PARENT_CHUNK_SIZE,
    chunk_overlap=PARENT_CHUNK_OVERLAP,
    length_function=_token_len,
    separators=_SEPARATORS,
)
# Back-compat alias.
_splitter = _child_splitter


@dataclass
class PreparedChunk:
    """A child chunk ready for embedding, with parent-document metadata.

    `text` is the small chunk that gets embedded and retrieved; `parent_text`
    is the larger block it belongs to, which is what the LLM actually reads.
    `parent_id` groups all children of the same parent so retrieval can
    de-duplicate and expand a hit to its parent.
    """
    text: str
    chunk_type: str       # "prose" or "table"
    section_name: str     # e.g. "Risk Factors", "MD&A", "full_text"
    item_number: str      # e.g. "1A", "7", ""
    parent_id: str        # shared by all children of one parent block
    parent_text: str      # the parent block — fed to the LLM as context


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------

def _get_chroma_client() -> chromadb.ClientAPI:
    host = os.getenv("CHROMA_HOST", "localhost")
    port = int(os.getenv("CHROMA_PORT", "8100"))
    return chromadb.HttpClient(host=host, port=port)


def _get_openai_client() -> OpenAI:
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _get_collection(chroma: chromadb.ClientAPI) -> chromadb.Collection:
    return chroma.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str) -> list[str]:
    """Split text into child-sized chunks. Legacy API for backward compat."""
    return _child_splitter.split_text(text)


def _add_parent_child(
    chunks: list[PreparedChunk],
    text: str,
    chunk_type: str,
    section_name: str,
    item_number: str,
) -> None:
    """Split `text` into parent blocks, then each parent into child chunks.

    Every child carries its parent's id and full text, so a retrieval hit on
    a small child can be expanded to the larger, more readable parent block.
    """
    for parent_block in _parent_splitter.split_text(text):
        parent_id = uuid.uuid4().hex
        for child in _child_splitter.split_text(parent_block):
            chunks.append(PreparedChunk(
                text=child,
                chunk_type=chunk_type,
                section_name=section_name,
                item_number=item_number,
                parent_id=parent_id,
                parent_text=parent_block,
            ))


def chunk_filing(raw_html: str) -> list[PreparedChunk]:
    """Parse a filing into section-aware parent/child chunks with tables.

    Returns a flat list of child PreparedChunks; each one references the
    parent block it belongs to (see _add_parent_child / PreparedChunk).
    """
    from pipelines.cleaner import parse_filing_sections

    parsed = parse_filing_sections(raw_html)

    chunks: list[PreparedChunk] = []

    if parsed.sections:
        # Section-aware chunking
        for section in parsed.sections:
            if section.text and _token_len(section.text) > 10:
                _add_parent_child(
                    chunks, section.text, "prose",
                    section.section_name, section.item_number,
                )
            # Each table is prefixed with section context, then parent/child
            # split like prose (a small table collapses to a single chunk
            # whose child == parent).
            for table_md in section.tables:
                if _token_len(table_md) < 10:
                    continue
                _add_parent_child(
                    chunks, f"[Table from {section.section_name}]\n{table_md}",
                    "table", section.section_name, section.item_number,
                )
    else:
        # Fallback: flat text chunking (non-SEC docs or parsing failure)
        if parsed.full_text and _token_len(parsed.full_text) > 10:
            _add_parent_child(chunks, parsed.full_text, "prose", "full_text", "")

    n_parents = len({c.parent_id for c in chunks})
    logger.info(
        "Chunked filing: %d child chunks across %d parents "
        "(%d prose, %d table, %d sections)",
        len(chunks), n_parents,
        sum(1 for c in chunks if c.chunk_type == "prose"),
        sum(1 for c in chunks if c.chunk_type == "table"),
        len(parsed.sections),
    )
    return chunks


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_texts(texts: list[str], client: OpenAI | None = None) -> list[list[float]]:
    """Embed texts using OpenAI text-embedding-3-large.

    Splits into sub-requests so no single call exceeds OpenAI's per-request
    limits (300k tokens / 2048 inputs). Embeddings are returned in the same
    order as the input texts.
    """
    if not texts:
        return []
    client = client or _get_openai_client()

    embeddings: list[list[float]] = []
    batch: list[str] = []
    batch_tokens = 0

    def _flush() -> None:
        nonlocal batch, batch_tokens
        if not batch:
            return
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        embeddings.extend(item.embedding for item in response.data)
        batch, batch_tokens = [], 0

    for text in texts:
        n_tokens = _token_len(text)
        # Close the current batch before it would exceed either limit. A
        # single oversized chunk (> the token cap on its own) still gets
        # sent solo — chunking upstream keeps texts well under 512 tokens,
        # so this is a guard, not an expected path.
        if batch and (
            batch_tokens + n_tokens > _MAX_TOKENS_PER_REQUEST
            or len(batch) >= _MAX_INPUTS_PER_REQUEST
        ):
            _flush()
        batch.append(text)
        batch_tokens += n_tokens

    _flush()
    return embeddings


def _fiscal_year(filing: Filing) -> int:
    """Best-effort fiscal year for a filing — 0 when unknown.

    SEC's `period_of_report` is the period-end date; its calendar year is a
    reliable proxy for the fiscal year (NVDA's FY2025 ends late Jan 2025,
    Apple's FY2024 ends Sept 2024). When it is missing (legacy rows, or a
    filing SEC didn't tag) return 0 so temporal filtering simply skips the
    chunk rather than guessing wrong.
    """
    if filing.period_of_report:
        return filing.period_of_report.year
    return 0


def _temporal_header(
    ticker: str,
    doc_type: str,
    fiscal_year: int,
    section_name: str,
    item_number: str,
) -> str:
    """One-line provenance header prepended to each chunk before embedding.

    Putting the fiscal year inside the chunk text makes it visible to both
    the embedding model and the cross-encoder reranker — neither of which
    can otherwise reliably tell a 2024 chunk from a near-identical 2025 one.
    """
    parts: list[str] = [ticker, doc_type]
    if fiscal_year:
        parts.append(f"FY{fiscal_year}")
    if item_number:
        sec = f"Item {item_number}"
        if section_name and section_name != "full_text":
            sec += f" ({section_name})"
        parts.append(sec)
    elif section_name and section_name != "full_text":
        parts.append(section_name)
    return "[" + " · ".join(parts) + "]"


# ---------------------------------------------------------------------------
# Filing embedding pipeline
# ---------------------------------------------------------------------------

async def embed_filing(
    session: AsyncSession,
    filing: Filing,
    chroma_client: chromadb.ClientAPI | None = None,
    openai_client: OpenAI | None = None,
) -> int:
    """Chunk a single filing (section-aware), embed, upsert to ChromaDB + Postgres.

    Returns the number of chunks created.
    """
    if not filing.raw_text:
        logger.warning("Filing %s has no raw_text, skipping", filing.id)
        return 0

    if not filing.content_hash:
        filing.content_hash = content_hash(filing.raw_text)

    # Resolve ticker symbol
    ticker_symbol = "UNKNOWN"
    if filing.ticker:
        ticker_symbol = filing.ticker.symbol

    chroma = chroma_client or _get_chroma_client()
    oai = openai_client or _get_openai_client()
    collection = _get_collection(chroma)

    # Section-aware chunking with tables
    prepared = chunk_filing(filing.raw_text)
    if not prepared:
        logger.warning("Filing %s produced no chunks, skipping", filing.id)
        return 0

    # Prepend a temporal/provenance header to every chunk *before* embedding,
    # so the fiscal year is encoded in the vector and visible to the reranker.
    fiscal_year = _fiscal_year(filing)
    headered: list[str] = [
        f"{_temporal_header(ticker_symbol, filing.filing_type, fiscal_year, c.section_name, c.item_number)}\n{c.text}"
        for c in prepared
    ]

    # Embed in chunks of 512 (OpenAI batch size) and upsert immediately to
    # ChromaDB so each HTTP body stays well under any reasonable limit.
    # A single 10-K can produce 1500+ chunks; a one-shot upsert of all of
    # them with 1536-dim float embeddings easily exceeds 10MB and hits
    # Chroma's 413 Payload Too Large.
    embed_batch = 512   # OpenAI embeddings call batch
    upsert_batch = 200  # ChromaDB upsert batch — keeps payload well under limits

    total_upserted = 0

    for batch_start in range(0, len(prepared), embed_batch):
        batch = prepared[batch_start : batch_start + embed_batch]
        texts = headered[batch_start : batch_start + embed_batch]
        embeddings = embed_texts(texts, client=oai)

        ids: list[str] = []
        vecs: list[list[float]] = []
        docs: list[str] = []
        metas: list[dict] = []

        for i, (chunk, emb) in enumerate(zip(batch, embeddings)):
            chunk_idx = batch_start + i
            vector_id = f"{ticker_symbol}_{filing.accession_number}_{chunk_idx}"
            ids.append(vector_id)
            vecs.append(emb)
            docs.append(headered[chunk_idx])
            metas.append({
                "ticker": ticker_symbol,
                "doc_type": filing.filing_type,
                "filed_date": filing.filed_date.isoformat() if filing.filed_date else "",
                "fiscal_year": fiscal_year,
                "accession_number": filing.accession_number or "",
                "chunk_index": chunk_idx,
                "source_url": filing.source_url or "",
                "section_name": chunk.section_name,
                "item_number": chunk.item_number,
                "chunk_type": chunk.chunk_type,
                # Parent-document retrieval: parent_id de-dupes/groups hits,
                # parent_text is the larger block handed to the LLM.
                "parent_id": chunk.parent_id,
                "parent_text": chunk.parent_text,
            })

        # Sub-batch the upsert so payload stays bounded regardless of
        # embed_batch size (some chunks are big, some metadata is verbose).
        for upsert_start in range(0, len(ids), upsert_batch):
            sl = slice(upsert_start, upsert_start + upsert_batch)
            collection.upsert(
                ids=ids[sl],
                embeddings=vecs[sl],
                documents=docs[sl],
                metadatas=metas[sl],
            )
            total_upserted += len(ids[sl])

    logger.info(
        "Upserted %d vectors for filing %s",
        total_upserted, filing.accession_number,
    )

    # Record chunks in Postgres — store the headered text so the Postgres
    # copy stays identical to what was embedded and stored in Chroma.
    for i in range(len(prepared)):
        vector_id = f"{ticker_symbol}_{filing.accession_number}_{i}"
        chunk_obj = Chunk(
            filing_id=filing.id,
            chunk_index=i,
            text=headered[i],
            token_count=_token_len(headered[i]),
            embedding_id=vector_id,
        )
        session.add(chunk_obj)

    filing.embedded_content_hash = filing.content_hash
    await session.commit()
    return len(prepared)


# ---------------------------------------------------------------------------
# Purge + batch embed
# ---------------------------------------------------------------------------

async def _purge_filing_embeddings(
    session: AsyncSession,
    filing: Filing,
    chroma_client: chromadb.ClientAPI,
) -> None:
    """Delete existing chunks + chroma vectors for a filing so it can be re-embedded."""
    chunk_rows = await session.execute(
        select(Chunk.embedding_id).where(Chunk.filing_id == filing.id)
    )
    vector_ids = [row[0] for row in chunk_rows.all() if row[0]]

    if vector_ids:
        try:
            collection = _get_collection(chroma_client)
            collection.delete(ids=vector_ids)
            logger.info("Purged %d stale vectors for filing %s", len(vector_ids), filing.accession_number)
        except Exception:
            logger.exception("Failed to purge chroma vectors for filing %s", filing.accession_number)

    await session.execute(delete(Chunk).where(Chunk.filing_id == filing.id))
    await session.commit()


async def embed_all_pending(session: AsyncSession) -> dict:
    """Embed filings that are either unembedded or whose content_hash changed."""
    from sqlalchemy.orm import selectinload

    # Backfill pass for legacy filings
    legacy_result = await session.execute(
        select(Filing.id, Filing.raw_text)
        .where(Filing.raw_text.isnot(None))
        .where(Filing.content_hash.is_(None))
        .where(Filing.chunks.any())
    )
    legacy_rows = legacy_result.all()
    if legacy_rows:
        from sqlalchemy import update
        for row in legacy_rows:
            digest = content_hash(row.raw_text)
            await session.execute(
                update(Filing)
                .where(Filing.id == row.id)
                .values(content_hash=digest, embedded_content_hash=digest)
            )
        await session.commit()
        logger.info("Backfilled content_hash for %d legacy filings", len(legacy_rows))

    result = await session.execute(
        select(Filing)
        .where(Filing.raw_text.isnot(None))
        .where(
            or_(
                ~Filing.chunks.any(),
                (Filing.content_hash.isnot(None))
                & (Filing.embedded_content_hash.isnot(None))
                & (Filing.content_hash != Filing.embedded_content_hash),
            )
        )
        .options(selectinload(Filing.ticker))
    )
    filings = list(result.scalars().all())

    if not filings:
        logger.info("No pending filings to embed")
        return {"filings_processed": 0, "total_chunks": 0, "reembedded": 0}

    chroma = _get_chroma_client()
    oai = _get_openai_client()
    total_chunks = 0
    reembedded = 0

    for filing in filings:
        is_reembed = (
            filing.content_hash is not None
            and filing.embedded_content_hash is not None
            and filing.content_hash != filing.embedded_content_hash
        )
        if is_reembed:
            logger.info("Filing %s content changed, purging old embeddings", filing.accession_number)
            await _purge_filing_embeddings(session, filing, chroma)
            reembedded += 1

        n = await embed_filing(session, filing, chroma_client=chroma, openai_client=oai)
        total_chunks += n

    logger.info(
        "Embedded %d filings (%d re-embedded), %d total chunks",
        len(filings), reembedded, total_chunks,
    )
    return {
        "filings_processed": len(filings),
        "total_chunks": total_chunks,
        "reembedded": reembedded,
    }
