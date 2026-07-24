"""
Commune -- a citizen-facing assistant for community builders navigating the
Singapore Government Partnerships Office ecosystem.

Layout mirrors Claude's own UI: a slim sidebar for branding/navigation, and
the actual input composer lives in the main canvas -- centered as a hero on
first load, then sitting below the conversation once it starts.

Run with:
    streamlit run app.py
"""

import os
import re
from html import escape as _escape

import streamlit as st
import streamlit.components.v1 as components

from rag_chain import generate_job1, generate_job2, generate_job3

# Streamlit only reads .streamlit/config.toml at process startup -- it can't
# be changed from inside a running script. Rather than ship that file
# separately, we write it ourselves (once) right next to this script, so
# app.py is the only file you need to keep track of. Without this, the app
# falls back to Streamlit's raw theme -- which follows the OS/browser's
# dark-mode setting -- for anything our CSS doesn't explicitly override,
# most importantly the dropdown menus, which render in a portal outside
# the .main container our CSS is scoped to.
_THEME_CONFIG = """[theme]
base = "light"
primaryColor = "#E15B3F"
backgroundColor = "#F7F4EC"
secondaryBackgroundColor = "#FFFFFF"
textColor = "#1E2A26"
font = "sans serif"
"""


def _ensure_theme_config():
    config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".streamlit")
    config_path = os.path.join(config_dir, "config.toml")
    existing = None
    if os.path.exists(config_path):
        with open(config_path) as f:
            existing = f.read()
    if existing == _THEME_CONFIG:
        return False
    os.makedirs(config_dir, exist_ok=True)
    with open(config_path, "w") as f:
        f.write(_THEME_CONFIG)
    return True


_wrote_new_config = _ensure_theme_config()

st.set_page_config(page_title="Commune", page_icon="📌", layout="wide")

if _wrote_new_config:
    st.warning(
        "First-time setup: wrote .streamlit/config.toml next to app.py to lock in "
        "the light theme. Streamlit only picks this up on process start, so please "
        "stop this app (Ctrl+C) and run `streamlit run app.py` again for colors to "
        "look right.",
        icon="⚠️",
    )
    st.stop()


def html(s: str) -> str:
    """st.markdown treats indented lines as Markdown code blocks (escaping
    any HTML inside them). textwrap.dedent alone isn't reliable here once
    snippets get spliced into other templates (a common-prefix dedent can
    end up removing nothing if any spliced-in line has zero indentation),
    so instead strip leading/trailing whitespace from every line
    individually. Safe for HTML/CSS, which don't care about whitespace
    between tags or rules."""
    return "\n".join(line.strip() for line in s.strip("\n").split("\n"))


def safe_text(s: str) -> str:
    """Escape arbitrary user-typed text before it's spliced into a raw HTML
    template, then turn newlines into <br> so multi-line input still reads
    as multiple lines instead of collapsing onto one."""
    return _escape(s or "", quote=True).replace("\n", "<br>")


def render_markdown_lite(s: str) -> str:
    """The RAG answer can contain basic markdown (paragraphs, bullets,
    **bold**, *italic*, [text](url) links). We escape first so nothing in
    the model's output can inject raw HTML, THEN layer a small set of
    markdown-like substitutions on top of the now-safe, escaped text --
    escaping doesn't touch *, [, ], (, ) so this ordering is safe."""
    text = _escape(s or "", quote=True)

    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        text,
    )
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*(?!\*)", r"<em>\1</em>", text)

    lines = text.split("\n")
    out, in_list = [], False
    for line in lines:
        stripped = line.strip()
        is_bullet = stripped.startswith("- ")
        if is_bullet:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{stripped[2:].strip()}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(line)
    if in_list:
        out.append("</ul>")
    text = "\n".join(out)

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    result = "</p><p>".join(p.replace("\n", "<br>") for p in paragraphs) or text.replace("\n", "<br>")
    # drop stray <br> that end up hugging block-level list tags
    result = re.sub(r"<br>\s*(</?(?:ul|li)>)", r"\1", result)
    result = re.sub(r"(</?(?:ul|li)>)\s*<br>", r"\1", result)
    return result


