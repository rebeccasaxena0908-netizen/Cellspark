"""
Tier 4 — Retrieval layer.

Builds a vector index over the PubMed corpus so the copilot can ground its
answers in real literature instead of generating from model parameters alone.

HOW RETRIEVAL WORKS (worth explaining in the viva):
Each abstract is converted to an embedding — a vector of 384 numbers that
places the text in a semantic space, where documents about similar ideas land
near each other. A question is embedded the same way, and retrieval is just
finding the nearest vectors.

This is why it beats keyword search: "why did you lower the U content?" shares
almost no words with an abstract titled "Suppression of RNA recognition by
Toll-like receptors", but the two sit close in embedding space because they
are about the same thing.

The index is persisted to disk, so embedding runs once rather than on every
server start.
"""

import json
import os
from functools import lru_cache
from typing import Any, Dict, List

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
CORPUS_PATH = os.path.join(DATA_DIR, "corpus.json")
CHROMA_PATH = os.path.join(DATA_DIR, "chroma")
COLLECTION = "cellspark_literature"
EMBED_MODEL = "all-MiniLM-L6-v2 (ONNX, Chroma default)"


@lru_cache(maxsize=1)
@lru_cache(maxsize=1)
def get_collection():
    """
    Open (or build) the persistent Chroma collection.

    Uses Chroma's bundled ONNX MiniLM-L6-v2 embedder (384 dimensions),
    downloaded once to ~/.cache/chroma. No embedding function is passed on
    reopen: Chroma persists which embedder built the collection and reuses
    it. Supplying a different one raises a conflict error rather than
    silently comparing vectors from two different spaces — which is the right
    behaviour, since that failure would otherwise be invisible.
    """
    import chromadb

    client = chromadb.PersistentClient(path=CHROMA_PATH)

    existing = [c.name for c in client.list_collections()]
    if COLLECTION in existing:
        col = client.get_collection(COLLECTION)
        if col.count() > 0:
            return col
        # empty collection from a failed build — start over
        client.delete_collection(COLLECTION)

    col = client.create_collection(
        name=COLLECTION,
        # cosine similarity is the right metric for text embeddings — it
        # compares direction and ignores document length
        metadata={"hnsw:space": "cosine"},
    )

    with open(CORPUS_PATH) as fh:
        docs = json.load(fh)

    # Index title and abstract together. Titles are dense with keywords and
    # measurably improve retrieval on short questions.
    col.add(
        ids=[d["pmid"] for d in docs],
        documents=[f"{d['title']}\n\n{d['abstract']}" for d in docs],
        metadatas=[{
            "pmid": d["pmid"],
            "title": d["title"],
            "journal": d.get("journal", ""),
            "year": d.get("year", ""),
        } for d in docs],
    )

    return col


def retrieve(query: str, k: int = 4) -> List[Dict[str, Any]]:
    """
    Return the k most semantically similar abstracts.

    Chroma reports cosine DISTANCE (0 = identical), so we convert to a
    similarity score, which reads more naturally in the UI.
    """
    col = get_collection()
    res = col.query(query_texts=[query], n_results=k)

    out = []
    for i in range(len(res["ids"][0])):
        meta = res["metadatas"][0][i]
        out.append({
            "pmid": meta["pmid"],
            "title": meta["title"],
            "journal": meta.get("journal", ""),
            "year": meta.get("year", ""),
            "text": res["documents"][0][i],
            "similarity": round(1 - res["distances"][0][i], 3),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{meta['pmid']}/",
        })
    return out


def corpus_info() -> Dict[str, Any]:
    """Summary for the API, so the UI can report what's indexed."""
    try:
        col = get_collection()
        return {
            "available": True,
            "documents": col.count(),
            "collection": COLLECTION,
            "embedding_model": EMBED_MODEL,
        }
    except Exception as e:
        return {"available": False, "error": str(e)}