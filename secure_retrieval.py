"""ConsentGuard Stage 1: authorization-scoped semantic retrieval.

Install: python -m pip install chromadb numpy
Run:     python secure_retrieval.py

principal_id must come from a trusted test harness/session, never from LLM output.
This prototype ranks authorized embeddings locally; it does not perform generation.
"""
from datetime import datetime, timezone
from pathlib import Path

import chromadb
import numpy as np
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from consentguard_v2 import authorize, connect

ROOT = Path(__file__).resolve().parent
CHROMA_PATH = ROOT / "chroma_storage"
COLLECTION_NAME = "healthcare_records_384"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def secure_search(principal_id, patient_id, query, top_k=5, evaluation_time=None):
    """Return semantically ranked notes only for records permitted by SQLite.

    evaluation_time is for reproducible tests only; production should use utc_now().
    Identity binding is not implemented: the caller must be trusted.
    """
    if not isinstance(principal_id, str) or not principal_id.strip():
        raise ValueError("A trusted principal_id is required")
    if not isinstance(patient_id, str) or not patient_id.strip():
        raise ValueError("patient_id is required")
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError("query must be 1 to 2000 characters")
    if type(top_k) is not int or not 1 <= top_k <= 20:
        raise ValueError("top_k must be an integer between 1 and 20")

    timestamp = evaluation_time if evaluation_time is not None else utc_now()

    # Authorization occurs before any clinical documents are loaded.
    with_db = connect(read_only=True)
    try:
        rows = with_db.execute(
            "SELECT record_id FROM record_metadata WHERE patient_id=? ORDER BY record_id",
            (patient_id,),
        ).fetchall()
        authorized_ids = [
            row["record_id"] for row in rows
            if authorize(with_db, principal_id, "read", row["record_id"], timestamp) == "Permit"
        ]
    finally:
        with_db.close()

    if not authorized_ids:
        return []

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    # get_collection fails closed if the expected index is absent.
    collection = client.get_collection(name=COLLECTION_NAME)

    # Chroma IDs already equal record IDs, so no metadata migration is needed.
    # Never call an unrestricted collection.query() here.
    subset = collection.get(
        ids=authorized_ids,
        include=["embeddings", "documents", "metadatas"],
    )
    ids = subset["ids"]
    if not ids:
        return []

    embeddings = np.asarray(subset["embeddings"], dtype=np.float64)
    if embeddings.ndim != 2 or len(embeddings) != len(ids):
        raise RuntimeError("Invalid Chroma embedding data")

    # Same embedding model as the existing ChromaDB index.
    embedder = DefaultEmbeddingFunction()
    query_embedding = np.asarray(embedder([query])[0], dtype=np.float64)
    if embeddings.shape[1] != query_embedding.shape[0]:
        raise RuntimeError("Embedding dimension mismatch")

    norms = np.linalg.norm(embeddings, axis=1) * np.linalg.norm(query_embedding)
    similarities = np.divide(
        embeddings @ query_embedding,
        norms,
        out=np.full(len(ids), -1.0),
        where=norms > 0,
    )
    order = np.argsort(-similarities)

    # Reopen SQLite for a fresh authorization check before releasing text.
    # This narrows but does not eliminate races with concurrent revocation.
    db = connect(read_only=True)
    try:
        results = []
        for pos in order:
            idx = int(pos)
            record_id = ids[idx]
            metadata = (subset["metadatas"] or [])[idx]
            if not isinstance(metadata, dict) or metadata.get("patient_id") != patient_id:
                continue  # Fail closed on inconsistent metadata.
            if authorize(db, principal_id, "read", record_id,
                         timestamp if evaluation_time is not None else utc_now()) != "Permit":
                continue
            document = (subset["documents"] or [])[idx]
            if not isinstance(document, str):
                continue
            results.append({
                "record_id": record_id,
                "patient_id": patient_id,
                "similarity": round(float(similarities[idx]), 4),
                "note_text": document,
            })
            if len(results) >= top_k:
                break
        return results
    finally:
        db.close()


if __name__ == "__main__":
    # Fixed time reproduces the consent-policy tests; not a live access decision.
    TEST_TIME = "2026-10-27T12:00:00Z"
    for principal in ("HP0006", "HP0018", "P01"):
        found = secure_search(
            principal_id=principal,
            patient_id="P01",
            query="medication changes",
            top_k=3,
            evaluation_time=TEST_TIME,
        )
        print(f"\n{principal}: {len(found)} authorized results")
        for item in found:
            print(f"  {item['record_id']} | similarity={item['similarity']}")
    # Deliberately do not print clinical notes in the demo.
