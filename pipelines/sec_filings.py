"""Download 10-K and 10-Q filings from SEC EDGAR and store in Postgres."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import get_or_create_ticker
from db.models import Filing
from pipelines.hashing import content_hash

logger = logging.getLogger(__name__)

# SEC EDGAR requires a descriptive User-Agent
EDGAR_HEADERS = {
    "User-Agent": "FinSight Research Agent contact@finsight.dev",
    "Accept-Encoding": "gzip, deflate",
}
EDGAR_COMPANY_SEARCH = "https://efts.sec.gov/LATEST/search-index"
EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
EDGAR_FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{primary_doc}"


async def _get_cik(symbol: str) -> str | None:
    """Resolve a ticker symbol to a CIK number via SEC EDGAR company tickers exchange JSON."""
    # This endpoint is ~200KB (vs ~7MB for company_tickers.json)
    url = "https://www.sec.gov/files/company_tickers_exchange.json"
    async with httpx.AsyncClient(headers=EDGAR_HEADERS, timeout=60) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    symbol_upper = symbol.upper()
    # Format: {"fields": [...], "data": [[cik, name, ticker, exchange], ...]}
    fields = data.get("fields", [])
    try:
        ticker_idx = fields.index("ticker")
        cik_idx = fields.index("cik")
    except ValueError:
        logger.error("Unexpected EDGAR response format: %s", fields)
        return None

    for row in data.get("data", []):
        if row[ticker_idx].upper() == symbol_upper:
            return str(row[cik_idx]).zfill(10)
    return None


async def _fetch_submissions(cik: str) -> dict:
    """Fetch the submissions JSON for a CIK."""
    url = EDGAR_SUBMISSIONS_URL.format(cik=cik)
    async with httpx.AsyncClient(headers=EDGAR_HEADERS, timeout=60) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def _download_filing_text(cik: str, accession: str, primary_doc: str) -> str:
    """Download the full text of a specific filing.

    Retries up to 3 times with exponential backoff on transient errors.
    SEC EDGAR throttles aggressively under burst load; retries with backoff
    are nearly always sufficient.
    """
    accession_clean = accession.replace("-", "")
    url = EDGAR_FILING_URL.format(cik=cik, accession=accession_clean, primary_doc=primary_doc)

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(
                headers=EDGAR_HEADERS, timeout=60, follow_redirects=True
            ) as client:
                resp = await client.get(url)
                # Retry on 429 (throttle) and 5xx (transient server errors).
                if resp.status_code in (429,) or 500 <= resp.status_code < 600:
                    raise httpx.HTTPStatusError(
                        f"transient {resp.status_code} from {url}",
                        request=resp.request,
                        response=resp,
                    )
                resp.raise_for_status()
                return resp.text
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            last_err = e
            if attempt < 2:
                wait = 1.0 * (2**attempt)  # 1s, 2s
                logger.warning(
                    "SEC download attempt %d/3 failed for %s: %r — retrying in %.1fs",
                    attempt + 1, accession, e, wait,
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    "SEC download exhausted retries for %s: %r url=%s",
                    accession, e, url,
                )

    # Re-raise the last error so the caller's except block runs and we skip this filing.
    raise last_err if last_err else httpx.RequestError(f"unknown failure downloading {url}")


def _parse_sec_date(value: str | None) -> datetime | None:
    """Parse an SEC 'YYYY-MM-DD' date string; return None when absent/malformed."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


def _extract_filings_metadata(submissions: dict, form_types: tuple = ("10-K", "10-Q")) -> list[dict]:
    """Parse the submissions JSON to extract recent filing metadata.

    Captures `reportDate` (the fiscal period the filing covers) alongside
    `filingDate` — the two differ, and the period date drives fiscal-year
    retrieval filtering.
    """
    recent = submissions.get("filings", {}).get("recent", {})
    if not recent:
        return []

    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    filings = []
    for i, form in enumerate(forms):
        if form in form_types and i < len(dates) and i < len(accessions) and i < len(primary_docs):
            filings.append(
                {
                    "filing_type": form,
                    "filed_date": dates[i],
                    "report_date": report_dates[i] if i < len(report_dates) else "",
                    "accession_number": accessions[i],
                    "primary_doc": primary_docs[i],
                }
            )
    return filings


