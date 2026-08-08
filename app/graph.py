"""Optional Neo4j graph persistence and airline relationship analytics."""

from __future__ import annotations

from typing import Any, Mapping

from app.config import settings
from app.logging_config import get_logger, track_call, tracked_operation

try:
    from neo4j import GraphDatabase
except ImportError as exc:
    GraphDatabase = None
    NEO4J_IMPORT_ERROR: ImportError | None = exc
else:
    NEO4J_IMPORT_ERROR = None


logger = get_logger(__name__)
_driver: Any = None


class GraphUpsertError(RuntimeError):
    """Raised when a Neo4j review batch cannot be stored safely."""


GRAPH_CONSTRAINTS = (
    "CREATE CONSTRAINT dataset_review_hash IF NOT EXISTS "
    "FOR (n:DatasetReview) REQUIRE n.review_hash IS UNIQUE",
    "CREATE CONSTRAINT airline_name IF NOT EXISTS "
    "FOR (n:Airline) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT country_name IF NOT EXISTS "
    "FOR (n:Country) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT route_name IF NOT EXISTS "
    "FOR (n:Route) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT aircraft_name IF NOT EXISTS "
    "FOR (n:Aircraft) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT traveller_type_name IF NOT EXISTS "
    "FOR (n:TravellerType) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT seat_type_name IF NOT EXISTS "
    "FOR (n:SeatType) REQUIRE n.name IS UNIQUE",
)

UPSERT_REVIEWS_CYPHER = """
UNWIND $reviews AS row
MERGE (review:Review:DatasetReview {review_hash: row.review_hash})
SET review.source_row_id = row.source_row_id,
    review.postgres_id = row.postgres_id,
    review.title = row.title,
    review.review_text = row.review_text,
    review.review_summary = row.review_summary,
    review.review_date = row.review_date,
    review.date_flown = row.date_flown,
    review.verified = row.verified,
    review.recommended = row.recommended,
    review.overall_rating = row.overall_rating,
    review.updated_at = datetime()

MERGE (airline:Airline {name: row.airline_name})
MERGE (review)-[:ABOUT_AIRLINE]->(airline)

FOREACH (_ IN CASE WHEN row.country = '' THEN [] ELSE [1] END |
    MERGE (country:Country {name: row.country})
    MERGE (review)-[:FROM_COUNTRY]->(country)
)
FOREACH (_ IN CASE WHEN row.route = '' THEN [] ELSE [1] END |
    MERGE (route:Route {name: row.route})
    MERGE (review)-[:FLOWN_ON_ROUTE]->(route)
)
FOREACH (_ IN CASE WHEN row.aircraft = '' THEN [] ELSE [1] END |
    MERGE (aircraft:Aircraft {name: row.aircraft})
    MERGE (review)-[:USED_AIRCRAFT]->(aircraft)
)
FOREACH (_ IN CASE WHEN row.traveller_type = '' THEN [] ELSE [1] END |
    MERGE (traveller:TravellerType {name: row.traveller_type})
    MERGE (review)-[:BY_TRAVELLER_TYPE]->(traveller)
)
FOREACH (_ IN CASE WHEN row.seat_type = '' THEN [] ELSE [1] END |
    MERGE (seat:SeatType {name: row.seat_type})
    MERGE (review)-[:IN_SEAT_TYPE]->(seat)
)
RETURN count(review) AS processed_count
"""

AIRLINE_OVERVIEW_CYPHER = """
MATCH (airline:Airline {name: $airline_name})
OPTIONAL MATCH (review:DatasetReview)-[:ABOUT_AIRLINE]->(airline)
RETURN airline.name AS airline_name,
       count(review) AS review_count,
       avg(review.overall_rating) AS average_rating,
       count(CASE
           WHEN toLower(coalesce(review.recommended, ''))
                IN ['yes', 'true', '1']
           THEN 1
       END) AS recommended_count
"""

TOP_RELATIONSHIP_QUERIES = {
    "routes": """
        MATCH (review:DatasetReview)-[:ABOUT_AIRLINE]->
              (:Airline {name: $airline_name}),
              (review)-[:FLOWN_ON_ROUTE]->(value:Route)
        RETURN value.name AS name, count(review) AS review_count
        ORDER BY review_count DESC, name
        LIMIT 5
    """,
    "aircraft": """
        MATCH (review:DatasetReview)-[:ABOUT_AIRLINE]->
              (:Airline {name: $airline_name}),
              (review)-[:USED_AIRCRAFT]->(value:Aircraft)
        RETURN value.name AS name, count(review) AS review_count
        ORDER BY review_count DESC, name
        LIMIT 5
    """,
    "seat_types": """
        MATCH (review:DatasetReview)-[:ABOUT_AIRLINE]->
              (:Airline {name: $airline_name}),
              (review)-[:IN_SEAT_TYPE]->(value:SeatType)
        RETURN value.name AS name, count(review) AS review_count
        ORDER BY review_count DESC, name
        LIMIT 5
    """,
    "traveller_types": """
        MATCH (review:DatasetReview)-[:ABOUT_AIRLINE]->
              (:Airline {name: $airline_name}),
              (review)-[:BY_TRAVELLER_TYPE]->(value:TravellerType)
        RETURN value.name AS name, count(review) AS review_count
        ORDER BY review_count DESC, name
        LIMIT 5
    """,
}


def graph_enabled() -> bool:
    """Return whether optional Neo4j integration is enabled."""
    return settings.NEO4J_ENABLED


