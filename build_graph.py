"""
Build a lightweight knowledge graph on top of data/processed/chunks.jsonl,
to support graph-aware queries the existing vector-only retrieval (Job 1 /
Job 2 in rag_chain.py) can't answer: pathway questions ("what comes after
Seed funding?"), bundling questions ("what pairs with this for a full
funding + mentorship package?"), and same-agency discovery ("what else
does this agency run?"). It also merges the same programme when it's
listed on more than one page (e.g. raiSE appears on both the funding page
and the partnerships page as two separate chunks today).

This does not replace the vector database -- it's a second, small index
that sits alongside it. Chroma still answers "what's semantically similar
to this query"; this graph answers "what's connected to this thing."

Node types:
    Programme    -- an individual fund/programme/scheme (one per card, or
                     one per SGPO funding tier page)
    Agency       -- the agency that runs a programme (parsed out of the
                     "(...)" suffix on card titles, e.g. "(NEA)")
    ResourceType -- funding / manpower / mentorship / network / etc.
    Category     -- the listing section a programme appeared under (e.g.
                     "Government Grants", "For Individuals")

Edge types:
    OFFERED_BY    Programme -> Agency
    PROVIDES      Programme -> ResourceType
    LISTED_UNDER  Programme -> Category
    NEXT_TIER     Programme -> Programme   (Seed -> Sprout -> Scale; this
                                             is hand-authored, not inferred,
                                             since SGPO's own tier order is
                                             known ahead of time)

Requires networkx (pip install networkx --break-system-packages).

Run from the project root, after extract_and_chunk.py has produced
chunks.jsonl:
    python build_graph.py
"""

import json
import re
from collections import defaultdict
from pathlib import Path

import networkx as nx
from networkx.readwrite import json_graph

CHUNKS_JSONL = Path("data/processed/chunks.jsonl")
GRAPH_JSON = Path("data/processed/graph.json")

# page_types that use the card-aware splitter in extract_and_chunk.py --
# each of their non-intro chunks is "[Section] Title: Description" and
# represents one Programme.
CARD_PAGE_TYPES = {"funding_listing", "partnerships_listing", "volunteering_listing"}

# SGPO's own staged funding programme. Order matters and is known in
# advance -- this isn't something to try to infer from chunk text.
TIER_ORDER = ["Seed", "Sprout", "Scale"]
TIER_SOURCE_PATTERN = re.compile(r"Funding_(\w+)\.pdf")

# Matches chunks produced by extract_and_chunk.py's cards_to_chunks():
# f"{prefix}{title}: {description}" where prefix is "[Section] " or "".
# Only the section bracket is parsed with a regex; title/description are
# split on the LAST colon in the remaining text, not the first -- some
# real titles contain their own colon (e.g. "Social Enterprise Support:
# raiSE", "Businesses: GoBusiness (Multi-Agency)"), and the description
# that extract_and_chunk.py produces never contains a colon in this
# dataset, so the final colon is reliably the true title/description
# boundary.
SECTION_PREFIX_PATTERN = re.compile(r"^\[(?P<section>[^\]]+)\]\s+(?P<rest>.*)$", re.DOTALL)

# A parsed title over this length is almost certainly a page-intro
# paragraph that happens to contain a colon, not a real card title --
# skip it rather than create a junk Programme node.
MAX_TITLE_LEN = 100

# Agency suffix on card titles, e.g. "Lively Places Fund (URA-HDB)" -> "URA-HDB"
AGENCY_SUFFIX_PATTERN = re.compile(r"\(([^)]+)\)\s*$")

# Minimum length for a title to be eligible for the alias-merge pass below
# -- guards against short, generic titles ("Grants", "Fund") accidentally
# absorbing unrelated programmes just because the word appears elsewhere.
MIN_ALIAS_TITLE_LEN = 4


def load_chunks():
    records = []
    with open(CHUNKS_JSONL) as f:
        for line in f:
            records.append(json.loads(line))
    return records


