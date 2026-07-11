"""
Retrieval + generation chain for the Community Builder RAG assistant.

Job 1 (pure RAG):      user describes their idea -> retrieve across all
                        providers -> generate a "here's your starting point
                        and why" answer with citations.
Job 2 (filtered RAG):  user selects resource type(s) -> filter to that
                        slice -> retrieve within it -> generate a comparison
                        across providers.
Job 3 (graph RAG):     user describes their situation in free text -> vector
                        search resolves it to a specific programme -> the
                        knowledge graph (build_graph.py) supplies what's
                        connected to that programme (next funding tier, same
                        agency, complementary support) -> generate a "here's
                        your path / here's what to pair this with" answer.

Job 3 needs data/processed/graph.json (run build_graph.py first) -- if
it's missing, Job 3 degrades gracefully with a message rather than
crashing the rest of the module.
"""

import os

import chromadb
from dotenv import load_dotenv
from openai import OpenAI

from build_graph import GRAPH_JSON, get_bundle_candidates, get_next_tier, get_same_agency, load_graph

load_dotenv(override=True)

CHROMA_DIR = "data/processed/chroma_db"
COLLECTION_NAME = "community_rag"
EMBEDDING_MODEL = "text-embedding-3-small"
CHAT_MODEL = "gpt-4o-mini"

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("OPENAI_API_KEY not found. Check your .env file.")

client = OpenAI(api_key=api_key)
chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
collection = chroma_client.get_or_create_collection(name=COLLECTION_NAME)

try:
    graph = load_graph(GRAPH_JSON)
    # Reverse index: which programme node "owns" a given chunk_id. Built
    # once here since the graph doesn't change at runtime.
    _CHUNK_ID_TO_PROGRAMME = {
        cid: node
        for node, data in graph.nodes(data=True)
        if data.get("kind") == "programme"
        for cid in data.get("chunk_ids", [])
    }
except FileNotFoundError:
    graph = None
    _CHUNK_ID_TO_PROGRAMME = {}
    print(f"NOTE: {GRAPH_JSON} not found -- Job 3 (graph RAG) will be "
          f"unavailable until you run build_graph.py.")


def embed_query(text: str):
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=[text])
    return response.data[0].embedding


def _format_results(ids, documents, metadatas, distances):
    formatted = []
    for id_, doc, meta, dist in zip(ids, documents, metadatas, distances):
        formatted.append({
            "id": id_,
            "text": doc,
            "provider": meta.get("provider"),
            "page_type": meta.get("page_type"),
            "resource_types": meta.get("resource_types", ""),
            "source_url": meta.get("source_url") or meta.get("source_file", ""),
            "distance": dist,
        })
    return formatted


# ---------------------------------------------------------------- Job 1 ----

def retrieve_job1(query: str, k: int = 6):
    """Retrieve across all providers and resource types, ranked by
    relevance to the user's described idea."""
    query_embedding = embed_query(query)
    results = collection.query(query_embeddings=[query_embedding], n_results=k)
    return _format_results(
        results["ids"][0], results["documents"][0],
        results["metadatas"][0], results["distances"][0],
    )


JOB1_SYSTEM_PROMPT = """You help community builders in Singapore figure out \
where to start, using the Singapore Government Partnerships Office (SGPO) \
ecosystem.

You will receive the user's description of their project idea, plus \
retrieved context chunks from official sources.

Your job:
1. Identify which provider(s)/programme(s) in the context best fit the idea.
2. Briefly explain why each fits (stage, resource type, eligibility).
3. Give the concrete next step (e.g. "apply via OurSG Grants Portal").
4. Cite every claim using the format [Source: <provider> - <source_url>].

Rules:
- ONLY use information present in the provided context. Never invent \
eligibility criteria, funding amounts, or deadlines not in the context.
- If nothing in the context is a good fit, say so plainly.
- Be concise: a short paragraph or bullet list, not an essay."""


def generate_job1(user_idea: str, k: int = 6):
    retrieved = retrieve_job1(user_idea, k=k)
    context_block = _build_context_block(retrieved)

    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": JOB1_SYSTEM_PROMPT},
            {"role": "user", "content": f"User's idea: {user_idea}\n\nContext:\n{context_block}"},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content, retrieved


# ---------------------------------------------------------------- Job 2 ----

