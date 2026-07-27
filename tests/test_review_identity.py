"""Tests for duplicate-safe dataset review identities."""

import unittest

from app.review_identity import (
    build_review_hash,
    deterministic_review_point_id,
)


class ReviewIdentityTests(unittest.TestCase):
    """Verify that record and vector identities remain stable across runs."""

    def setUp(self) -> None:
        self.review = {
            "source_row_id": "25",
            "airline_name": "Example Air",
            "title": "A comfortable flight",
            "review_text": "The crew was helpful and the seat was clean.",
            "country": "Vietnam",
            "review_date": "2026-01-02",
            "verified": "Yes",
            "traveller_type": "Solo Leisure",
            "seat_type": "Economy",
            "route": "SGN to SIN",
            "date_flown": "2025-12",
            "recommended": "Yes",
            "aircraft": "A321",
            "overall_rating": 8.0,
        }

    def test_hash_is_unchanged_when_source_row_moves(self) -> None:
        original_hash = build_review_hash(self.review)
        reordered_review = {**self.review, "source_row_id": "900"}

        self.assertEqual(
            build_review_hash(reordered_review),
            original_hash,
        )

    def test_hash_changes_when_review_content_changes(self) -> None:
        changed_review = {
            **self.review,
            "review_text": "This is a different passenger experience.",
        }

        self.assertNotEqual(
            build_review_hash(changed_review),
            build_review_hash(self.review),
        )

    def test_qdrant_point_id_is_deterministic(self) -> None:
        review_hash = build_review_hash(self.review)

        self.assertEqual(
            deterministic_review_point_id(review_hash),
            deterministic_review_point_id(review_hash),
        )


if __name__ == "__main__":
    unittest.main()
