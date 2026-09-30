"""Ingest passenger reviews into Postgres, Qdrant, and optional Neo4j."""

import glob
import os
import argparse
from sqlalchemy import text

import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from tqdm import tqdm

from app.config import settings
from app.db import (
    ensure_review_identity_schema,
    insert_review,
    test_postgres_connection,
)
from app.embedder import VECTOR_SIZE, embed_text, get_model
from app.graph import (
    GraphUpsertError,
    build_graph_record,
    close_graph_driver,
    ensure_graph_schema,
    graph_enabled,
    reset_dataset_graph,
    test_graph_connection,
    upsert_graph_reviews,
)
from app.logging_config import (
    get_logger,
    new_request_id,
    set_request_id,
    track_call,
    tracked_operation,
)
from app.review_identity import (
    build_review_hash,
    deterministic_review_point_id,
)
from app.summarizer import build_review_embedding_text, summarize_review
from app.dataset_io import discover_files, load_inputs, normalize
from app.dataset_store import ensure_dataset_schema, import_lock, persist_review, record_run
from app.db import engine


logger = get_logger(__name__)


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

    selected_file = files[0]
    logger.info("event=dataset_file_selected path=%s", selected_file)
    return selected_file


def load_dataset(file_path: str) -> pd.DataFrame:
    """Load a supported spreadsheet and add context to parser failures."""
    suffix = os.path.splitext(file_path)[1].lower()

    try:
        with tracked_operation(
            logger,
            "dataset_file_read",
            path=file_path,
            file_type=suffix,
        ):
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


@track_call
def setup_qdrant_collection(client: QdrantClient, replace: bool = False) -> None:
    """Preserve existing vectors unless replacement was explicitly requested."""
    try:
        with tracked_operation(
            logger,
            "qdrant_collection_setup",
            collection=settings.QDRANT_COLLECTION,
        ):
            collections = client.get_collections().collections
            existing_names = [collection.name for collection in collections]

            if settings.QDRANT_COLLECTION in existing_names:
                if not replace:
                    info = client.get_collection(settings.QDRANT_COLLECTION)
                    vectors = info.config.params.vectors
                    if getattr(vectors, 'size', None) != VECTOR_SIZE:
                        raise ValueError('Existing collection has an incompatible embedding dimension.')
                    return
                print(
                    "Rebuilding Qdrant collection: "
                    f"{settings.QDRANT_COLLECTION}"
                )
                client.delete_collection(
                    collection_name=settings.QDRANT_COLLECTION,
                )

            client.create_collection(
                collection_name=settings.QDRANT_COLLECTION,
                vectors_config=VectorParams(
                    size=VECTOR_SIZE,
                    distance=Distance.COSINE
                ),
            )
            print(f"Qdrant collection ready: {settings.QDRANT_COLLECTION}")
    except Exception as exc:
        raise RuntimeError(
            "Unable to rebuild the Qdrant dataset collection."
        ) from exc


def upsert_points(
    client: QdrantClient,
    points: list[PointStruct],
) -> None:
    """Write one vector batch and retain context if Qdrant rejects it."""
    if not points:
        return

    try:
        with tracked_operation(
            logger,
            "qdrant_points_upsert",
            collection=settings.QDRANT_COLLECTION,
            point_count=len(points),
        ):
            client.upsert(
                collection_name=settings.QDRANT_COLLECTION,
                points=points,
                wait=True,
            )
    except Exception as exc:
        raise QdrantUpsertError(
            f"Unable to upsert a batch of {len(points)} Qdrant points."
        ) from exc


