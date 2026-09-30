"""Normalize datasets and their provenance before touching any database."""

import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path

import pandas as pd
import yaml


ALIASES = {
    'airline_name': ('airline_name', 'names', 'airline', 'airline name'),
    'title': ('title', 'review_title'),
    'review_text': ('review_text', 'review', 'content', 'text', 'review_content'),
    'country': ('country', 'author_country'),
    'review_date': ('review_date', 'date', 'review date', 'date_review'),
    'verified': ('verified', 'trip verified'),
    'traveller_type': ('traveller_type', 'type of traveller', 'traveller type', 'type_of_traveller'),
    'seat_type': ('seat_type', 'seat type', 'cabin'),
    'route': ('route',), 'date_flown': ('date_flown', 'date flown'),
    'recommended': ('recommended',), 'aircraft': ('aircraft',),
    'overall_rating': ('overall_rating', 'overall rating', 'rating'),
}


def clean(value):
    if value is None or pd.isna(value):
        return ''
    return ' '.join(unicodedata.normalize('NFKC', str(value)).split())


def normalize(row, row_id):
    """Map case-insensitive field aliases; absent dates remain explicitly absent."""
    values = {str(key).strip().casefold(): value for key, value in row.items()}
    item = {}
    for field, aliases in ALIASES.items():
        item[field] = next((clean(values[key]) for key in aliases
                            if key in values and clean(values[key])), '')
    # Strip verification badges only from review prose, never from verification metadata.
    item['review_text'] = re.sub(r'^(?:✅\s*)?(?:Trip Verified|Not Verified)\s*[|:]?\s*', '', item['review_text'])
    try:
        rating = float(item['overall_rating'])
        item['overall_rating'] = rating if math.isfinite(rating) and 0 <= rating <= 10 else None
    except (ValueError, TypeError):
        item['overall_rating'] = None
    item['source_row_id'] = str(row_id)
    return item


def content_key(item):
    """Match identical airline + prose despite differing metadata; not fuzzy similarity."""
    body = clean(item.get('review_text')).casefold()
    airline = clean(item.get('airline_name')).casefold()
    # Very short generic comments need metadata to avoid conflating separate reviews.
    identity = [airline, body]
    if len(body) < 80:
        identity.extend(clean(item.get(k)).casefold() for k in ('title', 'review_date', 'route'))
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


def discover_files(root, explicit=()):
    paths = [Path(p) for p in explicit] if explicit else sorted(
        p for p in Path(root).iterdir() if p.suffix.lower() in {'.csv', '.xlsx'}
        and not p.name.startswith('~$'))
    if not paths:
        raise ValueError('No CSV/XLSX datasets found.')
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in {'.csv', '.xlsx'}:
            raise ValueError(f'Unsupported or missing dataset: {path}')
    return list(dict.fromkeys(p.resolve() for p in paths))


def load_inputs(paths, manifest_path='config/dataset_sources.yaml', limit=None):
    """Validate every input schema/checksum first; keep original source row numbers."""
    manifest = yaml.safe_load(Path(manifest_path).read_text()) if Path(manifest_path).exists() else {}
    sources = (manifest or {}).get('datasets', {})
    frames = []
    for path in paths:
        digest = hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
        metadata = sources.get(path.name, {})
        if metadata.get('sha256') and metadata['sha256'] != digest:
            raise ValueError(f'Checksum mismatch for {path.name}')
        frame = pd.read_excel(path) if path.suffix.lower() == '.xlsx' else pd.read_csv(path)
        cols = {str(col).strip().casefold() for col in frame.columns}
        for required in ('airline_name', 'review_text'):
            if not cols.intersection(ALIASES[required]):
                raise ValueError(f'{path.name}: missing {required} column; columns: {list(frame.columns)}')
        if limit:
            frame = frame.head(limit)
        frame = frame.copy()
        frame['_source_row'] = frame.index.astype(str)
        frame['_source_file'] = path.name
        frame['_file_sha256'] = digest
        for field, default in [('source_name', path.stem), ('source_url', ''),
                               ('license', 'Unspecified'), ('attribution', 'User-supplied dataset')]:
            frame['_' + field] = metadata.get(field, default)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)
