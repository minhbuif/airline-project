import os
import glob
import uuid
import pandas as pd
from tqdm import tqdm

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from app.config import settings
from app.db import test_postgres_connection, insert_review
from app.embedder import embed_text, VECTOR_SIZE


def find_dataset_file() -> str:
    patterns = [
        os.path.join(settings.LANDING_PATH, "*.xlsx"),
        os.path.join(settings.LANDING_PATH, "*.csv"),
    ]

    files = []
    for pattern in patterns:
        files.extend(glob.glob(pattern))

    if not files:
        raise FileNotFoundError(
            f"No .xlsx or .csv file found in landing path: {settings.LANDING_PATH}"
        )

    return files[0]


def load_dataset(file_path: str) -> pd.DataFrame:
    if file_path.endswith(".xlsx"):
        return pd.read_excel(file_path)

    if file_path.endswith(".csv"):
        return pd.read_csv(file_path)

    raise ValueError(f"Unsupported file type: {file_path}")


def clean_text(value) -> str:
    if pd.isna(value):
        return ""

    text = str(value)
    text = text.replace("\n", " ")
    text = text.replace("\r", " ")
    text = text.replace("✅ Trip Verified", "")
    text = text.replace("Trip Verified", "")
    text = text.replace("Not Verified", "")
    text = " ".join(text.split())
    return text.strip()


def get_value(row, possible_columns, default=""):
    for col in possible_columns:
        if col in row and not pd.isna(row[col]):
            return row[col]
    return default


def normalize_row(row, source_row_id: int) -> dict:
    airline_name = clean_text(
        get_value(row, ["NAMES", "Airline Name", "airline", "airline_name"])
    )

    title = clean_text(
        get_value(row, ["Title", "title"])
    )

    review_text = clean_text(
        get_value(row, ["Review", "review", "content", "text"])
    )

    country = clean_text(
        get_value(row, ["Country", "country"])
    )

    review_date = clean_text(
        get_value(row, ["Date", "date", "Review Date"])
    )

    verified = clean_text(
        get_value(row, ["Verified", "Trip Verified", "verified"])
    )

    traveller_type = clean_text(
        get_value(row, ["Type Of Traveller", "Traveller Type", "traveller_type"])
    )

    seat_type = clean_text(
        get_value(row, ["Seat Type", "seat_type", "Cabin"])
    )

    route = clean_text(
        get_value(row, ["Route", "route"])
    )

    date_flown = clean_text(
        get_value(row, ["Date Flown", "date_flown"])
    )

    recommended = clean_text(
        get_value(row, ["Recommended", "recommended"])
    )

    aircraft = clean_text(
        get_value(row, ["Aircraft", "aircraft"])
    )

    overall_rating_raw = get_value(
        row,
        ["Overall Rating", "Rating", "overall_rating"],
        default=None
    )

    try:
        overall_rating = float(overall_rating_raw)
    except Exception:
        overall_rating = None

    return {
        "source_row_id": str(source_row_id),
        "airline_name": airline_name,
        "title": title,
        "review_text": review_text,
        "country": country,
        "review_date": review_date,
        "verified": verified,
        "traveller_type": traveller_type,
        "seat_type": seat_type,
        "route": route,
        "date_flown": date_flown,
        "recommended": recommended,
        "aircraft": aircraft,
        "overall_rating": overall_rating,
    }


def build_document_text(item: dict) -> str:
    return f"""
Airline: {item["airline_name"]}
Title: {item["title"]}
Country: {item["country"]}
Review Date: {item["review_date"]}
Verified: {item["verified"]}
Traveller Type: {item["traveller_type"]}
Seat Type: {item["seat_type"]}
Route: {item["route"]}
Date Flown: {item["date_flown"]}
Aircraft: {item["aircraft"]}
Recommended: {item["recommended"]}

Review:
{item["review_text"]}
""".strip()


def setup_qdrant_collection(client: QdrantClient):
    collections = client.get_collections().collections
    existing_names = [collection.name for collection in collections]

    if settings.QDRANT_COLLECTION not in existing_names:
        print(f"Creating Qdrant collection: {settings.QDRANT_COLLECTION}")

        client.create_collection(
            collection_name=settings.QDRANT_COLLECTION,
            vectors_config=VectorParams(
                size=VECTOR_SIZE,
                distance=Distance.COSINE
            ),
        )
    else:
        print(f"Qdrant collection already exists: {settings.QDRANT_COLLECTION}")


def main():
    print("Starting airline review ingestion...")

    test_postgres_connection()

    file_path = find_dataset_file()
    print(f"Dataset file found: {file_path}")

    df = load_dataset(file_path)
    print(f"Loaded rows: {len(df)}")
    print("Columns:", list(df.columns))

    df = df.drop_duplicates()
    print(f"Rows after exact duplicate removal: {len(df)}")

    qdrant = QdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
    )

    setup_qdrant_collection(qdrant)

    points = []
    inserted_count = 0
    skipped_count = 0

    for idx, row in tqdm(df.iterrows(), total=len(df)):
        item = normalize_row(row, source_row_id=idx)

        if not item["review_text"]:
            skipped_count += 1
            continue

        postgres_id = insert_review(item)

        document_text = build_document_text(item)
        vector = embed_text(document_text)

        payload = {
            "postgres_id": postgres_id,
            "source_row_id": item["source_row_id"],
            "airline_name": item["airline_name"],
            "title": item["title"],
            "country": item["country"],
            "review_date": item["review_date"],
            "verified": item["verified"],
            "traveller_type": item["traveller_type"],
            "seat_type": item["seat_type"],
            "route": item["route"],
            "date_flown": item["date_flown"],
            "recommended": item["recommended"],
            "aircraft": item["aircraft"],
            "overall_rating": item["overall_rating"],
            "text": document_text,
        }

        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload=payload,
            )
        )

        inserted_count += 1

        if len(points) >= 100:
            qdrant.upsert(
                collection_name=settings.QDRANT_COLLECTION,
                points=points,
            )
            points = []

    if points:
        qdrant.upsert(
            collection_name=settings.QDRANT_COLLECTION,
            points=points,
        )

    print("Ingestion completed.")
    print(f"Inserted rows: {inserted_count}")
    print(f"Skipped rows: {skipped_count}")


if __name__ == "__main__":
    main()