LOGO_SVG = html("""
    <svg width="30" height="30" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
        <line x1="7" y1="7" x2="17" y2="7" stroke="#F7F4EC" stroke-width="1.4" stroke-opacity="0.55"/>
        <line x1="7" y1="7" x2="12" y2="17" stroke="#F7F4EC" stroke-width="1.4" stroke-opacity="0.55"/>
        <line x1="17" y1="7" x2="12" y2="17" stroke="#F7F4EC" stroke-width="1.4" stroke-opacity="0.55"/>
        <circle cx="7" cy="7" r="3.1" fill="#E15B3F"/>
        <circle cx="17" cy="7" r="3.1" fill="#E0A83E"/>
        <circle cx="12" cy="17" r="3.1" fill="#A9BFAE"/>
    </svg>
""")

# ---------------------------------------------------------------- styling ----

st.markdown(html("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700;800&display=swap');

:root {
    --ink: #1E2A26;
    --paper: #F7F4EC;
    --teal: #1F4E46;
    --teal-light: #2E6E63;
    --mustard: #E0A83E;
    --coral: #E15B3F;
    --sage: #A9BFAE;
}

html, body, .stApp, [class*="css"] {
    font-family: 'Open Sans', sans-serif !important;
}

.stApp, .main, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
    background-color: var(--paper) !important;
    color: var(--ink) !important;
}

/* Main canvas text -- dark ink on beige */
.main [data-testid="stMarkdownContainer"] h1,
.main [data-testid="stMarkdownContainer"] h2,
.main [data-testid="stMarkdownContainer"] h3,
.main [data-testid="stMarkdownContainer"] p,
.main [data-testid="stMarkdownContainer"] div,
.main [data-testid="stMarkdownContainer"] span,
.main label, .main .stRadio label, .main .stRadio p {
    color: var(--ink) !important;
    font-family: 'Open Sans', sans-serif !important;
}

/* Composer widgets in the main canvas -- explicit colors, scoped only to
   .main, so nothing here can leak into or be leaked into by the sidebar */
.main .stTextArea textarea {
    background-color: #FFFFFF !important;
    color: var(--ink) !important;
    border: 1px solid #E3DECE !important;
    border-radius: 10px !important;
}
.main .stButton>button {
    background-color: var(--coral) !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 700 !important;
}
.main .stButton>button:hover { background-color: #c94a30 !important; }
.main [data-testid="stWidgetLabel"] p { color: var(--ink) !important; }

/* Multiselect / selectbox -- the closed box lives in .main, but the open
   dropdown list renders in a portal attached to <body>, outside .main, so
   it needs its own unscoped rules or it falls back to Streamlit's raw
   (possibly dark) theme. */
[data-baseweb="select"] > div {
    background-color: #FFFFFF !important;
    border: 1px solid #E3DECE !important;
    border-radius: 10px !important;
}
[data-baseweb="select"] input {
    color: var(--ink) !important;
}
[data-baseweb="select"] input::placeholder {
    color: #7C877F !important;
}
[data-baseweb="select"] svg {
    fill: var(--ink) !important;
}
[data-baseweb="tag"] {
    background-color: var(--teal) !important;
}
[data-baseweb="tag"] span {
    color: #FFFFFF !important;
}
[data-baseweb="popover"] [data-baseweb="menu"] {
    background-color: #FFFFFF !important;
    border: 1px solid #E3DECE !important;
}
[data-baseweb="popover"] [data-baseweb="menu"] li,
[data-baseweb="popover"] [data-baseweb="menu"] li * {
    color: var(--ink) !important;
    background-color: transparent !important;
}
[data-baseweb="popover"] [data-baseweb="menu"] li:hover {
    background-color: #F1EDE0 !important;
}
.main .stTextArea textarea::placeholder {
    color: #7C877F !important;
}

/* Composer card -- native bordered container, not a fake HTML div wrapper */
.main [data-testid="stVerticalBlockBorderWrapper"] {
    background-color: #FFFFFF !important;
    border-radius: 16px !important;
    box-shadow: 0 4px 18px rgba(30, 42, 38, 0.07);
}

/* Sidebar wordmark, next to the logo */
.commune-title-row {
    display: flex;
    align-items: center;
    gap: 0.55rem;
    margin-bottom: 1.4rem;
}
.commune-wordmark {
    font-size: 1.3rem;
    font-weight: 800;
    letter-spacing: -0.01em;
    color: var(--paper) !important;
}

/* Slim sidebar -- branding + new conversation only, like Claude's left nav.
   Colors scoped strictly within [data-testid="stSidebar"] so they cannot
   leak into the main canvas. */
[data-testid="stSidebar"] {
    background-color: #000000 !important;
}
[data-testid="stSidebar"] * {
    color: var(--paper) !important;
    font-family: 'Open Sans', sans-serif !important;
}
[data-testid="stSidebar"] .stButton>button {
    background-color: transparent !important;
    color: var(--paper) !important;
    border: 1px solid rgba(247, 244, 236, 0.35) !important;
    border-radius: 8px;
    font-weight: 600;
    width: 100%;
    text-align: left;
}
[data-testid="stSidebar"] .stButton>button:hover {
    background-color: rgba(247, 244, 236, 0.1) !important;
    border-color: var(--paper) !important;
}

/* Center the main canvas content */
.main .block-container {
    max-width: 720px;
    margin: 0 auto;
    padding-top: 2rem;
}

/* Hero / empty state */
.commune-hero-wrap {
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    padding: 2rem 0 2rem 0;
}
.commune-hero-wrap p.tagline {
    color: #5A6B63 !important;
    font-size: 1.05rem;
    max-width: 460px;
    margin: 0.3rem 0 0 0;
}

/* Pinned noticeboard card (conversation history) */
.commune-card {
    background: #FFFFFF;
    border: 1px solid #E5E0D2;
    border-radius: 4px;
    padding: 1.1rem 1.3rem;
    margin: 1.2rem 0;
    box-shadow: 0 3px 10px rgba(30, 42, 38, 0.08);
    position: relative;
}
.commune-card.assistant {
    transform: rotate(-0.4deg);
    border-left: 3px solid var(--teal);
}
.commune-card.user {
    transform: rotate(0.3deg);
    border-left: 3px solid var(--mustard);
    background: #FFFDF7;
}
.commune-pin {
    position: absolute;
    top: -10px;
    left: 18px;
    font-size: 1.2rem;
}
.commune-label {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: #6E7C75 !important;
    margin-bottom: 0.4rem;
}
.commune-card p,
.commune-card ul,
.commune-card li,
.commune-card strong,
.commune-card em {
    margin: 0;
    line-height: 1.55;
    color: var(--ink) !important;
}
.commune-card ul {
    margin: 0.4rem 0 0 1.1rem;
    padding: 0;
}
.commune-card a {
    color: var(--teal) !important;
    font-weight: 600;
}
</style>
"""), unsafe_allow_html=True)

# ---------------------------------------------------------------- state ----

if "history" not in st.session_state:
    st.session_state.history = []  # list of dicts: mode, query_label, answer, sources

RESOURCE_TYPE_OPTIONS = [
    "funding", "manpower", "mentorship", "network", "capability_building", "space"
]
RESOURCE_TYPE_LABELS = {
    "funding": "💰 Funding",
    "manpower": "🙋 Manpower / Volunteers",
    "mentorship": "🧭 Mentorship",
    "network": "🤝 Network & Partnerships",
    "capability_building": "🛠️ Capability-building",
    "space": "📍 Space / Venue",
}

# ---------------------------------------------------------------- static pages ----

ABOUT_US_MD = """
# About Us

## What this is

An assistant that helps people in Singapore find government support for a community project idea. Describe the idea, or say what kind of help needed (funding, volunteers, mentorship, a venue, connections), and it points to matching programmes with a plain explanation of why, plus a link to the official source. It can also plan a path: what comes next after a funding tier, or what else to pair a programme with.

## Why build this

The Singapore Government Partnerships Office (SGPO) helps Singaporeans and ground-up groups partner with government on community projects. The information on how to do that is spread across several pages: a funding overview, two partnership pages (organisations and individuals), a volunteering page, and separate pages for each funding tier. Reading all of it to check "does this apply to me?" takes time. This assistant answers that in seconds. It also connects programmes to each other, something reading one page at a time can't easily show: which funding tier comes next, which programmes share an agency, which programmes complement each other.

Ideally, the future state of this app can allow the user to retrieve robust information from sources beyond SGPO office, including information made publicly available by community aggregators.

## What it's built on

All answers come from official SGPO web content, saved and processed as of the dates below:

- The SGPO About and FAQ page
- The Funding & Resources page
- The Partnerships & Engagements pages (organisations, and individuals)
- The Volunteering & Giving page
- The three funding tier pages (Seed, Sprout, Scale)

8 source documents, last refreshed 2 June 2026, broken into 53 tagged chunks covering funding, manpower, mentorship, network, and capability-building support. Those chunks are also organised into a small knowledge graph connecting programmes to their agency, their resource types, and (for the Seed, Sprout, Scale tiers) their order. See Methodology for how both pieces work.

## What it can do for the user

1. **Describe the idea in the user's own words.** The assistant searches everything it knows, finds the best-matching programmes, explains why each fits, and gives a concrete next step.
2. **Tell it what kind of support the user needs.** Pick funding, volunteers, mentorship, or another category, and it compares the relevant programmes side by side.
3. **Ask what comes next, or what to pair with.** Describe a programme the user is already on, and the assistant surfaces the next funding tier, other programmes from the same agency, or programmes that cover support the current one doesn't.

All three flows are detailed step by step on the Methodology page.

## Objectives

- Lower the barrier to finding help, so a good community idea doesn't stall on navigating government schemes.
- Never invent information. The assistant answers only from its source material and says plainly when nothing fits.
- Always cite sources, so answers can be checked against the original page.
- Serve individuals, informal ground-up groups, and established organisations alike.
- Surface relationships between programmes, not just individual matches, so users can plan a path rather than a single next step.

## Scope and limitations

- Covers only the SGPO ecosystem pages listed above, not every government scheme in Singapore.
- A snapshot in time, not a live feed. Updates to funding amounts or deadlines won't appear until the data is refreshed.
- A starting point, not a final answer. Confirm eligibility, amounts, and deadlines with the agency or official link before acting.
- Not legal, financial, or grant-writing advice. It points the user to the right people and programmes.
- The pathway feature only recognises situations that clearly match a specific programme. Vague descriptions may not resolve to one, in which case the assistant says so rather than guessing.
"""

METHODOLOGY_MD = """
# Methodology

How the assistant turns official SGPO web pages into answers, in five stages:

1. **Data preparation**: a one-time process that turns raw web pages into a searchable knowledge base.
2. **Building the knowledge graph**: a one-time process that connects programmes to their agency, resource types, and (for tiered funding) their order.
3. **Use case A, "Chat with idea"**: user describes the idea, the assistant finds a fit.
4. **Use case B, "Explore by need"**: user picks a type of support, the assistant compares options.
5. **Use case C, "Plan my pathway"**: user describes a programme they're already on, the assistant surfaces what's next or what pairs with it.

---

## Stage 1: Data preparation

Pages are saved, cleaned of non-content (nav menus, cookie banners, copyright lines), split into tagged pieces, and stored in a searchable index.

```mermaid
flowchart TD
    A[Official SGPO web pages saved as PDFs] --> B[Extract text from each PDF, page by page]
    B --> C[Strip boilerplate: nav menus, cookie notices, copyright lines, breadcrumbs]
    C --> D{What kind of page is it?}
    D -->|"Listing page (funding, partnerships, volunteering)"| E[Split into individual cards, one programme per chunk]
    D -->|"Prose or FAQ page (About, funding tiers)"| F[Merge page content into right-sized chunks]
    E --> G[Tag each chunk: provider, page type, resource type, source link]
    F --> G
    G --> H[Save all tagged chunks to a chunks file]
    H --> I[Convert each chunk's text into a numeric embedding]
    I --> J[(Store chunks and embeddings in a vector database)]
```

**Implementation detail:**

- Each source is a PDF saved from the live SGPO site. Text is extracted page by page with `pdfplumber`.
- Pattern and phrase filters remove known non-content lines: timestamps, "A Singapore Government Agency Website", nav labels like "Home" or "Feedback", scam-warning boilerplate, copyright lines.
- Two chunking strategies apply, based on page type:
  - **Listing pages** use a card-aware splitter. It reads line by line, recognises section headings (e.g. "Government Grants", "For Individuals"), and treats each title plus description as one chunk. This keeps each programme's information intact in a single chunk.
  - **Prose or FAQ pages** use block-merge chunking: content is merged up to a target size (20 to 120 words) so each chunk is substantial but not diluted.
- Each chunk is tagged with provider, page type, resource type(s), and a source link. Resource type defaults come from a metadata file, with per-programme overrides where needed.
- All chunks are written to `chunks.jsonl`, one line per chunk.
- Each chunk's text is embedded using OpenAI's `text-embedding-3-small` model, in batches of 100.
- Chunks and embeddings are stored together in a Chroma vector database, a persistent index for similarity search by semantic meaning. Re-running this step updates existing entries rather than duplicating them.

This step is redone only when source pages change or new ones are added.

---

## Stage 2: Building the knowledge graph

Chunks answer "what's semantically similar to this query." They don't capture how programmes relate to each other. This stage adds a second, small index on top of the same chunks that does.

```mermaid
flowchart TD
    A[Tagged chunks from Stage 1] --> B{Which kind of chunk is it?}
    B -->|Listing-page card| C[Parse into title, description, section]
    B -->|Funding tier page| D[Group chunks into one Seed, Sprout, or Scale programme]
    C --> E["Parse agency from the title, e.g. '(NEA)'"]
    E --> F[Merge programmes that appear under two different titles on different pages]
    D --> F
    F --> G[Build a graph: programme linked to its agency, resource types, and section]
    G --> H[Add a hand-set order: Seed points to Sprout points to Scale]
    H --> I[(Save the graph to a file)]
```

**Implementation detail:**

- Each listing-page chunk is parsed back into its title, description, and section, splitting on the last colon in the text since some real titles contain their own colon (e.g. "Social Enterprise Support: raiSE").
- The agency is read off the end of the title where one appears in parentheses, e.g. "Lively Places Fund (URA-HDB)" gives agency "URA-HDB".
- The three funding tier pages (Seed, Sprout, Scale) are each grouped into a single programme, since their chunking (Stage 1) splits one page into several chunks.
- The same programme sometimes appears under two different titles on different pages (e.g. "raiSE" and "Social Enterprise Support: raiSE"). A simple heuristic merges these: if one title appears as a whole word inside another, they're treated as the same programme. This is a starting point, not guaranteed entity resolution, and is logged when it happens so it can be checked.
- The graph itself has one node per programme, agency, resource type, and section, connected by: programme offered by agency, programme provides resource type, programme listed under section.
- One relationship is set by hand rather than inferred: Seed points to Sprout points to Scale, since SGPO's own tier order is known in advance and isn't something to guess from text.
- The finished graph is saved to a file alongside the chunks and the vector database, so both can be loaded independently at answer time.

This step is redone whenever Stage 1 is redone.

---

## Stage 3: Use case A, "Chat with idea"

User describes idea in free text. The assistant searches everything it knows to find the best fit.

```mermaid
flowchart TD
    A[User types their idea] --> B[Idea is converted into an embedding]
    B --> C[Vector database is searched for the most similar chunks, across all programmes]
    C --> D[Top 6 matches are selected]
    D --> E[Matches are assembled into a context package with source links]
    F[Language model receives idea and the context, with instructions to use only that context] --> G[Model identifies the best-fit programme, explains why, states a next step, cites sources]
    E --> F
    G --> H[Answer is shown with source links]
```

**Implementation detail:**

- Idea is embedded with the same `text-embedding-3-small` model used in data preparation.
- Chroma's `query` returns the 6 chunks closest to idea's embedding, searched across all programmes with no filtering.
- Retrieved chunks are formatted into a numbered context block: provider, resource types, source link, text.
- The context and idea are sent to `gpt-4o-mini` under a system prompt instructing it to identify the best-fit programme(s), explain fit (stage, resource type, eligibility), state a next step, and cite every claim as `[Source: <provider> - <source_url>]`.
- The prompt forbids inventing eligibility criteria, funding amounts, or deadlines not in the context, and requires saying plainly if nothing fits.
- The answer and the retrieved sources are returned together.

---

## Stage 4: Use case B, "Explore by need"

User selects a category of support. The assistant compares programmes that offer it.

```mermaid
flowchart TD
    A[User selects  one or more needs: funding, manpower, mentorship, network, capability-building] --> B[Optionally add more context]
    B --> C[Selection and context converted into an embedding]
    C --> D[Vector database searched broadly: top 50 candidates pulled]
    D --> E{Is this chunk tagged with one of user's selected needs?}
    E -->|No| F[Chunk discarded]
    E -->|Yes| G[Chunk kept, until 8 matches found]
    G --> H[Matches assembled into a context package with source links]
    I[Language model receives selection and context, with instructions to compare and cite sources] --> J[Model produces a side-by-side comparison]
    H --> I
    J --> K[Comparison shown to user with source links]
```

**Implementation detail:**

- If no extra context is given, the search query defaults to a plain list of selected resource types (e.g. "funding, mentorship"); typed context is used otherwise.
- Chroma stores resource types as a comma-joined string, not a list, so filtering can't happen inside the database query. The assistant over-fetches the top 50 closest matches, filters in code for chunks tagged with at least one selected need, and stops once 8 qualify.
- Filtered matches are formatted into the same context block style as Use Case A.
- The context, selected needs, and any extra input are sent to `gpt-4o-mini` under a separate system prompt instructing a comparison of offerings (amount, eligibility, audience) rather than a single recommendation, citing every claim and noting plainly if context is too thin.
- The answer and retrieved sources are returned together.

---

## Stage 5: Use case C, "Plan my pathway"

User describes a situation involving a specific programme in free text. The assistant resolves it to that programme, then uses the knowledge graph to find what's connected to it.

```mermaid
flowchart TD
    A[User describes their situation] --> B[Text is converted into an embedding]
    B --> C[Vector database is searched for the closest chunks]
    C --> D[First result that maps to a known programme becomes the entry point]
    D --> E{No match found}
    D --> F[Graph is checked: next tier, same agency, complementary programmes]
    E --> G[Assistant says it couldn't match a specific programme]
    F --> H[Matches are assembled into a labeled context package]
    I[Language model receives the question, the matched programme, and the labeled context] --> J[Model names the programme, explains what's next or what pairs with it, cites sources]
    H --> I
    J --> K[Answer is shown with source links]
```

**Implementation detail:**

- The user's text is embedded and searched the same way as Use Case A, but only the first hit that maps back to an actual programme in the graph is used, since the graph doesn't model page-intro or FAQ chunks.
- If no hit resolves to a known programme, the assistant says so directly rather than guessing, and suggests trying "Chat with idea" instead.
- Once a programme is resolved, the graph supplies: the next funding tier (if tiered), other programmes from the same agency, and programmes that cover resource types the matched one doesn't.
- Each piece of context is labeled with its relationship to the matched programme ("this programme," "next tier," "same agency," "complements this programme") so the model can reason about sequence and combination, not just similarity.
- The context and question are sent to `gpt-4o-mini` under a system prompt instructing it to name the matched programme, explain what's next or what to pair it with using only labeled context that's actually present, and cite every claim.
- If no next tier or complementary programme exists in the context, the prompt requires saying so plainly rather than forcing a recommendation.

---

## Trust and transparency

All three use cases answer only from material retrieved at query time, not general knowledge. If retrieved context lacks a good answer, or a specific programme can't be confidently matched, the assistant says so instead of guessing. Source citations are included so answers can be verified against the original pages.
"""


def render_markdown_with_mermaid(md_text: str):
    """Render a markdown string in the main canvas, drawing any fenced
    ```mermaid blocks as actual diagrams (via mermaid.js in a components.html
    iframe) instead of leaving them as inert code text."""
    parts = re.split(r"```mermaid\n(.*?)```", md_text, flags=re.S)
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if part.strip():
                st.markdown(part, unsafe_allow_html=False)
        else:
            diagram_height = 120 + 40 * part.count("\n")
            components.html(html(f"""
                <div class="mermaid">
                {part}
                </div>
                <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
                <script>mermaid.initialize({{ startOnLoad: true, theme: 'neutral' }});</script>
            """), height=diagram_height, scrolling=True)


# ---------------------------------------------------------------- sidebar ----

with st.sidebar:
    st.markdown(html(f"""
        <div class="commune-title-row">
            {LOGO_SVG}
            <span class="commune-wordmark">Commune</span>
        </div>
    """), unsafe_allow_html=True)

    st.markdown(html("""
        <p style='font-size:0.95rem; font-weight:600; margin-top:0.2rem;'>Find your way
        into Singapore's community-building ecosystem.</p>
    """), unsafe_allow_html=True)

    st.markdown("<div style='margin-top:2rem;'></div>", unsafe_allow_html=True)
    st.markdown(html("""
        <p style='opacity:0.7; font-size:0.78rem;'>
        Sourced from the Singapore Government Partnerships Office ecosystem.
        This assistant only answers from retrieved official content -- always verify
        eligibility and deadlines with the linked source.</p>
    """), unsafe_allow_html=True)

# ---------------------------------------------------------------- helpers ----

def render_card(kind, label, body_html, pin="📌"):
    st.markdown(html(f"""
        <div class="commune-card {kind}">
            <div class="commune-pin">{pin}</div>
            <div class="commune-label">{label}</div>
            <p>{body_html}</p>
        </div>
    """), unsafe_allow_html=True)


def run_query(mode_key, query_label, generate_fn, *args, **kwargs):
    with st.spinner("Pinning together an answer..."):
        try:
            answer, sources = generate_fn(*args, **kwargs)
        except Exception as e:
            answer, sources = f"Something went wrong: {e}", []
    st.session_state.history.append({
        "mode": mode_key,
        "query_label": query_label,
        "answer": answer,
        "sources": sources,
    })


def render_composer():
    """The actual input controls -- lives in the main canvas, not the
    sidebar. Uses a native bordered container (not an HTML div wrapper)
    so Streamlit's widgets actually render inside the visual card."""
    if st.session_state.pop("_clear_composer", False):
        st.session_state["idea_text"] = ""
        st.session_state["resource_types_ms"] = []
        st.session_state["resource_context_text"] = ""
        st.session_state["pathway_text"] = ""

    with st.container(border=True):
        mode = st.radio(
            "How can this assistant help?",
            ["💡 Describe my idea", "🔍 Find by resource need", "🧭 Plan my pathway"],
            horizontal=True,
            label_visibility="collapsed",
            key="composer_mode",
        )

        if mode == "💡 Describe my idea":
            context_text = st.text_area(
                "Tell me about your project or idea",
                placeholder="e.g. I want to run a monthly community gardening session for elderly residents in my estate",
                height=110,
                label_visibility="collapsed",
                key="idea_text",
            )
            selected_types = None
            submitted = st.button("Find my starting point →", use_container_width=True)
        elif mode == "🔍 Find by resource need":
            selected_types = st.multiselect(
                "What kind of support are you looking for?",
                RESOURCE_TYPE_OPTIONS,
                format_func=lambda t: RESOURCE_TYPE_LABELS.get(t, t),
                placeholder="Select resource type(s)",
                label_visibility="collapsed",
                key="resource_types_ms",
            )
            context_text = st.text_area(
                "Optional: tell me more about your project",
                placeholder="Optional: tell me more about your project",
                height=90,
                label_visibility="collapsed",
                key="resource_context_text",
            )
            submitted = st.button("Compare providers →", use_container_width=True)
        else:
            pathway_text = st.text_area(
                "What's your situation?",
                placeholder="e.g. I received Seed funding last year, what's next? or: I'm running "
                            "Lively Places Fund, what else should I pair it with?",
                height=110,
                label_visibility="collapsed",
                key="pathway_text",
            )
            selected_types = None
            submitted = st.button("Plan my pathway →", use_container_width=True)

    if submitted:
        if mode == "💡 Describe my idea":
            if not context_text or not context_text.strip():
                st.warning("Tell me a bit about your idea first.")
            else:
                run_query("job1", context_text.strip(), generate_job1, context_text.strip())
                st.session_state["_clear_composer"] = True
                st.session_state["_scroll_to_bottom"] = True
                st.rerun()
        elif mode == "🔍 Find by resource need":
            if not selected_types:
                st.warning("Pick at least one resource type.")
            else:
                label = "Looking for: " + ", ".join(RESOURCE_TYPE_LABELS.get(t, t) for t in selected_types)
                run_query("job2", label, generate_job2, selected_types, context_text.strip())
                st.session_state["_clear_composer"] = True
                st.session_state["_scroll_to_bottom"] = True
                st.rerun()
        else:
            if not pathway_text or not pathway_text.strip():
                st.warning("Tell me a bit about your situation first.")
            else:
                run_query("job3", pathway_text.strip(), generate_job3, pathway_text.strip())
                st.session_state["_clear_composer"] = True
                st.session_state["_scroll_to_bottom"] = True
                st.rerun()


# ---------------------------------------------------------------- pages ----

def render_main_page():
    if not st.session_state.history:
        st.markdown(html("""
            <div class="commune-hero-wrap">
                <p class="tagline">Describe your idea, tell me what kind of support you're after --
                funding, volunteers, mentorship, space -- or ask what comes next for a programme
                you're already on, and I'll point you to the right doors in the SGPO ecosystem.</p>
            </div>
        """), unsafe_allow_html=True)
        render_composer()
    else:
        _, header_col = st.columns([4, 1.3])
        with header_col:
            if st.button("+ New conversation", key="new_convo_main", use_container_width=True):
                st.session_state.history = []
                st.session_state["_clear_composer"] = True
                st.rerun()

        render_composer()

        st.markdown("<div style='margin-top:2rem;'></div>", unsafe_allow_html=True)

        for entry in st.session_state.history:
            render_card("user", "You asked", safe_text(entry["query_label"]), pin="🖊️")
            render_card("assistant", "Answer", render_markdown_lite(entry["answer"]))

        st.markdown('<div id="commune-chat-bottom"></div>', unsafe_allow_html=True)
        if st.session_state.pop("_scroll_to_bottom", False):
            st.iframe("""
                <script>
                    setTimeout(function () {
                        const doc = window.parent.document;
                        const el = doc.getElementById('commune-chat-bottom');
                        if (el) { el.scrollIntoView({behavior: 'smooth', block: 'start'}); }
                    }, 120);
                </script>
            """, height=1)


def render_about_page():
    st.markdown(ABOUT_US_MD)


def render_methodology_page():
    render_markdown_with_mermaid(METHODOLOGY_MD)


# ---------------------------------------------------------------- navigation ----
# Native multipage navigation (requires Streamlit >= 1.36). Order below is
# also the order shown in the sidebar nav: Main, About Us, Methodology.

pg = st.navigation([
    st.Page(render_main_page, title="Main", default=True),
    st.Page(render_about_page, title="About Us"),
    st.Page(render_methodology_page, title="Methodology"),
])
pg.run()
