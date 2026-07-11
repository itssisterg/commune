"""
Extract text from locally-saved PDFs, strip known SGPO/gov.sg boilerplate,
chunk it, and attach metadata from data/metadata.csv.

Two chunking strategies are used depending on page_type in metadata.csv:
- Listing pages (funding_listing, partnerships_listing, volunteering_listing):
  card-aware splitting -- each individual fund/programme becomes its own
  chunk, tagged with the section it appeared under (e.g. "Government Grants").
- Everything else (prose/FAQ pages like funding tiers, about page):
  block-merge chunking, one page's cleaned content merged up to MAX_CHUNK_WORDS.

Run from the project root:
    python extract_and_chunk.py
"""

import json
import re
from pathlib import Path

import pandas as pd
import pdfplumber

RAW_DIR = Path("data/raw")
METADATA_CSV = Path("data/metadata.csv")
OUTPUT_JSONL = Path("data/processed/chunks.jsonl")

MIN_CHUNK_WORDS = 20
MAX_CHUNK_WORDS = 120

# page_types (from metadata.csv) that get the card-aware splitter.
CARD_PAGE_TYPES = {"funding_listing", "partnerships_listing", "volunteering_listing"}

# Known section headings on the listing pages. A line matching one of these
# exactly starts a new section context; it is not treated as a card itself.
# Extend this set if you add more listing pages with different headings.
SECTION_HEADERS = {
    "Government Grants", "Commercial Ideas", "Resources",
    "For Ground-ups and Organisations", "For Individuals",
    "Volunteering and Giving Opportunities",
}

# Per-card resource_type overrides for Ecosystem_*.pdf listing pages.
# Keyed by exact card title (as produced by split_into_cards). Falls back
# to the row-level default in metadata.csv (now "general") for any card
# not listed here, and for the page-intro chunk.
CARD_TAG_OVERRIDES = {
    # -- Ecosystem_Funding_and_Resources --
    "Lively Places Fund (URA-HDB)": ["funding"],
    "Maritime Outreach Fund (MPA)": ["funding"],
    "NEA Call for Ideas Fund (NEA)": ["funding"],
    "Our SG Fund (MCCY)": ["funding"],
    "SG Eco Fund (MSE)": ["funding"],
    "Young Changemakers - Youth Heritage Kickstarter Fund (NYC-Changemakers)": ["funding"],
    "Businesses: GoBusiness (Multi-Agency)": ["network"],
    "Social Enterprise Support: raiSE": ["mentorship", "network"],
    "State Properties for Social & Community Uses (SLA)": ["space"],

    # -- Ecosystem_Partnerships (Grounds-ups/Orgs + Individuals) --
    "Bagus Together": ["network", "capability_building"],
    "Digital for Life (Multi-Agency)": ["capability_building", "network"],
    "Our SG Arts Plan (NAC)": ["network"],
    "Our SG Arts Plan (2023 - 2027) (NAC)": ["network"],
    "'Long Island' (URA)": ["network"],
    "Pro Enterprise Panel": ["mentorship", "network"],
    "raiSE": ["mentorship", "network"],
    "SG Youth Plan (NYC)": ["network"],
    "School-Industry Partnership (MOE)": ["network", "capability_building"],
    "Total Defence (TD) Sandbox (MINDEF)": ["network"],
    "Caring SG Commuters Movement (Multi-Agency)": ["network"],
    "Nature Kakis (NParks)": ["manpower", "network"],
    "One Service Kakis Network (MSO)": ["manpower", "network"],
    "Young ChangeMakers Programme (NYC-Changemakers)": ["funding", "mentorship"],

    # -- Ecosystem_Volunteering_and_Giving --
    "Community Foundation of Singapore": ["funding", "network"],
    "Dementia Singapore": ["manpower"],
    "DISCOVER Civic Action (NYC)": ["manpower", "network"],
    "Giving.sg": ["funding", "manpower"],
    "Mentoring.SG (Multi-Agency)": ["mentorship"],
    "MSFCare Network (MSF)": ["manpower", "network"],
    "NEA Volunteer Corps (NEA)": ["manpower"],
    "OneMillionTrees Facilitator (NParks)": ["manpower"],
    "PA Community Volunteering (PA)": ["manpower"],
    "Volunteer.gov.sg (MCCY)": ["manpower"],
}

# UI chrome / calls-to-action that sometimes get parsed as a stray "card" --
# dropped rather than kept as low-value chunks.
CTA_NOISE = {
    "Submit proposal",
    "If the above is not what you are looking for, share your proposal",
}

# --- Boilerplate filtering ---------------------------------------------

LINE_DROP_PATTERNS = [
    r"^\d{1,2}/\d{1,2}/\d{4},\s*\d{1,2}:\d{2}\s",       # "10/07/2026, 17:41 <title> | ..."
    r"^A Singapore Government Agency Website",
    r"^https?://\S+(\s+\d+/\d+)?$",                      # URL, optional trailing "N/M"
    r"^Home\s",                                          # breadcrumb nav
    r"^©\s*\d{4}",                                       # copyright line
]

LINE_DROP_CONTAINS = [
    "ScamShield",
    "transfer money or disclose bank",
    "details over a phone call",
    "How to identify",
]

LINE_DROP_FULLMATCH_PATTERNS = [
    r"scam\.?",  # stray wrapped tail of the ScamShield warning
]

LINE_DROP_EXACT = {
    "Take action", "SG Partnerships Fund", "Feature stories", "Discover your role",
    "About", "Reach us", "Contact", "Feedback", "Report Vulnerability",
    "Privacy Statement", "Terms of Use", "REACH", "Made with", "Built by",
    "Singapore Government Partnerships Office",
    "On this page",
}