def parse_card(text):
    """Try to read a chunk's text as a card ("[Section] Title: Description").
    Returns (section, title, description) or None if it doesn't look like
    a card (e.g. it's the page-intro chunk).

    Splits on the LAST colon in the text (see SECTION_PREFIX_PATTERN
    comment above for why) -- if there's no colon at all, it isn't a
    card."""
    section_match = SECTION_PREFIX_PATTERN.match(text)
    if section_match:
        section = section_match.group("section").strip()
        rest = section_match.group("rest")
    else:
        section = None
        rest = text

    if ":" not in rest:
        return None
    title, desc = rest.rsplit(":", 1)
    title, desc = title.strip(), desc.strip()
    if not title or not desc or len(title) > MAX_TITLE_LEN:
        return None
    return section, title, desc


def parse_agency(title):
    match = AGENCY_SUFFIX_PATTERN.search(title)
    return match.group(1).strip() if match else None


def build_programme_nodes(records):
    """One entry per distinct card title -- multiple chunks with the exact
    same title (shouldn't normally happen, but is possible if a card is
    re-listed) are merged as they're encountered."""
    programmes = {}  # title -> programme dict
    skipped = 0

    for r in records:
        if r["page_type"] not in CARD_PAGE_TYPES:
            continue
        parsed = parse_card(r["text"])
        if parsed is None:
            skipped += 1
            continue
        section, title, desc = parsed
        agency = parse_agency(title)

        if title not in programmes:
            programmes[title] = {
                "title": title,
                "kind": "programme",
                "description": desc,
                "agencies": set(),
                "resource_types": set(),
                "sections": set(),
                "chunk_ids": [],
                "source_files": set(),
            }
        p = programmes[title]
        if agency:
            p["agencies"].add(agency)
        if section:
            p["sections"].add(section)
        p["resource_types"].update(r["resource_types"])
        p["chunk_ids"].append(r["chunk_id"])
        p["source_files"].add(r["source_file"])

    print(f"Parsed {len(programmes)} programme cards from listing pages "
          f"({skipped} chunk(s) skipped as non-card, e.g. page intros).")
    return programmes


def build_tier_nodes(records):
    """SGPO's own Seed / Sprout / Scale funding tiers. Each tier's chunks
    (from block-merge chunking, since these are prose pages) are grouped
    by source_file into a single Programme node."""
    by_file = defaultdict(list)
    for r in records:
        if r["page_type"] == "funding_tier":
            by_file[r["source_file"]].append(r)

    tiers = {}
    for source_file, chunks in by_file.items():
        match = TIER_SOURCE_PATTERN.search(source_file)
        tier_name = match.group(1) if match else source_file
        title = f"SGPO {tier_name} Funding"
        tiers[title] = {
            "title": title,
            "kind": "programme",
            "tier_name": tier_name,
            "description": chunks[0]["text"][:200],
            "agencies": {"SGPO"},
            "resource_types": set().union(*(set(c["resource_types"]) for c in chunks)),
            "sections": set(),
            "chunk_ids": [c["chunk_id"] for c in chunks],
            "source_files": {source_file},
        }

    print(f"Parsed {len(tiers)} SGPO funding-tier programme(s) from prose pages.")
    return tiers


def _contains_as_word(needle, haystack):
    pattern = r"(?<!\w)" + re.escape(needle.lower()) + r"(?!\w)"
    return re.search(pattern, haystack.lower()) is not None


def merge_aliases(programmes):
    """Same programme, different titles across pages (e.g. 'raiSE' on the
    partnerships page vs. 'Social Enterprise Support: raiSE' on the
    funding page) are two separate dict entries at this point. This is a
    simple heuristic, not real entity resolution: if one title appears as
    a whole word inside another, treat them as the same programme and
    merge their data under the longer (more descriptive) title.

    This will occasionally over- or under-merge on edge cases -- it's a
    starting point, meant to be tightened once you see it run against
    real data, not a guarantee of correct entity resolution."""
    titles = sorted(programmes.keys(), key=len)  # shortest first
    merged_into = {}  # short_title -> canonical_title
    used = set()

    for short in titles:
        if short in used or len(short) < MIN_ALIAS_TITLE_LEN:
            continue
        for long in titles:
            if long == short or long in used:
                continue
            if _contains_as_word(short, long):
                merged_into[short] = long
                used.add(short)
                break

    for short, canonical in merged_into.items():
        src = programmes.pop(short)
        dst = programmes[canonical]
        dst["agencies"] |= src["agencies"]
        dst["resource_types"] |= src["resource_types"]
        dst["sections"] |= src["sections"]
        dst["chunk_ids"].extend(src["chunk_ids"])
        dst["source_files"] |= src["source_files"]
        dst.setdefault("aliases", set()).add(short)
        print(f"  merged '{short}' into '{canonical}'")

    if merged_into:
        print(f"Merged {len(merged_into)} alias title(s) across pages.")
    return programmes


