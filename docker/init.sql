CREATE TABLE IF NOT EXISTS airline_reviews (
    id SERIAL PRIMARY KEY,
    source_row_id TEXT,
    airline_name TEXT,
    title TEXT,
    review_text TEXT,
    country TEXT,
    review_date TEXT,
    verified TEXT,
    traveller_type TEXT,
    seat_type TEXT,
    route TEXT,
    date_flown TEXT,
    recommended TEXT,
    aircraft TEXT,
    overall_rating FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);