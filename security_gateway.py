"""ConsentGuard security gateway: search and consent-revalidated extractive summaries.

Run: python security_gateway.py
This is a controlled-session prototype, not an authentication service.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import secrets
from typing import Any

from consentguard_v2 import authorize, connect
from secure_retrieval import secure_search


@dataclass(frozen=True)
class TrustedSession:
    principal_id: str

    def __post_init__(self):
        if not isinstance(self.principal_id, str) or not self.principal_id.strip():
            raise ValueError("Trusted session requires a principal_id")


class SecurityGateway:
    """One instance per trusted session. Never instantiate from LLM arguments."""

    ALLOWED_TOOLS = frozenset({"search_records", "summarize"})
    SEARCH_FIELDS = frozenset({"patient_id", "query", "top_k"})
    SUMMARY_FIELDS = frozenset({"retrieval_id"})
    CACHE_TTL = timedelta(minutes=10)
    MAX_CACHED_SEARCHES = 20

    def __init__(self, session: TrustedSession):
        if not isinstance(session, TrustedSession):
            raise TypeError("A TrustedSession is required")
        self._session = session
        self._session_key = secrets.token_hex(16)
        self._retrievals = {}

    @staticmethod
    def _deny(reason):
        return {"status": "denied", "reason": reason, "results": []}

    def execute(self, tool_name: Any, arguments: Any) -> dict:
        if not isinstance(tool_name, str) or tool_name not in self.ALLOWED_TOOLS:
            return self._deny("Tool not allowed")
        if not isinstance(arguments, dict):
            return self._deny("Arguments must be a JSON object")
        if tool_name == "search_records":
            return self._search(arguments)
        return self._summarize(arguments)

    def _search(self, arguments):
        if set(arguments) - self.SEARCH_FIELDS:
            return self._deny("Unexpected argument")
        if not {"patient_id", "query"}.issubset(arguments):
            return self._deny("Missing required argument")

        patient_id = arguments["patient_id"]
        query = arguments["query"]
        top_k = arguments.get("top_k", 5)
        if (not isinstance(patient_id, str) or not patient_id.strip()
                or len(patient_id) > 128):
            return self._deny("Invalid patient_id")
        if (not isinstance(query, str) or not query.strip()
                or len(query) > 2000):
            return self._deny("Invalid query")
        if type(top_k) is not int or not 1 <= top_k <= 20:
            return self._deny("Invalid top_k")

        try:
            results = secure_search(
                principal_id=self._session.principal_id,
                patient_id=patient_id,
                query=query,
                top_k=top_k,
            )
        except Exception:
            return self._deny("Retrieval unavailable")

        # Retain only validated retrieval output in this session's local memory.
        now = datetime.now(timezone.utc)
        self._purge(now)
        retrieval_id = secrets.token_urlsafe(32)
        self._retrievals[retrieval_id] = {
            "session_key": self._session_key,
            "principal_id": self._session.principal_id,
            "patient_id": patient_id,
            "expires_at": now + self.CACHE_TTL,
            "records": [dict(item) for item in results],
        }
        while len(self._retrievals) > self.MAX_CACHED_SEARCHES:
            self._retrievals.pop(next(iter(self._retrievals)))

        return {
            "status": "ok",
            "tool": "search_records",
            "count": len(results),
            "results": results,
            "retrieval_id": retrieval_id,
        }

    def _purge(self, now):
        for key, entry in list(self._retrievals.items()):
            if entry["expires_at"] <= now:
                del self._retrievals[key]

    def _summarize(self, arguments):
        if set(arguments) != self.SUMMARY_FIELDS:
            return self._deny("summarize requires only retrieval_id")
        retrieval_id = arguments["retrieval_id"]
        if not isinstance(retrieval_id, str) or not retrieval_id.strip():
            return self._deny("Invalid retrieval_id")

        now = datetime.now(timezone.utc)
        self._purge(now)
        entry = self._retrievals.get(retrieval_id)
        if (entry is None or entry["session_key"] != self._session_key
                or entry["principal_id"] != self._session.principal_id):
            return self._deny("Unknown or expired retrieval_id")

        # Reauthorize every record against current consent before disclosing text.
        try:
            db = connect(read_only=True)
            try:
                excerpts = []
                for record in entry["records"]:
                    record_id = record["record_id"]
                    patient_id = record["patient_id"]
                    note = record["note_text"]
                    if patient_id != entry["patient_id"] or not isinstance(note, str):
                        return self._deny("Inconsistent retrieval data")
                    if authorize(
                        db, self._session.principal_id, "read", record_id,
                        datetime.now(timezone.utc).isoformat(),
                    ) != "Permit":
                        return self._deny("Consent no longer permits summarization")
                    excerpts.append({
                        "record_id": record_id,
                        "excerpt": " ".join(note.split())[:240],
                    })
            finally:
                db.close()
        except Exception:
            return self._deny("Summarization unavailable")

        return {
            "status": "ok",
            "tool": "summarize",
            "count": len(excerpts),
            "summary": "No authorized records to summarize." if not excerpts
                       else "Extractive overview of authorized records.",
            "excerpts": excerpts,
        }


if __name__ == "__main__":
    gateway = SecurityGateway(TrustedSession("P01"))
    found = gateway.execute("search_records", {
        "patient_id": "P01", "query": "medication changes", "top_k": 3,
    })
    print("Search:", found["status"], "count:", found.get("count", 0))
    if found["status"] == "ok":
        summary = gateway.execute("summarize", {"retrieval_id": found["retrieval_id"]})
        print("Summarize:", summary["status"], "count:", summary.get("count", 0))
    print("Spoofing:", gateway.execute("search_records", {
        "patient_id": "P01", "query": "medication", "principal_id": "HP0006",
    })["status"])