def clean_page_lines(raw_text: str):
    """Strip known boilerplate and return the surviving lines, in order."""
    lines = raw_text.split("\n")
    kept = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in LINE_DROP_EXACT:
            continue
        if any(re.match(p, stripped) for p in LINE_DROP_PATTERNS):
            continue
        if any(sub in stripped for sub in LINE_DROP_CONTAINS):
            continue
        if any(re.fullmatch(p, stripped, re.IGNORECASE) for p in LINE_DROP_FULLMATCH_PATTERNS):
            continue
        kept.append(stripped)
    return kept


def extract_pages(pdf_path: Path):
    """Return cleaned lines, grouped by page: list[list[str]]."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            raw = page.extract_text() or ""
            lines = clean_page_lines(raw)
            if lines:
                pages.append(lines)
    return pages


# --- Strategy A: card-aware splitting (listing pages) -------------------

def split_into_cards(pages):
    """
    Parse listing pages into individual (section, title, description) cards.
    A line is a 'title' when it doesn't end in terminal punctuation; the
    following line(s) become its description until a line ends in . ! or ?
    -- this matches how these specific pages wrap in the PDF (title line,
    then a 1-2 line description ending in punctuation).
    """
    all_lines = [line for page in pages for line in page]

    intro_lines = []
    entries = []
    current_section = None
    current_title = None
    desc_buffer = []
    seen_section_or_card = False

    def flush():
        nonlocal current_title, desc_buffer
        if current_title and current_title not in CTA_NOISE:
            desc = " ".join(desc_buffer).strip()
            if desc not in CTA_NOISE:
                entries.append({
                    "section": current_section,
                    "title": current_title,
                    "description": desc,
                })
        current_title = None
        desc_buffer = []

    for line in all_lines:
        if line in SECTION_HEADERS:
            flush()
            current_section = line
            seen_section_or_card = True
            continue

        if not seen_section_or_card:
            intro_lines.append(line)
            continue

        if current_title is None:
            current_title = line
            desc_buffer = []
            continue

        desc_buffer.append(line)
        if line.rstrip().endswith((".", "!", "?")):
            flush()

    flush()  # catch any dangling entry
    return intro_lines, entries


def cards_to_chunks(intro_lines, entries, default_resource_types, source_file=""):
    """Returns a list of (text, resource_types) pairs -- each card gets its
    own accurate tags via CARD_TAG_OVERRIDES where available, falling back
    to the file's page-level default tag (e.g. "general") otherwise. Falls
    back cases are printed so it's easy to see which new cards (e.g. from
    a newly-added provider) still need an override entry."""
    chunks = []
    if intro_lines:
        chunks.append((" ".join(intro_lines), default_resource_types))
    for e in entries:
        prefix = f"[{e['section']}] " if e["section"] else ""
        text = f"{prefix}{e['title']}: {e['description']}".strip()
        if text:
            if e["title"] in CARD_TAG_OVERRIDES:
                tags = CARD_TAG_OVERRIDES[e["title"]]
            else:
                tags = default_resource_types
                print(f"  (no override for card '{e['title']}' in {source_file} "
                      f"-- using page-level default {default_resource_types})")
            chunks.append((text, tags))
    return chunks


# --- Strategy B: block-merge chunking (prose/FAQ pages) ------------------

def chunk_as_blocks(pages, default_resource_types, min_words=MIN_CHUNK_WORDS, max_words=MAX_CHUNK_WORDS):
    blocks = [" ".join(page) for page in pages if page]

    raw_chunks = []
    current = []
    current_words = 0

    for block in blocks:
        block_words = len(block.split())
        if current_words + block_words > max_words and current_words >= min_words:
            raw_chunks.append(" ".join(current))
            current = [block]
            current_words = block_words
        else:
            current.append(block)
            current_words += block_words

    if current:
        raw_chunks.append(" ".join(current))

    if len(raw_chunks) > 1 and len(raw_chunks[-1].split()) < min_words:
        raw_chunks[-2] = raw_chunks[-2] + " " + raw_chunks[-1]
        raw_chunks.pop()

    return [(text, default_resource_types) for text in raw_chunks]


def main():
    manifest = pd.read_csv(METADATA_CSV)
    OUTPUT_JSONL.parent.mkdir(parents=True, exist_ok=True)

    all_records = []
    chunk_id = 0

    for _, row in manifest.iterrows():
        pdf_path = RAW_DIR / row["filename"]
        if not pdf_path.exists():
            print(f"WARNING: {pdf_path} not found, skipping")
            continue

        pages = extract_pages(pdf_path)
        if not pages:
            print(f"WARNING: no text extracted from {pdf_path} (check manually)")
            continue

        page_type = row["page_type"]
        default_resource_types = [t.strip() for t in str(row["resource_types"]).split(";")]

        if page_type in CARD_PAGE_TYPES:
            intro_lines, entries = split_into_cards(pages)
            chunks = cards_to_chunks(intro_lines, entries, default_resource_types, row["filename"])
        else:
            chunks = chunk_as_blocks(pages, default_resource_types)

        for chunk_text, resource_types in chunks:
            record = {
                "chunk_id": chunk_id,
                "text": chunk_text,
                "provider": row["provider"],
                "page_type": page_type,
                "resource_types": resource_types,
                "source_file": row["filename"],
                "source_url": row.get("source_url", ""),
                "notes": row.get("notes", ""),
            }
            all_records.append(record)
            chunk_id += 1

        print(f"{pdf_path.name}: {len(chunks)} chunks")

    with open(OUTPUT_JSONL, "w") as f:
        for record in all_records:
            f.write(json.dumps(record) + "\n")

    print(f"\nDone. {len(all_records)} total chunks written to {OUTPUT_JSONL}")


if __name__ == "__main__":
    main()