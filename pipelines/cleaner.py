"""Data normalisation utilities for raw SEC filing text.

Provides two levels of cleaning:
  1. clean_filing_text()    — legacy flat-text cleaning (strips all HTML)
  2. parse_filing_sections() — section-aware parsing that preserves structure,
     extracts tables as markdown, and tags each section with its Item header.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag


# ---------------------------------------------------------------------------
# Section definitions for 10-K / 10-Q filings
# ---------------------------------------------------------------------------

SECTION_NAMES: dict[str, str] = {
    "1": "Business",
    "1A": "Risk Factors",
    "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "4": "Mine Safety Disclosures",
    "5": "Market for Common Equity",
    "6": "Selected Financial Data",
    "7": "MD&A",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements",
    "9": "Changes in and Disagreements with Accountants",
    "9A": "Controls and Procedures",
    "9B": "Other Information",
    "10": "Directors and Corporate Governance",
    "11": "Executive Compensation",
    "12": "Security Ownership",
    "13": "Certain Relationships",
    "14": "Principal Accountant Fees",
    "15": "Exhibits and Financial Statement Schedules",
}

# Regex to match Item headers in SEC filings.
# Matches patterns like: "Item 1.", "ITEM 1A.", "Item 7", "ITEM 1A"
_ITEM_PATTERN = re.compile(
    r"^(?:PART\s+[IV]+\s*[-—.]?\s*)?ITEM\s+(\d+[A-Z]?)[\.\s:]",
    re.IGNORECASE,
)


@dataclass
class FilingSection:
    """A parsed section from an SEC filing."""
    item_number: str          # e.g. "1A", "7"
    section_name: str         # e.g. "Risk Factors", "MD&A"
    text: str                 # cleaned prose text
    tables: list[str] = field(default_factory=list)  # tables as markdown


@dataclass
class ParsedFiling:
    """Result of parsing an SEC filing into structured sections."""
    sections: list[FilingSection]
    full_text: str            # fallback: entire filing as flat text


# ---------------------------------------------------------------------------
# Table → markdown conversion
# ---------------------------------------------------------------------------

def _table_to_markdown(table_tag: Tag) -> str:
    """Convert an HTML <table> to a markdown table string."""
    rows = table_tag.find_all("tr")
    if not rows:
        return ""

    md_rows: list[list[str]] = []
    for row in rows:
        cells = row.find_all(["td", "th"])
        md_row = [cell.get_text(strip=True).replace("|", "/") for cell in cells]
        # Skip completely empty rows
        if any(c for c in md_row):
            md_rows.append(md_row)

    if not md_rows:
        return ""

    # Normalize column count
    max_cols = max(len(r) for r in md_rows)
    for r in md_rows:
        while len(r) < max_cols:
            r.append("")

    # Build markdown
    lines = []
    # Header row
    lines.append("| " + " | ".join(md_rows[0]) + " |")
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")
    for row in md_rows[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section-aware parsing
# ---------------------------------------------------------------------------

def _find_item_number(text: str) -> str | None:
    """Extract Item number from text like 'Item 1A. Risk Factors'."""
    m = _ITEM_PATTERN.match(text.strip())
    if m:
        return m.group(1).upper()
    return None


def parse_filing_sections(raw_html: str) -> ParsedFiling:
    """Parse an SEC filing HTML into structured sections with tables.

    Walks the DOM looking for Item headers (Item 1, Item 1A, Item 7, etc.),
    then collects all content between consecutive headers into sections.
    Tables are extracted separately as markdown.

    Falls back to flat text if no sections are detected (e.g., non-SEC docs).
    """
    soup = BeautifulSoup(raw_html, "html.parser")

    # --- Identify section boundaries ---
    # Look for elements whose text matches "Item N." pattern
    boundaries: list[tuple[str, Tag]] = []  # (item_number, element)

    for tag in soup.find_all(["div", "span", "p", "b", "strong", "h1", "h2", "h3", "h4"]):
        text = tag.get_text(strip=True)
        if len(text) > 100:
            continue
        item_num = _find_item_number(text)
        if item_num:
            # Deduplicate: skip if we just saw the same item (nested tags)
            if boundaries and boundaries[-1][0] == item_num:
                continue
            boundaries.append((item_num, tag))

    # Fallback: no sections found → return flat text
    full_text = _clean_flat_text(soup.get_text(separator=" "))
    if len(boundaries) < 2:
        return ParsedFiling(sections=[], full_text=full_text)

    # --- Extract content between boundaries ---
    sections: list[FilingSection] = []

    for i, (item_num, start_tag) in enumerate(boundaries):
        # Collect all sibling/following elements until the next boundary
        end_tag = boundaries[i + 1][1] if i + 1 < len(boundaries) else None

        section_texts: list[str] = []
        section_tables: list[str] = []

        # Walk elements between start and end
        current = start_tag
        while current:
            current = current.find_next()
            if current is None:
                break
            if end_tag and current == end_tag:
                break

            # Extract tables separately
            if isinstance(current, Tag) and current.name == "table":
                md = _table_to_markdown(current)
                if md and len(md) > 20:
                    section_tables.append(md)
                # Skip the table's children
                continue

            # Skip children of tables (already handled)
            if isinstance(current, Tag) and current.find_parent("table"):
                continue

            # Collect text from leaf-ish elements
            if isinstance(current, Tag) and current.name in ("p", "div", "span", "li"):
                t = current.get_text(strip=True)
                if t and len(t) > 5:
                    section_texts.append(t)

        text = _clean_flat_text(" ".join(section_texts))
        section_name = SECTION_NAMES.get(item_num, f"Item {item_num}")

        if text or section_tables:
            sections.append(FilingSection(
                item_number=item_num,
                section_name=section_name,
                text=text,
                tables=section_tables,
            ))

    return ParsedFiling(sections=sections, full_text=full_text)


# ---------------------------------------------------------------------------
# Flat text cleaning (legacy + fallback)
# ---------------------------------------------------------------------------

def _clean_flat_text(text: str) -> str:
    """Normalize whitespace and remove boilerplate from extracted text."""
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    # Remove very long sequences of dashes/underscores (table borders)
    text = re.sub(r"[-_=]{10,}", "", text)
    # Decode leftover HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ").replace("&#160;", " ")
    return text.strip()


def clean_filing_text(raw_html: str) -> str:
    """Strip HTML tags, normalize whitespace, and remove boilerplate from SEC filings.

    Legacy function — returns flat text. Use parse_filing_sections() for
    structured output.
    """
    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text(separator=" ")
    return _clean_flat_text(text)


def normalize_ticker(symbol: str) -> str:
    """Uppercase and strip whitespace from a ticker symbol."""
    return symbol.strip().upper()