def build_graph(programmes):
    g = nx.DiGraph()

    for title, p in programmes.items():
        g.add_node(
            title,
            kind="programme",
            description=p["description"],
            chunk_ids=sorted(p["chunk_ids"]),
            source_files=sorted(p["source_files"]),
            aliases=sorted(p.get("aliases", [])),
        )
        for agency in p["agencies"]:
            g.add_node(agency, kind="agency")
            g.add_edge(title, agency, type="OFFERED_BY")
        for rtype in p["resource_types"]:
            g.add_node(rtype, kind="resource_type")
            g.add_edge(title, rtype, type="PROVIDES")
        for section in p["sections"]:
            g.add_node(section, kind="category")
            g.add_edge(title, section, type="LISTED_UNDER")

    # Hand-authored tier progression, since the order is known in advance.
    tier_titles = {t: f"SGPO {t} Funding" for t in TIER_ORDER}
    for a, b in zip(TIER_ORDER, TIER_ORDER[1:]):
        title_a, title_b = tier_titles[a], tier_titles[b]
        if title_a in g and title_b in g:
            g.add_edge(title_a, title_b, type="NEXT_TIER")

    return g


def save_graph(g, path=GRAPH_JSON):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json_graph.node_link_data(g, edges="edges")
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=list)
    print(f"\nSaved graph to {path}: {g.number_of_nodes()} nodes, "
          f"{g.number_of_edges()} edges.")


def load_graph(path=GRAPH_JSON):
    with open(path) as f:
        data = json.load(f)
    return json_graph.node_link_graph(data, edges="edges")


# ------------------------------------------------------------- query helpers ----
# Small traversal helpers, meant to be imported by rag_chain.py / app.py for
# the pathway/bundling use case. Kept here since they operate directly on
# the graph structure defined above.

def get_next_tier(g, programme_title):
    """Given a programme title (e.g. 'SGPO Seed Funding'), return the next
    tier's title, or None if there isn't one / it isn't a tiered programme."""
    for _, target, data in g.out_edges(programme_title, data=True):
        if data.get("type") == "NEXT_TIER":
            return target
    return None


def get_same_agency(g, programme_title):
    """Other programmes offered by the same agency/agencies as this one."""
    agencies = [t for _, t, d in g.out_edges(programme_title, data=True) if d.get("type") == "OFFERED_BY"]
    peers = set()
    for agency in agencies:
        for source, _, d in g.in_edges(agency, data=True):
            if d.get("type") == "OFFERED_BY" and source != programme_title:
                peers.add(source)
    return sorted(peers)


def get_bundle_candidates(g, programme_title, needed_resource_types):
    """Other programmes that together with this one cover a set of needed
    resource types this programme doesn't provide alone."""
    own_types = {t for _, t, d in g.out_edges(programme_title, data=True) if d.get("type") == "PROVIDES"}
    missing_types = set(needed_resource_types) - own_types
    if not missing_types:
        return []

    candidates = set()
    for rtype in missing_types:
        for source, _, d in g.in_edges(rtype, data=True):
            if d.get("type") == "PROVIDES" and source != programme_title:
                candidates.add(source)
    return sorted(candidates)


def main():
    records = load_chunks()
    print(f"Loaded {len(records)} chunks from {CHUNKS_JSONL}")

    programmes = build_programme_nodes(records)
    programmes.update(build_tier_nodes(records))
    programmes = merge_aliases(programmes)

    g = build_graph(programmes)
    save_graph(g)


if __name__ == "__main__":
    main()