@track_call
def import_rows(df, replace=False) -> dict:
    """Write prevalidated inputs; reruns repair partial writes with stable IDs."""
    print("Starting airline review ingestion...")
    logger.info("event=dataset_ingestion_started")
    print(f"Loaded rows: {len(df)}")

    # Complete dependency and input checks before rebuilding vector storage.
    test_postgres_connection()
    duplicates_removed = ensure_review_identity_schema()
    if duplicates_removed:
        print(
            "Removed legacy duplicate Postgres rows: "
            f"{duplicates_removed}"
        )
    get_model()
    test_graph_connection()
    ensure_graph_schema()

    qdrant = QdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
    )

    setup_qdrant_collection(qdrant, replace=replace)
    if replace:
        reset_dataset_graph()
        with engine.begin() as conn:
            conn.execute(text('DELETE FROM airline_reviews'))

    # Batch vector writes to reduce Qdrant network overhead.
    points: list[PointStruct] = []
    graph_records: list[dict] = []
    upserted_count = 0
    graph_upserted_count = 0
    skipped_count = 0
    duplicate_count = 0
    failed_count = 0
    seen_review_hashes: set[str] = set()

    for idx, row in tqdm(df.iterrows(), total=len(df)):
        try:
            item = normalize(row, row['_source_row'])

            if not item["review_text"] or not item['airline_name']:
                skipped_count += 1
                continue

            item["review_summary"] = summarize_review(item["review_text"])
            provenance = {field: str(row['_' + field]) for field in (
                'source_file', 'file_sha256', 'source_name', 'source_url', 'license', 'attribution')}
            provenance['source_row_id'] = str(row['_source_row'])
            postgres_id, item, matched = persist_review(item, provenance)
            if matched:
                duplicate_count += 1

            document_text = build_review_embedding_text(item)
            vector = embed_text(document_text)

            payload = {
                'source_name': item['source_name'],
                'source_url': item['source_url'],
                'sources': item['sources'],
                "postgres_id": postgres_id,
                "source_row_id": item["source_row_id"],
                "review_hash": item["review_hash"],
                "review_summary": item["review_summary"],
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
                # Store clean evidence separately from the summary-first text
                # used only to produce the embedding vector.
                "text": item["review_text"],
            }

            points.append(
                PointStruct(
                    id=deterministic_review_point_id(
                        item["review_hash"],
                    ),
                    vector=vector,
                    payload=payload,
                )
            )
            if graph_enabled():
                graph_records.append(
                    build_graph_record(item, postgres_id)
                )
            seen_review_hashes.add(item["review_hash"])

            upserted_count += 1

            if len(points) >= 100:
                upsert_points(qdrant, points)
                points.clear()
                graph_upserted_count += upsert_graph_reviews(graph_records)
                graph_records.clear()

        except (QdrantUpsertError, GraphUpsertError):
            # Stop rather than continuing to insert Postgres rows while the
            # vector or graph store is unavailable.
            raise
        except Exception as exc:
            failed_count += 1
            print(f"Failed source row {idx}: {exc}")
            logger.error(
                "event=dataset_row_failed source_row_id=%s error_type=%s",
                idx,
                type(exc).__name__,
            )

    if points:
        upsert_points(qdrant, points)
        points.clear()
    if graph_records:
        graph_upserted_count += upsert_graph_reviews(graph_records)
        graph_records.clear()

    print("Ingestion completed.")
    print(f"Upserted rows: {upserted_count}")
    print(f"Skipped rows: {skipped_count}")
    print(f"Duplicate input rows: {duplicate_count}")
    print(f"Failed rows: {failed_count}")
    if graph_enabled():
        print(f"Neo4j reviews upserted: {graph_upserted_count}")
    logger.info(
        "event=dataset_ingestion_completed upserted_count=%s "
        "skipped_count=%s duplicate_count=%s failed_count=%s "
        "graph_upserted_count=%s",
        upserted_count,
        skipped_count,
        duplicate_count,
        failed_count,
        graph_upserted_count,
    )
    return {'processed': upserted_count, 'skipped': skipped_count,
            'matched_existing': duplicate_count, 'failed': failed_count,
            'graph_upserted': graph_upserted_count}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Import all CSV/XLSX datasets additively by default.')
    parser.add_argument('--file', action='append', default=[], help='Import a specific file; repeat for multiple files.')
    parser.add_argument('--limit', type=int, help='Pilot: maximum rows per file.')
    parser.add_argument('--dry-run', action='store_true', help='Validate files only; no database/API calls.')
    parser.add_argument('--replace', action='store_true', help='Delete and rebuild ALL dataset reviews, graph and vectors from these inputs.')
    parser.add_argument('--confirm-replace', action='store_true', help='Acknowledge removal of previously imported dataset reviews.')
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error('--limit must be positive')
    if args.replace and not args.confirm_replace:
        parser.error('--replace requires --confirm-replace; default ingestion is additive')
    if args.replace and args.limit:
        parser.error('A limited pilot cannot replace the full dataset')
    return args


def main(argv=None):
    args = parse_args(argv)
    paths = discover_files(settings.LANDING_PATH, args.file)
    df = load_inputs(paths, limit=args.limit)
    valid = sum(bool((item := normalize(row, row['_source_row']))['airline_name'] and item['review_text'])
                for _, row in df.iterrows())
    if not valid:
        raise ValueError('No valid airline reviews in selected files; existing stores unchanged.')
    print(f'Validated {len(paths)} files: {len(df)} rows, {valid} valid reviews.')
    if args.dry_run:
        return
    test_postgres_connection()
    with import_lock():
        ensure_review_identity_schema()
        ensure_dataset_schema()
        run_id = new_request_id('ingest')
        set_request_id(run_id)
        files = [p.name for p in paths]
        mode = 'replace' if args.replace else 'add'
        record_run(run_id, mode, files)
        try:
            metrics = import_rows(df, replace=args.replace)
            record_run(run_id, mode, files, metrics,
                       status='Completed with errors' if metrics['failed'] else 'Completed')
            if metrics['failed']:
                raise RuntimeError(f"{metrics['failed']} rows failed; inspect logs and rerun.")
        except Exception as exc:
            record_run(run_id, mode, files, locals().get('metrics', {}), status='Failed', error_type=type(exc).__name__)
            raise
        finally:
            close_graph_driver()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Ingestion failed: {exc}") from exc
