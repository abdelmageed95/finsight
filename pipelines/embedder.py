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

CHUNK_SIZE = 512       # tokens (not characters)
CHUNK_OVERLAP = 64     # tokens
EMBEDDING_MODEL = "text-embedding-3-large"
COLLECTION_NAME = "finsight_filings"

# tiktoken encoder for OpenAI models (cl100k_base covers gpt-5-nano, embeddings-3)
_encoding = tiktoken.get_encoding("cl100k_base")


def _token_len(text: str) -> int:
    """Count tokens using tiktoken cl100k_base encoding."""
    return len(_encoding.encode(text))


# Splitter configured for token-level chunking
_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    length_function=_token_len,
    separators=["\n\n", "\n", ". ", " "],
)


@dataclass
class PreparedChunk:
    """A chunk ready for embedding, with metadata."""
    text: str
    chunk_type: str       # "prose" or "table"
    section_name: str     # e.g. "Risk Factors", "MD&A", "full_text"
    item_number: str      # e.g. "1A", "7", ""


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
    """Split text into ~512-token chunks. Legacy API for backward compat."""
    return _splitter.split_text(text)


def chunk_filing(raw_html: str) -> list[PreparedChunk]:
    """Parse a filing into section-aware, token-level chunks with tables.

    Returns a list of PreparedChunk with metadata for each chunk.
    """
    from pipelines.cleaner import parse_filing_sections

    parsed = parse_filing_sections(raw_html)

    chunks: list[PreparedChunk] = []

    if parsed.sections:
        # Section-aware chunking
        for section in parsed.sections:
            # Chunk prose within this section
            if section.text and _token_len(section.text) > 10:
                text_chunks = _splitter.split_text(section.text)
                for tc in text_chunks:
                    chunks.append(PreparedChunk(
                        text=tc,
                        chunk_type="prose",
                        section_name=section.section_name,
                        item_number=section.item_number,
                    ))

            # Each table is its own chunk (prefixed with section context)
            for table_md in section.tables:
                if _token_len(table_md) < 10:
                    continue
                # If table is too large, split it too
                if _token_len(table_md) > CHUNK_SIZE * 2:
                    table_chunks = _splitter.split_text(table_md)
                    for tc in table_chunks:
                        chunks.append(PreparedChunk(
                            text=f"[Table from {section.section_name}]\n{tc}",
                            chunk_type="table",
                            section_name=section.section_name,
                            item_number=section.item_number,
                        ))
                else:
                    chunks.append(PreparedChunk(
                        text=f"[Table from {section.section_name}]\n{table_md}",
                        chunk_type="table",
                        section_name=section.section_name,
                        item_number=section.item_number,
                    ))
    else:
        # Fallback: flat text chunking (non-SEC docs or parsing failure)
        if parsed.full_text and _token_len(parsed.full_text) > 10:
            text_chunks = _splitter.split_text(parsed.full_text)
            for tc in text_chunks:
                chunks.append(PreparedChunk(
                    text=tc,
                    chunk_type="prose",
                    section_name="full_text",
                    item_number="",
                ))

    logger.info(
        "Chunked filing: %d total chunks (%d prose, %d tables, %d sections)",
        len(chunks),
        sum(1 for c in chunks if c.chunk_type == "prose"),
        sum(1 for c in chunks if c.chunk_type == "table"),
        len(parsed.sections),
    )
    return chunks


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_texts(texts: list[str], client: OpenAI | None = None) -> list[list[float]]:
    """Embed a batch of texts using OpenAI text-embedding-3-large."""
    if not texts:
        return []
    client = client or _get_openai_client()
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


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
