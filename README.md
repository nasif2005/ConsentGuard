# ConsentGuard

SQLite-only prototype. Uses the two included **synthetic** R500 JSON datasets. No Docker, cloud account, or third-party Python packages required.

## Windows PowerShell

1. Extract this folder to `C:\Users\nasif\Downloads\1st project\consentguard_starter`.
2. Open PowerShell in that folder.
3. Initialize the database:

```powershell
python .\consentguard.py --records .\synthetic_health_records_R500.json --consents .\synthetic_consent_directives_R500.json --db .\consentguard.db
```

4. Run the tests:

```powershell
python -m unittest discover -s tests -v
```

The initializer is intentionally **not** idempotent: running it again against an existing database fails on duplicate record IDs. Delete `consentguard.db` before rebuilding from scratch (not necessary for tests, which use a temporary database).

## Data model and policy semantics

- `users`: patient and healthcare-professional identities. This is an identity directory, **not** an authentication implementation.
- `records`: authoritative record text, patient, author, episode, date, labels.
- `consents`: active consent directives. The six fixture directives are **not imported** into the production database.
- `authorize(db, principal_id, action, record_id, evaluation_time)` returns `Permit` or `Deny` for **read only**.
- Author and subject have immutable read access; everyone else needs a valid active permit. Default deny. Denies are honored; contradictory active policy is rejected at pre-commit validation.
- `validate_directive` checks invalid intervals, missing scope, author/subject denial and overlapping contradictory active directives. It is a limited v1 pre-commit check, not a complete implementation of your CBAC framework.
- Timestamp bounds are `[valid_from, valid_until)`, UTC-aware.
- The `principal_id` must ultimately come from a trusted authenticated session, not from LLM tool arguments. Authentication and ChromaDB are **not yet implemented**.
- A minimal second synthetic patient `P02` is added **only inside an isolated automated test**, not to the main imported dataset.
- These 500 records are synthetic template notes with repetition; not clinical-quality retrieval evaluation data.

## Research Background and Reference

ConsentGuard is motivated by prior research on consent-based access control (CBAC) for healthcare information systems.

The underlying research introduces pre-commit consent validation through a Consent Conflict Analysis Module (CCAM), formalizes baseline access rights for patients and record authors, and proposes controlled emergency access mechanisms.

ConsentGuard explores applying deterministic consent enforcement to LLM-based agents. The LLM selects tools, while an independent Security Gateway evaluates access permissions before clinical records are retrieved or summarized.

The current prototype implements a limited subset of the research framework and does not implement its full emergency-access mechanism.

### Reference

[1] N. Muslim and J.-C. Grégoire, "An Extended Consent-Based Access Control Framework: Pre-Commit Validation and Emergency Access," *arXiv preprint arXiv:2603.07004*, 2026.

**Paper:** https://arxiv.org/abs/2603.07004

**DOI:** https://doi.org/10.48550/arXiv.2603.07004
