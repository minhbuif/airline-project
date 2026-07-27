"""Command-line smoke test for combined dataset and web retrieval."""

from app.logging_config import (
    get_logger,
    new_request_id,
    set_request_id,
    track_call,
)
from app.retriever import retrieve_reviews


logger = get_logger(__name__)


@track_call
def search(query: str, limit: int = 5) -> None:
    """Print the highest-ranked sources returned by the application retriever."""
    set_request_id(new_request_id("search"))
    logger.info("event=search_test_started result_limit=%s", limit)
    results = retrieve_reviews(query=query, limit=limit)

    if not results:
        print("No matching indexed sources were found.")
        return

    for index, result in enumerate(results, start=1):
        print("=" * 80)
        print(f"Result {index}")
        print(f"Score: {result.get('score')}")
        print(f"Type: {result.get('document_type')}")
        print(f"Source: {result.get('source_name')}")
        print(f"URL: {result.get('source_url') or 'Not available'}")
        print(f"Airline: {result.get('airline_name')}")
        print(f"Title: {result.get('title')}")
        print(f"Seat Type: {result.get('seat_type')}")
        print(f"Route: {result.get('route')}")
        print(f"Recommended: {result.get('recommended')}")
        print()
        print(str(result.get("text") or "")[:1000])

    logger.info("event=search_test_completed result_count=%s", len(results))


if __name__ == "__main__":
    try:
        search("What do passengers complain about in economy class?")
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(f"Search test failed: {exc}") from exc
