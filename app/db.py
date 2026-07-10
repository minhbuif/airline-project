from sqlalchemy import create_engine, text
from app.config import settings

engine = create_engine(settings.postgres_url)


def test_postgres_connection():
    with engine.begin() as conn:
        result = conn.execute(text("SELECT 1;"))
        print("Postgres connection OK:", result.scalar())


def insert_review(row: dict) -> int:
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

    with engine.begin() as conn:
        result = conn.execute(query, row)
        return result.scalar_one()