def get_graph_driver() -> Any:
    """Create and cache the configured Neo4j driver."""
    global _driver

    if GraphDatabase is None:
        raise RuntimeError(
            "The Neo4j Python driver is unavailable. Install project "
            "requirements before enabling graph storage."
        ) from NEO4J_IMPORT_ERROR
    if not settings.NEO4J_PASSWORD:
        raise RuntimeError(
            "NEO4J_PASSWORD is missing while NEO4J_ENABLED is true."
        )
    if _driver is None:
        _driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
    return _driver


def close_graph_driver() -> None:
    """Close the cached Neo4j driver when a command-line job finishes."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


@track_call
def test_graph_connection() -> None:
    """Verify Neo4j connectivity when graph integration is enabled."""
    if not graph_enabled():
        return
    try:
        with tracked_operation(
            logger,
            "neo4j_connection_test",
            uri=settings.NEO4J_URI,
            database=settings.NEO4J_DATABASE,
        ):
            get_graph_driver().verify_connectivity()
    except Exception as exc:
        raise RuntimeError(
            "Unable to connect to Neo4j. Check the NEO4J_* settings and "
            "confirm that the Neo4j service is running."
        ) from exc


@track_call
def ensure_graph_schema() -> None:
    """Create index-backed uniqueness constraints for graph identities."""
    if not graph_enabled():
        return
    driver = get_graph_driver()
    try:
        with tracked_operation(logger, "neo4j_schema_setup"):
            for statement in GRAPH_CONSTRAINTS:
                driver.execute_query(
                    statement,
                    database_=settings.NEO4J_DATABASE,
                )
    except Exception as exc:
        raise RuntimeError("Unable to configure the Neo4j graph schema.") from exc


@track_call
def reset_dataset_graph() -> None:
    """Remove the prior dataset snapshot while preserving unrelated graph data."""
    if not graph_enabled():
        return
    driver = get_graph_driver()
    try:
        with tracked_operation(logger, "neo4j_dataset_reset"):
            driver.execute_query(
                "MATCH (review:DatasetReview) DETACH DELETE review",
                database_=settings.NEO4J_DATABASE,
            )
            driver.execute_query(
                """
                MATCH (node)
                WHERE (node:Airline OR node:Country OR node:Route OR
                       node:Aircraft OR node:TravellerType OR node:SeatType)
                  AND NOT (node)--()
                DELETE node
                """,
                database_=settings.NEO4J_DATABASE,
            )
    except Exception as exc:
        raise RuntimeError("Unable to reset the Neo4j dataset graph.") from exc


def build_graph_record(review: Mapping[str, Any], postgres_id: int) -> dict:
    """Convert one normalized review into Neo4j-safe scalar properties."""
    review_hash = str(review.get("review_hash") or "").strip()
    airline_name = str(review.get("airline_name") or "").strip()
    if len(review_hash) != 64:
        raise ValueError("A 64-character review_hash is required for Neo4j")
    if not airline_name:
        raise ValueError("airline_name is required for Neo4j")

    def clean(field: str) -> str:
        return str(review.get(field) or "").strip()

    return {
        "review_hash": review_hash,
        "postgres_id": int(postgres_id),
        "source_row_id": clean("source_row_id"),
        "airline_name": airline_name,
        "title": clean("title"),
        "review_text": clean("review_text"),
        "review_summary": clean("review_summary"),
        "country": clean("country"),
        "review_date": clean("review_date"),
        "verified": clean("verified"),
        "traveller_type": clean("traveller_type"),
        "seat_type": clean("seat_type"),
        "route": clean("route"),
        "date_flown": clean("date_flown"),
        "recommended": clean("recommended"),
        "aircraft": clean("aircraft"),
        "overall_rating": review.get("overall_rating"),
    }


def upsert_graph_reviews(reviews: list[dict[str, Any]]) -> int:
    """Idempotently write one review batch and its graph relationships."""
    if not graph_enabled() or not reviews:
        return 0
    try:
        with tracked_operation(
            logger,
            "neo4j_review_batch_upsert",
            review_count=len(reviews),
        ):
            records, _summary, _keys = get_graph_driver().execute_query(
                UPSERT_REVIEWS_CYPHER,
                parameters_={"reviews": reviews},
                database_=settings.NEO4J_DATABASE,
            )
        return int(records[0]["processed_count"]) if records else 0
    except Exception as exc:
        raise GraphUpsertError(
            f"Unable to upsert {len(reviews)} reviews into Neo4j."
        ) from exc


@track_call
def get_airline_graph_overview(airline_name: str) -> dict[str, Any] | None:
    """Return relationship-based review statistics for one airline."""
    if not graph_enabled():
        raise RuntimeError("Neo4j graph integration is disabled.")
    cleaned_name = airline_name.strip()
    if not cleaned_name:
        raise ValueError("airline_name cannot be empty")

    driver = get_graph_driver()
    try:
        with tracked_operation(
            logger,
            "neo4j_airline_overview_query",
            airline=cleaned_name,
        ):
            records, _summary, _keys = driver.execute_query(
                AIRLINE_OVERVIEW_CYPHER,
                parameters_={"airline_name": cleaned_name},
                database_=settings.NEO4J_DATABASE,
            )
            if not records:
                return None

            overview = records[0].data()
            for result_name, statement in TOP_RELATIONSHIP_QUERIES.items():
                related, _summary, _keys = driver.execute_query(
                    statement,
                    parameters_={"airline_name": cleaned_name},
                    database_=settings.NEO4J_DATABASE,
                )
                overview[result_name] = [record.data() for record in related]
            return overview
    except (ValueError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError("Unable to query the Neo4j airline graph.") from exc
