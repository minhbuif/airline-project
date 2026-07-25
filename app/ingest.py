"""Ingest a passenger-review CSV/XLSX dataset into Postgres and Qdrant."""

import glob
import os
import uuid

import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from tqdm import tqdm

from app.config import settings
from app.db import insert_review, test_postgres_connection
from app.embedder import VECTOR_SIZE, embed_text


class QdrantUpsertError(RuntimeError):
    """Raised when a vector batch cannot be persisted safely."""


def find_dataset_file() -> str:
    """Return the first supported dataset in the configured landing path."""
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
    """Load a supported spreadsheet and add context to parser failures."""
    suffix = os.path.splitext(file_path)[1].lower()

    try:
        if suffix == ".xlsx":
            return pd.read_excel(file_path)

        if suffix == ".csv":
            return pd.read_csv(file_path)
    except (ImportError, OSError, ValueError) as exc:
        raise RuntimeError(f"Unable to load dataset: {file_path}") from exc

    raise ValueError(f"Unsupported file type: {file_path}")


def clean_text(value) -> str:
    """Normalize nullable spreadsheet cells into single-line text."""
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
    """Return the first populated value among alternate column names."""
    for col in possible_columns:
        if col in row and not pd.isna(row[col]):
            return row[col]
    return default


def normalize_row(row, source_row_id: int) -> dict:
    """Map varying source columns into the database review schema."""
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
    except (TypeError, ValueError):
        # Ratings are optional; invalid source values are stored as NULL.
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
    """Build the text embedded and stored in the Qdrant payload."""
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


def setup_qdrant_collection(client: QdrantClient) -> None:
    """Create the configured vector collection when it does not exist."""
    try:
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
            print(
                "Qdrant collection already exists: "
                f"{settings.QDRANT_COLLECTION}"
            )
    except Exception as exc:
        raise RuntimeError(
            "Unable to inspect or create the Qdrant collection."
        ) from exc


def upsert_points(
    client: QdrantClient,
    points: list[PointStruct],
) -> None:
    """Write one vector batch and retain context if Qdrant rejects it."""
    if not points:
        return

    try:
        client.upsert(
            collection_name=settings.QDRANT_COLLECTION,
            points=points,
            wait=True,
        )
    except Exception as exc:
        raise QdrantUpsertError(
            f"Unable to upsert a batch of {len(points)} Qdrant points."
        ) from exc


def main() -> None:
    """Run the end-to-end passenger-review ingestion pipeline."""
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

    # Batch vector writes to reduce Qdrant network overhead.
    points: list[PointStruct] = []
    inserted_count = 0
    skipped_count = 0
    failed_count = 0

    for idx, row in tqdm(df.iterrows(), total=len(df)):
        try:
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
                upsert_points(qdrant, points)
                points.clear()

        except QdrantUpsertError:
            # Stop rather than continuing to insert Postgres rows while the
            # vector store is unavailable.
            raise
        except Exception as exc:
            failed_count += 1
            print(f"Failed source row {idx}: {exc}")

    if points:
        upsert_points(qdrant, points)
        points.clear()

    print("Ingestion completed.")
    print(f"Inserted rows: {inserted_count}")
    print(f"Skipped rows: {skipped_count}")
    print(f"Failed rows: {failed_count}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Ingestion failed: {exc}") from exc
