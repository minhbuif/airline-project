"""Qdrant retrieval helpers for passenger-review vectors."""

from qdrant_client import QdrantClient

from app.config import settings
from app.embedder import embed_text


def retrieve_reviews(query: str, limit: int = 5) -> list[dict]:
    """Embed a query and return the most similar review payloads."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Search query must be a non-empty string.")

    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValueError("Search limit must be an integer.")

    if limit < 1:
        raise ValueError("Search limit must be at least 1.")

    try:
        client = QdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
        )
        query_vector = embed_text(query)
        response = client.query_points(
            collection_name=settings.QDRANT_COLLECTION,
            query=query_vector,
            limit=limit,
            with_payload=True,
        )
    except (ValueError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(
            "Unable to query Qdrant. Check that Qdrant is running and the "
            "QDRANT_* settings are correct."
        ) from exc

    # Return plain dictionaries so callers are decoupled from Qdrant models.
    results: list[dict] = []

    for point in response.points:
        payload = point.payload or {}

        results.append({
            "score": point.score,
            "airline_name": payload.get("airline_name"),
            "title": payload.get("title"),
            "country": payload.get("country"),
            "review_date": payload.get("review_date"),
            "traveller_type": payload.get("traveller_type"),
            "seat_type": payload.get("seat_type"),
            "route": payload.get("route"),
            "date_flown": payload.get("date_flown"),
            "aircraft": payload.get("aircraft"),
            "recommended": payload.get("recommended"),
            "text": payload.get("text"),
            "postgres_id": payload.get("postgres_id"),
        })

    return results
