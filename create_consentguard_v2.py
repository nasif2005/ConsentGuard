"""Create a metadata-only ConsentGuard SQLite v2 from the existing v1 database.

Run from the consentguard_starter directory:
    python create_consentguard_v2.py

The original consentguard.db is read-only; the new database is created only
if consentguard_v2.db does not already exist.
"""
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'consentguard.db'
DEST = ROOT / 'consentguard_v2.db'

SCHEMA = '''
PRAGMA foreign_keys = ON;
CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    role TEXT NOT NULL CHECK(role IN ('patient', 'healthcare_professional'))
);
CREATE TABLE record_metadata (
    record_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES users(user_id),
    episode_id TEXT NOT NULL,
    author_id TEXT NOT NULL REFERENCES users(user_id),
    recorded_at TEXT NOT NULL,
    labels_json TEXT NOT NULL
);
CREATE TABLE consents (
    consent_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES users(user_id),
    grantee_id TEXT NOT NULL REFERENCES users(user_id),
    target_type TEXT NOT NULL CHECK(target_type IN ('record','episode')),
    target_id TEXT NOT NULL,
    effect TEXT NOT NULL CHECK(effect IN ('Permit','Deny')),
    status TEXT NOT NULL CHECK(status IN ('Active','Inactive','Draft')),
    valid_from TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX idx_record_patient ON record_metadata(patient_id);
CREATE INDEX idx_record_episode ON record_metadata(patient_id,episode_id);
CREATE INDEX idx_consents_lookup ON consents(patient_id,grantee_id,status);
'''


def main():
    if not SOURCE.is_file():
        raise FileNotFoundError(f'Missing source database: {SOURCE}')
    if DEST.exists():
        raise FileExistsError(
            f'{DEST} already exists. Refusing to overwrite it. '
            'Keep it or rename it before running this script again.'
        )

    src = sqlite3.connect(f'{SOURCE.as_uri()}?mode=ro', uri=True)
    src.row_factory = sqlite3.Row
    dst = None
    try:
        required = {'users', 'records', 'consents'}
        tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required.issubset(tables):
            raise RuntimeError(f'Source database is missing tables: {required - tables}')

        dst = sqlite3.connect(str(DEST))
        dst.executescript(SCHEMA)
        with dst:
            dst.executemany(
                'INSERT INTO users (user_id,role) VALUES (?,?)',
                ((r['user_id'], r['role']) for r in src.execute('SELECT user_id,role FROM users'))
            )
            dst.executemany(
                '''INSERT INTO record_metadata
                   (record_id,patient_id,episode_id,author_id,recorded_at,labels_json)
                   VALUES (?,?,?,?,?,?)''',
                ((r['record_id'],r['patient_id'],r['episode_id'],r['author_id'],
                  r['recorded_at'],r['labels_json']) for r in src.execute(
                      'SELECT record_id,patient_id,episode_id,author_id,recorded_at,labels_json FROM records'))
            )
            dst.executemany(
                '''INSERT INTO consents
                   (consent_id,patient_id,grantee_id,target_type,target_id,effect,status,
                    valid_from,valid_until,revoked_at) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (tuple(r) for r in src.execute(
                    'SELECT consent_id,patient_id,grantee_id,target_type,target_id,effect,status,valid_from,valid_until,revoked_at FROM consents'))
            )

            for table, old_table in [('users','users'), ('record_metadata','records'), ('consents','consents')]:
                new_count = dst.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                old_count = src.execute(f'SELECT COUNT(*) FROM {old_table}').fetchone()[0]
                if new_count != old_count:
                    raise RuntimeError(f'Count mismatch for {table}: {new_count} != {old_count}')

            if dst.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('Foreign-key integrity check failed')

        print('Created:', DEST)
        for table in ('users','consents','record_metadata'):
            print(f'{table}:', dst.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])
        print('Clinical note columns in SQLite v2:',
              [r[1] for r in dst.execute('PRAGMA table_info(record_metadata)') if r[1] == 'note_text'])
        print('Original database left unchanged:', SOURCE)
        print('Next: adapt authorize() to query record_metadata instead of records.')
    except Exception:
        if dst is not None:
            dst.close()
            dst = None
        if DEST.exists():
            DEST.unlink()
        raise
    finally:
        src.close()
        if dst is not None:
            dst.close()


if __name__ == '__main__':
    main()
