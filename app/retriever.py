"""Combined Qdrant retrieval for dataset reviews and crawled web sources."""

from __future__ import annotations

from collections import Counter
from typing import Any

from qdrant_client import QdrantClient

from app.config import settings
from app.embedder import embed_text
from app.logging_config import get_logger, track_call, tracked_operation


MAX_CHUNKS_PER_WEB_PAGE = 2
logger = get_logger(__name__)


def _query_collection(
    client: QdrantClient,
    collection_name: str,
    query_vector: list[float],
    limit: int,
) -> list[Any]:
    """Query one existing collection and return its scored points."""
    with tracked_operation(
        logger,
        "qdrant_collection_query",
        collection=collection_name,
        limit=limit,
    ):
        response = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=limit,
            with_payload=True,
        )
    return list(response.points)


def _normalize_point(point: Any, collection_name: str) -> dict[str, Any]:
    """Convert dataset and web payload variants into one source contract."""
    payload = point.payload or {}
    is_web = (
        collection_name == settings.QDRANT_WEB_COLLECTION
        or payload.get("document_type") == "web"
    )

    return {
        "score": float(point.score),
        "document_type": "web" if is_web else "passenger_review",
        "source_name": (
            payload.get("source_name")
            or ("Web" if is_web else "Airline review dataset")
        ),
        "source_url": payload.get("source_url"),
        "resolved_url": payload.get("resolved_url"),
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
        "review_summary": payload.get("review_summary"),
        "text": payload.get("text"),
        "postgres_id": payload.get("postgres_id"),
        "chunk_index": payload.get("chunk_index"),
        "crawled_at": payload.get("crawled_at"),
    }


def _select_diverse_results(
    candidates: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """Rank globally while preventing one web page from filling all slots."""
    selected: list[dict[str, Any]] = []
    page_counts: Counter[str] = Counter()

    for candidate in sorted(
        candidates,
        key=lambda item: item["score"],
        reverse=True,
    ):
        source_url = candidate.get("source_url")
        if (
            candidate["document_type"] == "web"
            and source_url
            and page_counts[source_url] >= MAX_CHUNKS_PER_WEB_PAGE
        ):
            continue

        selected.append(candidate)
        if source_url:
            page_counts[source_url] += 1

        if len(selected) >= limit:
            break

    return selected


@track_call
def retrieve_reviews(query: str, limit: int = 5) -> list[dict]:
    """Retrieve and merge relevant dataset reviews and crawled web chunks."""
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
        with tracked_operation(
            logger,
            "qdrant_collection_list",
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
        ):
            existing_names = {
                collection.name
                for collection in client.get_collections().collections
            }
    except (ValueError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(
            "Unable to connect to Qdrant. Check that Qdrant is running and "
            "the QDRANT_* settings are correct."
        ) from exc

    collection_names = list(dict.fromkeys([
        settings.QDRANT_COLLECTION,
        settings.QDRANT_WEB_COLLECTION,
    ]))
    candidates: list[dict[str, Any]] = []
    query_errors: list[str] = []

    # Pull extra candidates from each collection before global ranking so one
    # collection cannot exclude the other before their scores are compared.
    per_collection_limit = max(limit * 2, 10)
    for collection_name in collection_names:
        if collection_name not in existing_names:
            continue

        try:
            points = _query_collection(
                client=client,
                collection_name=collection_name,
                query_vector=query_vector,
                limit=per_collection_limit,
            )
        except Exception as exc:
            query_errors.append(f"{collection_name}: {exc}")
            continue

        candidates.extend(
            _normalize_point(point, collection_name)
            for point in points
        )

    if not candidates and query_errors:
        raise RuntimeError(
            "Qdrant search failed for all available collections: "
            + "; ".join(query_errors)
        )

    selected = _select_diverse_results(candidates, limit)
    logger.info(
        "event=retrieval_completed candidate_count=%s result_count=%s "
        "collections=%s",
        len(candidates),
        len(selected),
        ",".join(sorted(existing_names)),
    )
    return selected
