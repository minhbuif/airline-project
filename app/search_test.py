"""Small command-line smoke test for Qdrant review search."""

from qdrant_client import QdrantClient

from app.config import settings
from app.embedder import embed_text


def search(query: str, limit: int = 5) -> None:
    """Print the nearest review results for a query."""
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
    except Exception as exc:
        raise RuntimeError(
            "Search failed. Check the embedding model and Qdrant connection."
        ) from exc

    results = response.points

    # Print a compact diagnostic view rather than exposing Qdrant objects.
    for i, result in enumerate(results, start=1):
        payload = result.payload or {}

        print("=" * 80)
        print(f"Result {i}")
        print(f"Score: {result.score}")
        print(f"Airline: {payload.get('airline_name')}")
        print(f"Title: {payload.get('title')}")
        print(f"Seat Type: {payload.get('seat_type')}")
        print(f"Route: {payload.get('route')}")
        print(f"Recommended: {payload.get('recommended')}")
        print()
        print(payload.get("text", "")[:1000])


if __name__ == "__main__":
    try:
        search("What do passengers complain about in economy class?")
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(f"Search test failed: {exc}") from exc
