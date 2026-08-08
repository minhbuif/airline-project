"""Tests for summary flow through ingestion, retrieval, and RAG context."""

import unittest
from types import SimpleNamespace

from app.config import settings
from app.rag import format_context
from app.retriever import _normalize_point
from app.summarizer import build_review_embedding_text


class SummaryIntegrationTests(unittest.TestCase):
    """Verify that review summaries reach each search pipeline layer."""

    def setUp(self) -> None:
        self.item = {
            "airline_name": "Example Air",
            "title": "Economy experience",
            "country": "Australia",
            "review_date": "2026-07-01",
            "verified": "Yes",
            "traveller_type": "Solo Leisure",
            "seat_type": "Economy",
            "route": "BNE to SIN",
            "date_flown": "2026-06",
            "aircraft": "A350",
            "recommended": "Yes",
            "review_summary": "The crew was helpful but legroom was limited.",
            "review_text": (
                "The crew was helpful but legroom was limited. "
                "The meal and entertainment were satisfactory."
            ),
        }

    def test_embedding_text_places_summary_before_full_review(self) -> None:
        document = build_review_embedding_text(self.item)

        self.assertLess(
            document.index("Review Summary:"),
            document.index("Full Review:"),
        )
        self.assertIn(self.item["review_summary"], document)
        self.assertIn(self.item["review_text"], document)

    def test_short_review_is_not_duplicated_in_embedding_text(self) -> None:
        item = {
            **self.item,
            "review_summary": "A short review.",
            "review_text": "A short review.",
        }

        document = build_review_embedding_text(item)

        self.assertEqual(document.count("A short review."), 1)
        self.assertNotIn("Full Review:", document)

    def test_retrieval_and_rag_context_preserve_summary(self) -> None:
        point = SimpleNamespace(
            score=0.9,
            payload={
                **self.item,
                "text": self.item["review_text"],
            },
        )

        normalized = _normalize_point(
            point,
            settings.QDRANT_COLLECTION,
        )
        context = format_context([normalized])

        self.assertEqual(
            normalized["review_summary"],
            self.item["review_summary"],
        )
        self.assertIn(
            f"Review Summary: {self.item['review_summary']}",
            context,
        )


if __name__ == "__main__":
    unittest.main()
