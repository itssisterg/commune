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

from rag_chain import generate_job1, generate_job2

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

/* Important Notice expander -- pops as a light card against the black
   sidebar; without this it would inherit the sidebar's off-white text on
   a light background and become unreadable. */
[data-testid="stSidebar"] [data-testid="stExpander"] {
    background-color: #FFFFFF !important;
    border: 1px solid rgba(247, 244, 236, 0.25) !important;
    border-radius: 8px;
}
[data-testid="stSidebar"] [data-testid="stExpander"] * {
    color: var(--ink) !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    font-weight: 700;
    font-size: 0.85rem;
}
[data-testid="stSidebar"] [data-testid="stExpander"] p {
    font-size: 0.82rem;
    line-height: 1.5;
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

/* Chat-style conversation -- right-aligned user bubble, plain
   left-aligned assistant text with a small avatar, no card chrome */
.commune-msg-row {
    display: flex;
    margin: 1.4rem 0;
    align-items: flex-start;
}
.commune-msg-row.user {
    justify-content: flex-end;
}
.commune-msg-row.assistant {
    justify-content: flex-start;
    gap: 0.65rem;
}
.commune-avatar {
    width: 26px;
    height: 26px;
    border-radius: 50%;
    background: #FFFFFF;
    border: 1px solid #E5E0D2;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    margin-top: 0.2rem;
}
.commune-avatar svg {
    width: 15px;
    height: 15px;
}
.commune-bubble {
    max-width: 78%;
}
.commune-msg-row.assistant .commune-bubble {
    max-width: calc(100% - 2.2rem);
}
.commune-msg-row.user .commune-bubble {
    background: #FFFFFF;
    border: 1px solid #E5E0D2;
    border-radius: 18px;
    padding: 0.65rem 1.1rem;
}
.commune-bubble p,
.commune-bubble ul,
.commune-bubble li,
.commune-bubble strong,
.commune-bubble em {
    margin: 0;
    line-height: 1.6;
    color: var(--ink) !important;
}
.commune-bubble p + p,
.commune-bubble p + ul,
.commune-bubble ul + p {
    margin-top: 0.6rem;
}
.commune-bubble ul {
    margin: 0.4rem 0 0 1.1rem;
    padding: 0;
}
.commune-bubble a {
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

    st.markdown("<div style='margin-top:1rem;'></div>", unsafe_allow_html=True)
    with st.expander("⚠️ Important Notice"):
        st.markdown(html("""
            This web application is a **prototype developed for educational purposes
            only**. The information provided here is **not intended for real-world
            usage** and should not be relied upon for making any decisions, especially
            those related to financial, legal, or healthcare matters.

            Furthermore, please be aware that the LLM may generate inaccurate or
            incorrect information. You assume full responsibility for how you use any
            generated output.

            Always consult with qualified professionals for accurate and personalised
            advice.
        """))

# ---------------------------------------------------------------- helpers ----

def render_message(kind, body_html):
    avatar_html = f'<div class="commune-avatar">{LOGO_SVG}</div>' if kind == "assistant" else ""
    st.markdown(html(f"""
        <div class="commune-msg-row {kind}">
            {avatar_html}
            <div class="commune-bubble"><p>{body_html}</p></div>
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

    with st.container(border=True):
        mode = st.radio(
            "How can this assistant help?",
            ["💡 Describe my idea", "🔍 Find by resource need"],
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
        else:
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

    if submitted:
        if mode == "💡 Describe my idea":
            if not context_text or not context_text.strip():
                st.warning("Tell me a bit about your idea first.")
            else:
                run_query("job1", context_text.strip(), generate_job1, context_text.strip())
                st.session_state["_clear_composer"] = True
                st.session_state["_scroll_to_bottom"] = True
                st.rerun()
        else:
            if not selected_types:
                st.warning("Pick at least one resource type.")
            else:
                label = "Looking for: " + ", ".join(RESOURCE_TYPE_LABELS.get(t, t) for t in selected_types)
                run_query("job2", label, generate_job2, selected_types, context_text.strip())
                st.session_state["_clear_composer"] = True
                st.session_state["_scroll_to_bottom"] = True
                st.rerun()


# ---------------------------------------------------------------- canvas ----

if not st.session_state.history:
    st.markdown(html("""
        <div class="commune-hero-wrap">
            <p class="tagline">Describe your idea, or tell me what kind of support you're
            after -- funding, volunteers, mentorship, space -- and I'll point you to the
            right doors in the SGPO ecosystem.</p>
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
        render_message("user", safe_text(entry["query_label"]))
        render_message("assistant", render_markdown_lite(entry["answer"]))

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
