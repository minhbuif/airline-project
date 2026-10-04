"""Read-only data coverage and import health for the administrator."""

import pandas as pd


def summarize_coverage(rows, now=None):
    """Calculate coverage from stored metadata, never invent missing dates."""
    frame = pd.DataFrame(rows)
    if frame.empty:
        return []
    today = pd.Timestamp(now or pd.Timestamp.now(tz='UTC'))
    if today.tzinfo is None:
        today = today.tz_localize('UTC')
    dates = pd.to_datetime(frame['review_date'], format='mixed', errors='coerce', utc=True)
    frame['date'] = dates.where(dates <= today)
    frame['recent'] = frame['date'].ge(today - pd.Timedelta(days=365))
    result = []
    for airline, group in frame.groupby('airline_name', dropna=False):
        dated = group['date'].dropna()
        item = {'Airline': airline or 'Unknown', 'Reviews': len(group),
                'Recent reviews (365 days)': int(group['recent'].sum()),
                'Oldest review': dated.min().date().isoformat() if not dated.empty else 'Unknown',
                'Newest review': dated.max().date().isoformat() if not dated.empty else 'Unknown',
                'Missing/invalid review dates': int(group['date'].isna().sum())}
        for field, label in [('date_flown', 'Missing travel dates'), ('seat_type', 'Missing cabin'), ('route', 'Missing route')]:
            item[label] = int(group[field].fillna('').astype(str).str.strip().eq('').sum())
        result.append(item)
    return sorted(result, key=lambda row: (row['Recent reviews (365 days)'], row['Reviews'], row['Airline']))


def load_coverage():
    """One bounded DB snapshot; no schema changes and no paid API calls."""
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError
    from app.db import engine

    try:
        with engine.connect() as conn:
            conn.execute(text('SET TRANSACTION READ ONLY'))
            conn.execute(text("SET LOCAL statement_timeout = '8000ms'"))
            rows = conn.execute(text('''SELECT airline_name, review_date, date_flown, seat_type, route
                FROM airline_reviews''')).mappings().all()
            sources, runs = [], []
            if conn.execute(text("SELECT to_regclass('public.review_sources')")).scalar():
                sources = [dict(row) for row in conn.execute(text('''SELECT source_name, source_file, source_url,
                    license, attribution, count(DISTINCT review_id) AS unique_reviews,
                    count(*) AS source_rows, max(imported_at) AS last_import
                    FROM review_sources GROUP BY source_name, source_file, source_url, license, attribution
                    ORDER BY unique_reviews DESC''')).mappings()]
                runs = [dict(row) for row in conn.execute(text('''SELECT * FROM dataset_import_runs
                    ORDER BY started_at DESC LIMIT 30''')).mappings()]
                duplicates = conn.execute(text('''SELECT count(*) - count(DISTINCT content_key)
                    FROM airline_reviews WHERE content_key IS NOT NULL''')).scalar()
                attributed = conn.execute(text('SELECT count(DISTINCT review_id) FROM review_sources')).scalar()
            else:
                duplicates, attributed = None, 0
        return {'airlines': summarize_coverage(rows), 'sources': sources, 'runs': runs,
                'reviews': len(rows), 'unattributed': len(rows) - attributed,
                'legacy_duplicate_candidates': duplicates}
    except SQLAlchemyError as exc:
        raise RuntimeError('Coverage unavailable. Start Postgres and run dataset ingestion to initialize its tables.') from exc
