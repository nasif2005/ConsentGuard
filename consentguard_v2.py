"""ConsentGuard v2: metadata-only deterministic authorization and pre-commit validation.

Run: python consentguard_v2.py
The database is opened read-only by the CLI. The caller must supply an identity
from a trusted session; principal_id is not proof of authentication.
"""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).resolve().parent / 'consentguard_v2.db'


def instant(value):
    if not isinstance(value, str) or not value:
        raise ValueError('Timezone-aware timestamp is required')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timestamp must include a timezone')
    return result.astimezone(timezone.utc)


def connect(db_path=DB_PATH, *, read_only=True):
    path = Path(db_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if read_only:
        db = sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)
    else:
        db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def target_records(db, patient_id, target_type, target_id):
    if target_type == 'record':
        query = 'SELECT record_id FROM record_metadata WHERE patient_id=? AND record_id=?'
    elif target_type == 'episode':
        query = 'SELECT record_id FROM record_metadata WHERE patient_id=? AND episode_id=?'
    else:
        raise ValueError('Invalid target type')
    return {row['record_id'] for row in db.execute(query, (patient_id, target_id))}


def validate_directive(db, directive):
    """Pre-commit validation; does not insert or activate a directive.

    Rejects conflicting overlapping active scopes and Deny directives that
    would remove the patient/author read invariants. Draft/inactive directives
    may be validated but are never treated as authorization grants.
    """
    c = directive
    if c['effect'] not in ('Permit', 'Deny') or c['status'] not in ('Active', 'Inactive', 'Draft'):
        raise ValueError('Invalid effect/status')
    start, end = instant(c['valid_from']), instant(c['valid_until'])
    if start >= end:
        raise ValueError('Invalid validity interval')
    if c.get('revoked_at') is not None:
        instant(c['revoked_at'])
    patient = db.execute('SELECT role FROM users WHERE user_id=?', (c['patient_id'],)).fetchone()
    grantee = db.execute('SELECT role FROM users WHERE user_id=?', (c['grantee_id'],)).fetchone()
    if not patient or patient['role'] != 'patient' or not grantee:
        raise ValueError('Unknown patient or grantee')
    targets = target_records(db, c['patient_id'], c['target_type'], c['target_id'])
    if not targets:
        raise ValueError('Target does not exist for patient')
    if c['effect'] == 'Deny':
        if c['grantee_id'] == c['patient_id']:
            raise ValueError('Cannot deny record subject')
        authored = db.execute(
            'SELECT record_id FROM record_metadata WHERE patient_id=? AND author_id=?',
            (c['patient_id'], c['grantee_id'])
        )
        if targets.intersection(row['record_id'] for row in authored):
            raise ValueError('Cannot deny record author')
    # Validate potential conflicts even for draft/inactive proposals before activation.
    others = db.execute('''SELECT * FROM consents
        WHERE patient_id=? AND grantee_id=? AND status='Active' AND effect<>?''',
        (c['patient_id'], c['grantee_id'], c['effect']))
    for other in others:
        # Revocation can shorten the effective interval.
        other_end = instant(other['valid_until'])
        if other['revoked_at'] is not None:
            other_end = min(other_end, instant(other['revoked_at']))
        this_end = min(end, instant(c['revoked_at'])) if c.get('revoked_at') else end
        if start < other_end and instant(other['valid_from']) < this_end:
            if targets & target_records(db, other['patient_id'], other['target_type'], other['target_id']):
                raise ValueError('Conflicting active consent scope')
    return True


def authorize(db, principal_id, action, record_id, evaluation_time):
    """Return Permit/Deny. Principal MUST be obtained from a trusted session."""
    if action != 'read':
        return 'Deny'
    now = instant(evaluation_time)
    principal = db.execute('SELECT role FROM users WHERE user_id=?', (principal_id,)).fetchone()
    record = db.execute('''SELECT patient_id, author_id, episode_id
                           FROM record_metadata WHERE record_id=?''', (record_id,)).fetchone()
    if principal is None or record is None:
        return 'Deny'
    if principal_id == record['patient_id'] and principal['role'] == 'patient':
        return 'Permit'
    if principal_id == record['author_id'] and principal['role'] == 'healthcare_professional':
        return 'Permit'
    if principal['role'] != 'healthcare_professional':
        return 'Deny'
    applicable = []
    rows = db.execute('''SELECT * FROM consents
                         WHERE patient_id=? AND grantee_id=? AND status='Active' ''',
                      (record['patient_id'], principal_id))
    for c in rows:
        if not (instant(c['valid_from']) <= now < instant(c['valid_until'])):
            continue
        if c['revoked_at'] is not None and now >= instant(c['revoked_at']):
            continue
        if ((c['target_type'] == 'record' and c['target_id'] == record_id) or
            (c['target_type'] == 'episode' and c['target_id'] == record['episode_id'])):
            applicable.append(c['effect'])
    if 'Deny' in applicable:
        return 'Deny'
    return 'Permit' if 'Permit' in applicable else 'Deny'


def main():
    with connect() as db:
        for table in ('users', 'consents', 'record_metadata'):
            print(f'{table}: {db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]}')
        time = '2026-10-27T12:00:00Z'
        print('HP0006 read r0001:', authorize(db, 'HP0006', 'read', 'r0001', time))
        print('HP0009 read r0004:', authorize(db, 'HP0009', 'read', 'r0004', time))
        print('P01 read r0001:', authorize(db, 'P01', 'read', 'r0001', time))


if __name__ == '__main__':
    main()
