"""Postgres connection and review persistence helpers."""

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.logging_config import (
    get_logger,
    track_call,
    track_call_debug,
    tracked_operation,
)

# SQLAlchemy opens the actual database connection lazily on first use.
engine = create_engine(settings.postgres_url)
logger = get_logger(__name__)


@track_call
def test_postgres_connection() -> None:
    """Verify that Postgres is reachable before starting ingestion."""
    try:
        with tracked_operation(
            logger,
            "postgres_connection_test",
            host=settings.POSTGRES_HOST,
            database=settings.POSTGRES_DB,
        ):
            with engine.begin() as conn:
                result = conn.execute(text("SELECT 1;"))
                print("Postgres connection OK:", result.scalar())
    except SQLAlchemyError as exc:
        raise RuntimeError(
            "Unable to connect to Postgres. Check the POSTGRES_* settings."
        ) from exc


@track_call_debug
def insert_review(row: dict) -> int:
    """Insert one normalized review and return its database ID."""
    query = text("""
        INSERT INTO airline_reviews (
            source_row_id,
            airline_name,
            title,
            review_text,
            country,
            review_date,
            verified,
            traveller_type,
            seat_type,
            route,
            date_flown,
            recommended,
            aircraft,
            overall_rating
        )
        VALUES (
            :source_row_id,
            :airline_name,
            :title,
            :review_text,
            :country,
            :review_date,
            :verified,
            :traveller_type,
            :seat_type,
            :route,
            :date_flown,
            :recommended,
            :aircraft,
            :overall_rating
        )
        RETURNING id;
    """)

    try:
        # The transaction is committed on success and rolled back on failure.
        with tracked_operation(
            logger,
            "postgres_review_insert",
            level=10,
            source_row_id=row.get("source_row_id", "unknown"),
            airline=row.get("airline_name", "unknown"),
        ):
            with engine.begin() as conn:
                result = conn.execute(query, row)
                return int(result.scalar_one())
    except SQLAlchemyError as exc:
        source_row_id = row.get("source_row_id", "unknown")
        raise RuntimeError(
            f"Unable to insert review row {source_row_id} into Postgres."
        ) from exc
