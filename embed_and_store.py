"""
Embed data/processed/chunks.jsonl using OpenAI embeddings and store them
in a persistent Chroma collection for retrieval.

Requires an OPENAI_API_KEY in a .env file in the project root (see
.env.example -- never commit the real .env, it's covered by .gitignore).

Run from the project root:
    python embed_and_store.py
"""

import json
import os
from pathlib import Path

import chromadb
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()  # reads .env in the current working directory

CHUNKS_JSONL = Path("data/processed/chunks.jsonl")
CHROMA_DIR = "data/processed/chroma_db"
COLLECTION_NAME = "community_rag"
EMBEDDING_MODEL = "text-embedding-3-small"
BATCH_SIZE = 100  # chunks per OpenAI embeddings API call

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError(
        "OPENAI_API_KEY not found. Create a .env file in the project root "
        "containing:\n  OPENAI_API_KEY=sk-...\n"
        "(copy .env.example and fill in your real key)"
    )

client = OpenAI(api_key=api_key)
chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)


def load_chunks():
    records = []
    with open(CHUNKS_JSONL) as f:
        for line in f:
            records.append(json.loads(line))
    return records


def embed_batch(texts):
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def main():
    records = load_chunks()
    print(f"Loaded {len(records)} chunks from {CHUNKS_JSONL}")

    collection = chroma_client.get_or_create_collection(name=COLLECTION_NAME)

    ids, documents, metadatas = [], [], []
    for r in records:
        ids.append(f"chunk_{r['chunk_id']}")
        documents.append(r["text"])
        metadatas.append({
            "provider": r["provider"],
            "page_type": r["page_type"],
            # Chroma metadata values must be scalars, not lists -- store as
            # a comma-separated string and split it back out at query time.
            "resource_types": ",".join(r["resource_types"]),
            "source_file": r["source_file"],
        })

    all_embeddings = []
    for i in range(0, len(documents), BATCH_SIZE):
        batch = documents[i:i + BATCH_SIZE]
        print(f"Embedding chunks {i}-{i + len(batch)} of {len(documents)}...")
        all_embeddings.extend(embed_batch(batch))

    # upsert (not add) so re-running this script after adding more chunks
    # doesn't error out on duplicate IDs -- it just updates them
    collection.upsert(
        ids=ids,
        embeddings=all_embeddings,
        documents=documents,
        metadatas=metadatas,
    )

    print(f"\nDone. {collection.count()} chunks stored in Chroma collection "
          f"'{COLLECTION_NAME}' at {CHROMA_DIR}")


if __name__ == "__main__":
    main()