async def ingest_sec_filings(
    session: AsyncSession,
    symbol: str,
    form_types: tuple = ("10-K", "10-Q"),
    max_filings: int = 4,
) -> dict:
    """Full pipeline: resolve CIK, list filings, download text, persist to DB.

    Default `max_filings=4` covers the most recent 10-K plus the last three
    10-Qs — plenty of context for an analyst-grade report and cuts first-run
    latency dramatically vs. pulling 10. Subsequent runs skip filings that
    are already stored, so growing history accrues naturally over time.

    Per-filing downloads are issued concurrently (capped at 4) so a fresh
    ticker takes one round-trip to SEC instead of N.

    Returns summary dict.
    """
    symbol = symbol.upper()
    logger.info("Fetching SEC filings for %s", symbol)

    cik = await _get_cik(symbol)
    if not cik:
        logger.warning("Could not resolve CIK for %s", symbol)
        return {"symbol": symbol, "filings_ingested": 0, "error": "CIK not found"}

    submissions = await _fetch_submissions(cik)
    filings_meta = _extract_filings_metadata(submissions, form_types=form_types)
    filings_meta = filings_meta[:max_filings]

    ticker = await get_or_create_ticker(session, symbol)

    # First pass: insert filing rows that don't yet exist. Returns the list
    # of metas whose row we just created (which need a download).
    to_download: list[dict] = []
    for meta in filings_meta:
        existing_stmt = pg_insert(Filing).values(
            ticker_id=ticker.id,
            filing_type=meta["filing_type"],
            filed_date=datetime.strptime(meta["filed_date"], "%Y-%m-%d"),
            period_of_report=_parse_sec_date(meta.get("report_date")),
            accession_number=meta["accession_number"],
            source_url=EDGAR_FILING_URL.format(
                cik=cik,
                accession=meta["accession_number"].replace("-", ""),
                primary_doc=meta["primary_doc"],
            ),
        ).on_conflict_do_nothing(index_elements=["accession_number"])

        result = await session.execute(existing_stmt)
        if result.rowcount == 0:
            logger.debug(
                "Filing %s already exists, skipping download",
                meta["accession_number"],
            )
            continue
        to_download.append(meta)

    if not to_download:
        await session.commit()
        logger.info("Ingested 0 filings for %s (all cached)", symbol)
        return {"symbol": symbol, "filings_ingested": 0}

    # Second pass: download in parallel, capped concurrency to stay friendly
    # to SEC's 10 req/sec policy. CIK is the same across all filings so we
    # don't burst the submissions endpoint.
    sem = asyncio.Semaphore(4)

    async def _one(meta: dict) -> tuple[dict, str | None, Exception | None]:
        async with sem:
            try:
                text = await _download_filing_text(
                    cik, meta["accession_number"], meta["primary_doc"]
                )
                return (meta, text, None)
            except httpx.HTTPError as e:
                return (meta, None, e)

    results = await asyncio.gather(*[_one(m) for m in to_download])

    from sqlalchemy import update
    ingested = 0
    for meta, raw_text, err in results:
        if err is not None or raw_text is None:
            logger.error(
                "Failed to download filing %s after retries: %r",
                meta["accession_number"], err,
            )
            continue
        hash_val = content_hash(raw_text)
        await session.execute(
            update(Filing)
            .where(Filing.accession_number == meta["accession_number"])
            .values(raw_text=raw_text, content_hash=hash_val)
        )
        ingested += 1
        logger.info(
            "Downloaded %s filing %s (%d bytes)",
            meta["filing_type"], meta["accession_number"], len(raw_text),
        )

    await session.commit()
    logger.info("Ingested %d/%d filings for %s", ingested, len(to_download), symbol)
    return {"symbol": symbol, "filings_ingested": ingested}
