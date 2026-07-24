# Commune — Finding Your Way Through Singapore's Community-Building Support

## What problem does this solve?

Singapore has a wide range of government-backed funding, mentorship, manpower,
and networking support for people who want to run community projects — things
like the Singapore Government Partnerships Office (SGPO) ecosystem, agency
grants, and volunteering programmes. The catch is that this support is spread
across many different agencies and web pages, each with its own eligibility
rules, jargon, and application process.

A community builder — someone who wants to start a gardening group, a youth
mentorship programme, a social enterprise, or a neighbourhood initiative — is
often left asking three very practical questions that are hard to answer just
by browsing government websites:

1. **"I have an idea. Where do I even start?"**
2. **"I know what kind of help I need (money, volunteers, mentors, space) —
   who offers that?"**
3. **"I'm already on a programme. What comes next, and what else should I
   pair it with?"**

**Commune** is an assistant that answers exactly these three questions, using
only information pulled from official SGPO and government sources — never
guessing or inventing details like funding amounts or deadlines.

## What does Commune actually do?

Commune is a simple chat-style web app (built with Streamlit) with three
modes, matching the three questions above:

| Mode | What you type | What you get back |
|---|---|---|
| 💡 **Describe my idea** | A free-text description of your project | The programme(s) that best fit your idea, why they fit, and the concrete next step to apply |
| 🔍 **Find by resource need** | The type(s) of support you need (funding, manpower, mentorship, network, space, etc.) | A side-by-side comparison of the providers/programmes offering that support |
| 🧭 **Plan my pathway** | Your current situation (e.g. "I received Seed funding, what's next?") | The next stage of your programme (if there is one), plus other programmes from the same agency or that complement what you're already doing |

Every answer comes with citations back to the original source, so you can
always verify eligibility criteria, funding amounts, and deadlines yourself
before acting on anything.

## How does it work, in plain terms?

Think of it as a three-step pipeline that only needs to be set up once,
followed by the app itself:

```
 Government PDFs  →  Cleaned & chunked  →  Searchable database  →  Commune app
 (funding pages,     (extract_and_          + relationship map     (what you see
  partnerships,       chunk.py)             (embed_and_store.py     and use)
  volunteering)                              + build_graph.py)
```

1. **Reading the source documents** — `extract_and_chunk.py` reads the raw
   PDFs (funding listings, partnership listings, volunteering listings, and
   informational pages), strips out website clutter (navigation menus,
   cookie notices, copyright lines), and breaks each page into bite-sized,
   labelled pieces of information ("chunks") — for example, one chunk per
   individual fund or programme.

2. **Making it searchable** — `embed_and_store.py` converts each chunk into
   a format a computer can search by *meaning*, not just keyword matching,
   and stores it in a local search database (Chroma). This is what powers
   modes 💡 and 🔍 above.

3. **Mapping how programmes relate to each other** — `build_graph.py` builds
   a small map of how programmes connect: which agency runs which
   programme, what type of support each one provides, and — for staged
   funding like Seed → Sprout → Scale — what the natural next step is. It
   also notices when the same programme appears on two different pages
   (e.g. listed under both "Funding" and "Partnerships") and merges them
   so they aren't treated as two unrelated things. This is what powers
   mode 🧭 above.

4. **The app itself** — `app.py` is what you actually see and click
   through. It presents the three modes, sends your question to the
   relevant logic in `rag_chain.py`, and displays the answer with its
   sources. `rag_chain.py` is the "brain" that decides, for each mode, what
   to search for and how to turn the search results into a clear, honest
   answer — it is instructed never to make up eligibility rules, amounts,
   or deadlines that aren't in the source material.

## Important things to know

- **Commune only knows what's in the source documents it was given.** If a
  programme, deadline, or amount isn't in the underlying PDFs, Commune will
  say so rather than guess.
- **Always double-check eligibility and deadlines against the original
  source link** provided with every answer — programmes and rules can
  change after the source documents were last collected.
- **This is a supporting tool, not an official government service.** It is
  not affiliated with or endorsed by any government agency; it simply
  organizes and summarizes publicly available information to make it
  easier to navigate.

## Project files at a glance

| File | Role |
|---|---|
| `extract_and_chunk.py` | Turns raw PDFs into clean, labelled text chunks |
| `embed_and_store.py` | Makes those chunks searchable by meaning |
| `build_graph.py` | Maps how programmes relate to each other (agency, tier, support type) |
| `rag_chain.py` | The logic that answers each of the three question types |
| `app.py` | The web app you interact with |

## Setup order (for whoever is running this)

These only need to be run once, in order, before the app can be used:

1. `python extract_and_chunk.py`
2. `python embed_and_store.py`
3. `python build_graph.py`
4. `streamlit run app.py`

An `OPENAI_API_KEY` needs to be set up in a `.env` file before steps 2–4 will
work.
