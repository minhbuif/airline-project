"""Additive review persistence, source attribution, and import-run bookkeeping."""

import json
from contextlib import contextmanager

from sqlalchemy import text

from app.db import engine
from app.dataset_io import content_key
from app.review_identity import REVIEW_IDENTITY_FIELDS, build_review_hash


def ensure_dataset_schema():
    """Backfill a secondary content identity without deleting existing reviews."""
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE airline_reviews ADD COLUMN IF NOT EXISTS content_key CHAR(64)'))
        conn.execute(text('CREATE INDEX IF NOT EXISTS ix_reviews_content_key ON airline_reviews(content_key)'))
        conn.execute(text('''CREATE TABLE IF NOT EXISTS review_sources (
            review_id INTEGER NOT NULL REFERENCES airline_reviews(id) ON DELETE CASCADE,
            file_sha256 TEXT NOT NULL, source_row_id TEXT NOT NULL, source_file TEXT NOT NULL,
            source_name TEXT NOT NULL, source_url TEXT NOT NULL, license TEXT NOT NULL,
            attribution TEXT NOT NULL, imported_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY(file_sha256, source_row_id))'''))
        conn.execute(text('''CREATE TABLE IF NOT EXISTS dataset_import_runs (
            run_id TEXT PRIMARY KEY, started_at TIMESTAMPTZ DEFAULT now(), finished_at TIMESTAMPTZ,
            status TEXT NOT NULL, mode TEXT NOT NULL, files JSONB NOT NULL,
            metrics JSONB NOT NULL DEFAULT '{}', error_type TEXT)'''))
        rows = conn.execute(text('SELECT * FROM airline_reviews WHERE content_key IS NULL')).mappings().all()
        if rows:
            conn.execute(text('UPDATE airline_reviews SET content_key=:key WHERE id=:id'),
                         [{'id': r['id'], 'key': content_key(r)} for r in rows])


@contextmanager
def import_lock():
    """Prevent two dataset jobs from racing across the three stores."""
    with engine.connect() as conn:
        acquired = conn.execute(text('SELECT pg_try_advisory_lock(73110429)')).scalar()
        conn.commit()
        if not acquired:
            raise RuntimeError('Another dataset import is running; retry when it finishes.')
        try:
            yield
        finally:
            conn.execute(text('SELECT pg_advisory_unlock(73110429)'))
            conn.commit()


def persist_review(item, provenance):
    """Keep canonical IDs and rich existing metadata; attach every source occurrence."""
    key = content_key(item)
    columns = (*REVIEW_IDENTITY_FIELDS, 'review_summary', 'source_row_id', 'review_hash', 'content_key')
    with engine.begin() as conn:
        existing = conn.execute(text('SELECT * FROM airline_reviews WHERE content_key=:key ORDER BY id LIMIT 1'),
                                {'key': key}).mappings().first()
        row = dict(item)
        if existing:
            for field in (*REVIEW_IDENTITY_FIELDS, 'review_summary'):
                if existing.get(field) is not None and str(existing[field]).strip():
                    row[field] = existing[field]
            row['review_hash'] = existing['review_hash'].strip()
        else:
            row['review_hash'] = build_review_hash(row)
        row['content_key'] = key
        params = {field: row.get(field) for field in columns}
        if existing:
            assignments = ', '.join(f'{field}=:{field}' for field in columns)
            review_id = conn.execute(text(f'UPDATE airline_reviews SET {assignments} WHERE id=:id RETURNING id'),
                                     {**params, 'id': existing['id']}).scalar_one()
        else:
            names = ', '.join(columns)
            values = ', '.join(':' + field for field in columns)
            review_id = conn.execute(text(f'INSERT INTO airline_reviews ({names}) VALUES ({values}) RETURNING id'), params).scalar_one()
        conn.execute(text('''INSERT INTO review_sources
            (review_id, file_sha256, source_row_id, source_file, source_name, source_url, license, attribution)
            VALUES (:review_id, :file_sha256, :source_row_id, :source_file, :source_name, :source_url, :license, :attribution)
            ON CONFLICT (file_sha256, source_row_id) DO UPDATE SET
            review_id=EXCLUDED.review_id, source_name=EXCLUDED.source_name,
            source_url=EXCLUDED.source_url, license=EXCLUDED.license, attribution=EXCLUDED.attribution'''),
                     {**provenance, 'review_id': review_id})
        sources = conn.execute(text('''SELECT DISTINCT source_name, source_url, license, attribution
            FROM review_sources WHERE review_id=:id ORDER BY source_name, source_url'''), {'id': review_id}).mappings().all()
    row['sources'] = [dict(source) for source in sources]
    row.update(source_name='; '.join(source['source_name'] for source in sources),
               source_url=next((s['source_url'] for s in sources if s['source_url']), ''))
    return int(review_id), row, bool(existing)


def record_run(run_id, mode, files, metrics=None, status='Started', error_type=None):
    with engine.begin() as conn:
        conn.execute(text('''INSERT INTO dataset_import_runs (run_id, mode, files, status)
            VALUES (:id, :mode, CAST(:files AS jsonb), :status) ON CONFLICT (run_id) DO UPDATE SET
            status=:status, metrics=CAST(:metrics AS jsonb), error_type=:error,
            finished_at=CASE WHEN :status='Started' THEN NULL ELSE now() END'''),
                     {'id': run_id, 'mode': mode, 'files': json.dumps(files), 'status': status,
                      'metrics': json.dumps(metrics or {}), 'error': error_type})
