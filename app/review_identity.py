"""Stable identities shared by dataset persistence and vector indexing."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Mapping


# Include every normalized review field except source_row_id. A row number can
# change when a spreadsheet is reordered, whereas the review itself remains
# the same record.
REVIEW_IDENTITY_FIELDS = (
    "airline_name",
    "title",
    "review_text",
    "country",
    "review_date",
    "verified",
    "traveller_type",
    "seat_type",
    "route",
    "date_flown",
    "recommended",
    "aircraft",
    "overall_rating",
)


def build_review_hash(review: Mapping[str, Any]) -> str:
    """Return a stable SHA-256 identity for one normalized review."""
    values = [
        "" if review.get(field) is None else str(review.get(field))
        for field in REVIEW_IDENTITY_FIELDS
    ]
    canonical_record = json.dumps(
        values,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_record.encode("utf-8")).hexdigest()


def deterministic_review_point_id(review_hash: str) -> str:
    """Return the same Qdrant UUID every time a review is ingested."""
    if len(review_hash) != 64:
        raise ValueError("review_hash must be a 64-character SHA-256 hash")
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"airline-review:{review_hash}",
        )
    )
