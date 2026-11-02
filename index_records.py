
from pathlib import Path
import json
import sqlite3
import chromadb

# ------------------------------------------
# 1. Project paths
# ------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent

SQLITE_PATH = PROJECT_DIR / "consentguard.db"
CHROMA_PATH = PROJECT_DIR / "chroma_storage"

COLLECTION_NAME = "healthcare_records_384"
BATCH_SIZE = 50

# ------------------------------------------
# 2. Read clinical records from SQLite
# ------------------------------------------

if not SQLITE_PATH.exists():
    raise FileNotFoundError(
        f"SQLite database not found: {SQLITE_PATH}"
    )

conn = sqlite3.connect(str(SQLITE_PATH))
conn.row_factory = sqlite3.Row

# Display available tables for debugging
tables = [
    row[0]
    for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
]

print("SQLite tables:", tables)

if "records" not in tables:
    raise RuntimeError("The 'records' table was not found.")

rows = conn.execute("SELECT * FROM records").fetchall()
records = [dict(row) for row in rows]

conn.close()

print("SQLite records found:", len(records))

if len(records) != 500:
    raise RuntimeError(
        f"Expected 500 records, found {len(records)}"
    )

# ------------------------------------------
# 3. Initialize local ChromaDB
# ------------------------------------------

client = chromadb.PersistentClient(
    path=str(CHROMA_PATH)
)

# Default ChromaDB embedding function
collection = client.get_or_create_collection(
    name=COLLECTION_NAME
)

print("ChromaDB collection:", COLLECTION_NAME)

# ------------------------------------------
# 4. Convert SQLite rows into ChromaDB data
# ------------------------------------------

ids = []
documents = []
metadatas = []

for record in records:

    record_id = str(record["record_id"])
    note_text = str(record["note_text"])

    if not note_text.strip():
        raise ValueError(
            f"Empty clinical note: {record_id}"
        )

    labels = record.get("labels", [])

    if isinstance(labels, str):
        try:
            labels = json.loads(labels)
        except json.JSONDecodeError:
            labels = [labels]

    if not isinstance(labels, list):
        labels = [str(labels)]

    metadata = {
        "patient_id": str(record["patient_id"]),
        "episode_id": str(record["episode_id"]),
        "author_id": str(record["author_id"]),
        "recorded_at": str(record["recorded_at"]),
        "labels": json.dumps(labels),
    }

    ids.append(record_id)
    documents.append(note_text)
    metadatas.append(metadata)

# ------------------------------------------
# 5. Insert records in batches
# ------------------------------------------

total = len(ids)

for start in range(0, total, BATCH_SIZE):

    end = min(start + BATCH_SIZE, total)

    collection.upsert(
        ids=ids[start:end],
        documents=documents[start:end],
        metadatas=metadatas[start:end]
    )

    print(f"Indexed {end}/{total}")

# ------------------------------------------
# 6. Verify ChromaDB records
# ------------------------------------------

count = collection.count()

print(
    f"ChromaDB collection '{COLLECTION_NAME}' count:",
    count
)

stored = collection.get(include=[])

sqlite_ids = set(ids)
chroma_ids = set(stored["ids"])

if sqlite_ids != chroma_ids:
    missing = sqlite_ids - chroma_ids
    extra = chroma_ids - sqlite_ids

    raise RuntimeError(
        f"Record ID mismatch. Missing: {missing}, Extra: {extra}"
    )

print(
    "SUCCESS: All 500 SQLite record IDs "
    "are indexed in ChromaDB."
)

print(
    "NOTE: Consent-aware retrieval is "
    "not yet implemented."
)
