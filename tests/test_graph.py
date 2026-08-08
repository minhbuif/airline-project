"""Tests for Neo4j graph records, batching, and analytics."""

import unittest
from unittest.mock import Mock, patch

from app.graph import (
    GRAPH_CONSTRAINTS,
    UPSERT_REVIEWS_CYPHER,
    build_graph_record,
    get_airline_graph_overview,
    upsert_graph_reviews,
)


class FakeRecord(dict):
    """Minimal Neo4j Record stand-in used by graph query tests."""

    def data(self) -> dict:
        return dict(self)


class GraphTests(unittest.TestCase):
    """Verify duplicate-safe graph modeling without a live Neo4j server."""

    def setUp(self) -> None:
        self.review = {
            "review_hash": "a" * 64,
            "source_row_id": "10",
            "airline_name": "Example Air",
            "title": "A useful review",
            "review_text": "The crew was helpful.",
            "review_summary": "The crew was helpful.",
            "country": "Australia",
            "review_date": "2026-07-01",
            "verified": "Yes",
            "traveller_type": "Solo Leisure",
            "seat_type": "Economy",
            "route": "BNE to SIN",
            "date_flown": "2026-06",
            "recommended": "Yes",
            "aircraft": "A350",
            "overall_rating": 8.0,
        }

    def test_builds_scalar_graph_record(self) -> None:
        record = build_graph_record(self.review, postgres_id=42)

        self.assertEqual(record["review_hash"], "a" * 64)
        self.assertEqual(record["postgres_id"], 42)
        self.assertEqual(record["airline_name"], "Example Air")
        self.assertEqual(record["route"], "BNE to SIN")

    def test_rejects_graph_record_without_identity(self) -> None:
        with self.assertRaises(ValueError):
            build_graph_record({**self.review, "review_hash": ""}, 42)

    def test_schema_and_upsert_are_duplicate_safe(self) -> None:
        self.assertTrue(
            any("review_hash IS UNIQUE" in item for item in GRAPH_CONSTRAINTS)
        )
        self.assertIn("UNWIND $reviews", UPSERT_REVIEWS_CYPHER)
        self.assertIn("MERGE (review:Review:DatasetReview", UPSERT_REVIEWS_CYPHER)
        self.assertIn("MERGE (review)-[:ABOUT_AIRLINE]", UPSERT_REVIEWS_CYPHER)

    @patch("app.graph.graph_enabled", return_value=True)
    @patch("app.graph.get_graph_driver")
    def test_upserts_review_batch(
        self,
        get_driver: Mock,
        _graph_enabled: Mock,
    ) -> None:
        driver = get_driver.return_value
        driver.execute_query.return_value = (
            [FakeRecord(processed_count=2)],
            Mock(),
            ["processed_count"],
        )

        count = upsert_graph_reviews([
            build_graph_record(self.review, 1),
            build_graph_record({**self.review, "review_hash": "b" * 64}, 2),
        ])

        self.assertEqual(count, 2)
        parameters = driver.execute_query.call_args.kwargs["parameters_"]
        self.assertEqual(len(parameters["reviews"]), 2)

    @patch("app.graph.graph_enabled", return_value=True)
    @patch("app.graph.get_graph_driver")
    def test_returns_airline_relationship_overview(
        self,
        get_driver: Mock,
        _graph_enabled: Mock,
    ) -> None:
        driver = get_driver.return_value
        driver.execute_query.side_effect = [
            (
                [FakeRecord(
                    airline_name="Example Air",
                    review_count=12,
                    average_rating=7.5,
                    recommended_count=9,
                )],
                Mock(),
                [],
            ),
            *[
                ([FakeRecord(name="Example", review_count=4)], Mock(), [])
                for _ in range(4)
            ],
        ]

        result = get_airline_graph_overview("Example Air")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["review_count"], 12)
        self.assertIn("routes", result)
        self.assertIn("aircraft", result)
        self.assertIn("seat_types", result)
        self.assertIn("traveller_types", result)


if __name__ == "__main__":
    unittest.main()
