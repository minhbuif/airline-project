from qdrant_client import QdrantClient

from app.config import settings
from app.embedder import embed_text


def search(query: str, limit: int = 5):
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

    results = response.points

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
    search("What do passengers complain about in economy class?")