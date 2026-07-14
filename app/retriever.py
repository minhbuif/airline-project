from qdrant_client import QdrantClient

from app.config import settings
from app.embedder import embed_text


def retrieve_reviews(query: str, limit: int = 5) -> list[dict]:
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

    results = []

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