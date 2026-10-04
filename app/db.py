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
from app.review_identity import build_review_hash

# SQLAlchemy opens the actual database connection lazily on first use.
engine = create_engine(settings.postgres_url, connect_args={'connect_timeout': 5})
logger = get_logger(__name__)


REVIEW_IDENTITY_COLUMNS = text("""
    SELECT
        id,
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
    FROM airline_reviews
    ORDER BY id;
""")


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


@track_call
def ensure_review_identity_schema() -> int:
    """Add review hashes/summaries and remove legacy Postgres duplicates.

    Returns the number of duplicate rows removed during a one-time migration.
    Fresh databases already have the unique review_hash constraint and return
    immediately without scanning the review table.
    """
    try:
        with tracked_operation(logger, "postgres_review_identity_setup"):
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE airline_reviews "
                    "ADD COLUMN IF NOT EXISTS review_hash CHAR(64);"
                ))
                conn.execute(text(
                    "ALTER TABLE airline_reviews "
                    "ADD COLUMN IF NOT EXISTS review_summary TEXT;"
                ))
                existing_index = conn.execute(text(
                    "SELECT to_regclass("
                    "'public.uq_airline_reviews_review_hash'"
                    ");"
                )).scalar_one_or_none()

                if existing_index:
                    return 0

                rows = conn.execute(REVIEW_IDENTITY_COLUMNS).mappings().all()
                keepers: dict[str, int] = {}
                updates: list[dict[str, object]] = []
                duplicate_ids: list[int] = []

                for row in rows:
                    review_hash = build_review_hash(row)
                    row_id = int(row["id"])

                    if review_hash in keepers:
                        duplicate_ids.append(row_id)
                    else:
                        keepers[review_hash] = row_id
                        updates.append({
                            "row_id": row_id,
                            "review_hash": review_hash,
                        })

                if duplicate_ids:
                    conn.execute(
                        text(
                            "DELETE FROM airline_reviews "
                            "WHERE id = ANY(:duplicate_ids);"
                        ),
                        {"duplicate_ids": duplicate_ids},
                    )

                if updates:
                    conn.execute(
                        text(
                            "UPDATE airline_reviews "
                            "SET review_hash = :review_hash "
                            "WHERE id = :row_id;"
                        ),
                        updates,
                    )

                conn.execute(text(
                    "ALTER TABLE airline_reviews "
                    "ALTER COLUMN review_hash SET NOT NULL;"
                ))
                conn.execute(text(
                    "CREATE UNIQUE INDEX "
                    "uq_airline_reviews_review_hash "
                    "ON airline_reviews (review_hash);"
                ))

                logger.info(
                    "event=postgres_legacy_duplicates_removed count=%s",
                    len(duplicate_ids),
                )
                return len(duplicate_ids)
    except SQLAlchemyError as exc:
        raise RuntimeError(
            "Unable to configure duplicate-safe review storage."
        ) from exc


@track_call_debug
def insert_review(row: dict) -> int:
    """Insert or update one normalized review and return its database ID."""
    query = text("""
        INSERT INTO airline_reviews (
            source_row_id,
            review_hash,
            review_summary,
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
            :review_hash,
            :review_summary,
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
        ON CONFLICT (review_hash)
        DO UPDATE SET
            source_row_id = EXCLUDED.source_row_id,
            review_summary = EXCLUDED.review_summary,
            airline_name = EXCLUDED.airline_name,
            title = EXCLUDED.title,
            review_text = EXCLUDED.review_text,
            country = EXCLUDED.country,
            review_date = EXCLUDED.review_date,
            verified = EXCLUDED.verified,
            traveller_type = EXCLUDED.traveller_type,
            seat_type = EXCLUDED.seat_type,
            route = EXCLUDED.route,
            date_flown = EXCLUDED.date_flown,
            recommended = EXCLUDED.recommended,
            aircraft = EXCLUDED.aircraft,
            overall_rating = EXCLUDED.overall_rating
        RETURNING id;
    """)

    row_with_hash = {
        **row,
        "review_hash": row.get("review_hash") or build_review_hash(row),
        "review_summary": row.get("review_summary") or "",
    }

    try:
        # The transaction is committed on success and rolled back on failure.
        with tracked_operation(
            logger,
            "postgres_review_upsert",
            level=10,
            source_row_id=row.get("source_row_id", "unknown"),
            airline=row.get("airline_name", "unknown"),
        ):
            with engine.begin() as conn:
                result = conn.execute(query, row_with_hash)
                return int(result.scalar_one())
    except SQLAlchemyError as exc:
        source_row_id = row.get("source_row_id", "unknown")
        raise RuntimeError(
            f"Unable to upsert review row {source_row_id} into Postgres."
        ) from exc