def retrieve_job2(selected_resource_types: list, query: str = "", k: int = 8, over_fetch: int = 50):
    """
    Retrieve only chunks tagged with at least one of the selected resource
    types. Chroma metadata can't store lists, so resource_types is stored
    as a comma-joined string -- filtering happens client-side here rather
    than through Chroma's `where` clause (fine at this corpus size).
    """
    query_text = query.strip() if query.strip() else ", ".join(selected_resource_types)
    query_embedding = embed_query(query_text)

    # Over-fetch first, since we don't know in advance how many of the
    # top matches will actually pass the resource-type filter.
    raw = collection.query(query_embeddings=[query_embedding], n_results=over_fetch)

    ids, docs, metas, dists = [], [], [], []
    for id_, doc, meta, dist in zip(
        raw["ids"][0], raw["documents"][0], raw["metadatas"][0], raw["distances"][0]
    ):
        chunk_types = meta.get("resource_types", "").split(",")
        if any(t in chunk_types for t in selected_resource_types):
            ids.append(id_)
            docs.append(doc)
            metas.append(meta)
            dists.append(dist)
        if len(docs) >= k:
            break

    return _format_results(ids, docs, metas, dists)


JOB2_SYSTEM_PROMPT = """You help community builders in Singapore find the \
right support, using the Singapore Government Partnerships Office (SGPO) \
ecosystem.

The user has selected one or more resource types they need (e.g. funding, \
manpower, mentorship). You will receive retrieved context already filtered \
to those resource type(s).

Your job:
1. Present a short comparison of the providers/programmes available for \
the selected resource type(s) -- what each offers, and key differences \
(amount, eligibility, audience).
2. Cite every claim using the format [Source: <provider> - <source_url>].

Rules:
- ONLY use information present in the provided context.
- If the context is empty or thin, say so plainly rather than inventing \
an answer -- do not pad with generic advice.
- Be concise: a comparison list is better than long prose."""


def generate_job2(selected_resource_types: list, user_context: str = "", k: int = 8):
    retrieved = retrieve_job2(selected_resource_types, query=user_context, k=k)
    context_block = _build_context_block(retrieved)

    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": JOB2_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Selected resource types: {', '.join(selected_resource_types)}\n"
                    f"Additional context from user: {user_context or '(none given)'}\n\n"
                    f"Context:\n{context_block}"
                ),
            },
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content, retrieved


# ---------------------------------------------------------------- Job 3 ----

def _resolve_entry_programme(query: str, k: int = 5):
    """Free-text entry point into the graph: vector search for the query,
    then walk the hits in relevance order and return the first one that's
    actually a node in the graph (i.e. maps back to a specific programme,
    not a page-intro or FAQ chunk, which the graph doesn't model)."""
    query_embedding = embed_query(query)
    results = collection.query(query_embeddings=[query_embedding], n_results=k)

    for id_, dist in zip(results["ids"][0], results["distances"][0]):
        chunk_id = int(id_.replace("chunk_", ""))
        title = _CHUNK_ID_TO_PROGRAMME.get(chunk_id)
        if title:
            return title, dist
    return None, None


def _programme_sources(title: str):
    """Fetch a programme's underlying chunk(s) back out of Chroma, using
    the chunk_ids recorded on its graph node, so the answer can cite the
    same provider/source_url fields Job 1 and Job 2 use."""
    chunk_ids = graph.nodes[title].get("chunk_ids", [])
    if not chunk_ids:
        return []
    got = collection.get(ids=[f"chunk_{cid}" for cid in chunk_ids])
    sources = []
    for doc, meta in zip(got["documents"], got["metadatas"]):
        sources.append({
            "id": title,
            "text": doc,
            "provider": meta.get("provider"),
            "page_type": meta.get("page_type"),
            "resource_types": meta.get("resource_types", ""),
            "source_url": meta.get("source_url") or meta.get("source_file", ""),
            "distance": None,
        })
    return sources


def _related_programmes(entry_title: str, max_related: int = 4):
    """What's connected to the entry programme in the graph: the next
    funding tier (if it's a tiered programme), other programmes from the
    same agency, and programmes that complement it by covering resource
    types it doesn't provide on its own."""
    next_tier = get_next_tier(graph, entry_title)
    same_agency = get_same_agency(graph, entry_title)[:max_related]

    entry_types = {t for _, t, d in graph.out_edges(entry_title, data=True) if d.get("type") == "PROVIDES"}
    all_types = {n for n, d in graph.nodes(data=True) if d.get("kind") == "resource_type"}
    missing_types = all_types - entry_types
    bundle = get_bundle_candidates(graph, entry_title, missing_types)[:max_related] if missing_types else []

    return {"next_tier": next_tier, "same_agency": same_agency, "bundle": bundle}


