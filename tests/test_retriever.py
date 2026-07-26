"""Tests for normalizing and diversifying combined retrieval results."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.config import settings
from app.retriever import (
    _normalize_point,
    _select_diverse_results,
    retrieve_reviews,
)


class RetrieverTests(unittest.TestCase):
    """Test retrieval result handling without a live Qdrant server."""

    def test_normalizes_web_payload(self) -> None:
        point = SimpleNamespace(
            score=0.91,
            payload={
                "document_type": "web",
                "source_name": "Tripadvisor",
                "source_url": "https://example.com/review",
                "airline_name": "Example Air",
                "text": "Passenger review text",
            },
        )

        result = _normalize_point(point, settings.QDRANT_WEB_COLLECTION)

        self.assertEqual(result["document_type"], "web")
        self.assertEqual(result["source_name"], "Tripadvisor")

    def test_limits_chunks_from_one_web_page(self) -> None:
        candidates = [
            {
                "score": 1.0 - index / 100,
                "document_type": "web",
                "source_url": "https://example.com/review",
            }
            for index in range(4)
        ]
        candidates.append({
            "score": 0.5,
            "document_type": "passenger_review",
            "source_url": None,
        })

        result = _select_diverse_results(candidates, limit=5)

        web_results = [
            item for item in result if item["document_type"] == "web"
        ]
        self.assertEqual(len(web_results), 2)
        self.assertEqual(len(result), 3)

    @patch("app.retriever.embed_text", return_value=[0.0] * 384)
    @patch("app.retriever.QdrantClient")
    def test_queries_and_merges_both_collections(
        self,
        client_class: Mock,
        _embed_text: Mock,
    ) -> None:
        client = client_class.return_value
        client.get_collections.return_value = SimpleNamespace(
            collections=[
                SimpleNamespace(name=settings.QDRANT_COLLECTION),
                SimpleNamespace(name=settings.QDRANT_WEB_COLLECTION),
            ]
        )

        def query_points(collection_name: str, **_kwargs):
            if collection_name == settings.QDRANT_COLLECTION:
                payload = {
                    "airline_name": "Example Air",
                    "text": "Dataset review",
                }
                score = 0.8
            else:
                payload = {
                    "document_type": "web",
                    "source_name": "Example Reviews",
                    "source_url": "https://example.com/review",
                    "airline_name": "Example Air",
                    "text": "Web review",
                }
                score = 0.9

            return SimpleNamespace(
                points=[SimpleNamespace(score=score, payload=payload)]
            )

        client.query_points.side_effect = query_points

        results = retrieve_reviews("cabin service", limit=5)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["document_type"], "web")
        self.assertEqual(results[1]["document_type"], "passenger_review")


if __name__ == "__main__":
    unittest.main()