def retrieve_job3(query: str, k: int = 5):
    """Resolve the query to an entry programme, then gather that
    programme's own chunks plus chunks for whatever the graph says is
    connected to it. Returns (entry_title, retrieved) -- entry_title is
    None if nothing in the query matched a known programme."""
    if graph is None:
        return None, []

    entry_title, _ = _resolve_entry_programme(query, k=k)
    if not entry_title:
        return None, []

    related = _related_programmes(entry_title)
    retrieved = [dict(r, relationship="this programme") for r in _programme_sources(entry_title)]

    if related["next_tier"]:
        retrieved += [dict(r, relationship="next tier")
                      for r in _programme_sources(related["next_tier"])]
    for title in related["same_agency"]:
        retrieved += [dict(r, relationship="same agency")
                      for r in _programme_sources(title)]
    for title in related["bundle"]:
        retrieved += [dict(r, relationship="complements this programme")
                      for r in _programme_sources(title)]

    return entry_title, retrieved


JOB3_SYSTEM_PROMPT = """You help community builders in Singapore plan a \
path through the Singapore Government Partnerships Office (SGPO) \
ecosystem, using how programmes relate to each other -- not just what \
each one offers on its own.

You will receive the user's question, the programme it most closely \
matches, and retrieved context chunks, each labeled with its relationship \
to that programme: "this programme" (its own info), "next tier" (the \
next stage up, if this is a tiered funding programme), "same agency" \
(other programmes run by the same agency), or "complements this \
programme" (programmes covering support types this one doesn't).

Your job:
1. Name the programme the user's question matches.
2. If they're asking what comes next and a "next tier" entry is present, \
name it and explain what changes at that stage.
3. If complementary or same-agency programmes are present and relevant to \
the question, recommend specific ones and explain why they pair well.
4. Cite every claim using the format [Source: <provider> - <source_url>].

Rules:
- ONLY use information present in the provided context. Never invent \
eligibility criteria, funding amounts, or deadlines not in the context.
- If the context has no next tier, or no same-agency/complementary \
programmes, say so plainly rather than forcing a recommendation.
- Be concise: a short paragraph or bullet list, not an essay."""


def generate_job3(user_query: str, k: int = 5):
    if graph is None:
        return ("Graph data isn't available yet -- run build_graph.py first, "
                "then restart the app."), []

    entry_title, retrieved = retrieve_job3(user_query, k=k)
    if not entry_title:
        return ("I couldn't confidently match that to a specific programme "
                "in the ecosystem. Try naming the programme, or use "
                "'Describe my idea' instead."), []

    context_block = _build_context_block(retrieved, include_relationship=True)

    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": JOB3_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"User's question: {user_query}\n"
                    f"Best-matching programme: {entry_title}\n\n"
                    f"Context:\n{context_block}"
                ),
            },
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content, retrieved


# ---------------------------------------------------------------- shared ----

def _build_context_block(retrieved, include_relationship=False):
    if not retrieved:
        return "(No matching context was found.)"
    lines = []
    for i, r in enumerate(retrieved, 1):
        relationship_line = f" | Relationship: {r['relationship']}" if include_relationship else ""
        lines.append(
            f"[{i}] Provider: {r['provider']} | Resource types: {r['resource_types']}{relationship_line}\n"
            f"Source: {r['source_url']}\n"
            f"{r['text']}\n"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    # Quick manual smoke test -- run this file directly to sanity-check
    # both jobs before wiring up the Streamlit UI.
    print("=== Job 1: pure RAG ===")
    answer1, sources1 = generate_job1("I want to start a community gardening project in my neighbourhood")
    print(answer1)
    print("\nSources used:", [s["provider"] for s in sources1])

    print("\n=== Job 2: filtered RAG ===")
    answer2, sources2 = generate_job2(["funding"], "small pilot project for youths")
    print(answer2)
    print("\nSources used:", [s["provider"] for s in sources2])

    print("\n=== Job 3: graph RAG ===")
    answer3, sources3 = generate_job3("I received Seed funding last year, what's next?")
    print(answer3)
    print("\nSources used:", [(s["provider"], s.get("relationship")) for s in sources3])
