"""
Ingest Firecrawl output into Postgres and Qdrant.

Expected input:
    landing/web/crawled_pages.jsonl

Each JSONL record should contain:
    airline_name
    source_name
    source_url
    resolved_url
    title
    markdown
    content_hash
    crawled_at

Run:
    python -m app.ingest_web

Optional:
    python -m app.ingest_web --limit 10
    python -m app.ingest_web --input landing/web/crawled_pages.jsonl
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from tqdm import tqdm

from app.config import settings
from app.db import engine
from app.embedder import VECTOR_SIZE, embed_text
from app.logging_config import (
    get_logger,
    new_request_id,
    set_request_id,
    track_call,
    tracked_operation,
)


DEFAULT_INPUT_PATH = Path("landing/web/crawled_pages.jsonl")
DEFAULT_COLLECTION = settings.QDRANT_WEB_COLLECTION

CHUNK_SIZE = 2_500
CHUNK_OVERLAP = 300
QDRANT_BATCH_SIZE = 64
logger = get_logger(__name__)


class QdrantUpsertError(RuntimeError):
    """Raised when a vector batch cannot be persisted safely."""


CREATE_TABLE_SQL = text(
    """
    CREATE TABLE IF NOT EXISTS public.web_documents (
        id BIGSERIAL PRIMARY KEY,
        airline_name TEXT NOT NULL,
        source_name TEXT NOT NULL,
        source_url TEXT NOT NULL,
        resolved_url TEXT,
        title TEXT,
        content_markdown TEXT NOT NULL,
        content_hash CHAR(64) NOT NULL,
        crawled_at TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_web_documents_source_content
            UNIQUE (source_url, content_hash)
    );
    """
)

CREATE_INDEXES_SQL = [
    text(
        """
        CREATE INDEX IF NOT EXISTS idx_web_documents_airline
        ON public.web_documents (airline_name);
        """
    ),
    text(
        """
        CREATE INDEX IF NOT EXISTS idx_web_documents_source
        ON public.web_documents (source_name);
        """
    ),
    text(
        """
        CREATE INDEX IF NOT EXISTS idx_web_documents_crawled_at
        ON public.web_documents (crawled_at);
        """
    ),
]

UPSERT_DOCUMENT_SQL = text(
    """
    INSERT INTO public.web_documents (
        airline_name,
        source_name,
        source_url,
        resolved_url,
        title,
        content_markdown,
        content_hash,
        crawled_at
    )
    VALUES (
        :airline_name,
        :source_name,
        :source_url,
        :resolved_url,
        :title,
        :content_markdown,
        :content_hash,
        :crawled_at
    )
    ON CONFLICT (source_url, content_hash)
    DO UPDATE SET
        airline_name = EXCLUDED.airline_name,
        source_name = EXCLUDED.source_name,
        resolved_url = EXCLUDED.resolved_url,
        title = EXCLUDED.title,
        content_markdown = EXCLUDED.content_markdown,
        crawled_at = EXCLUDED.crawled_at
    RETURNING id;
    """
)

DELETE_WEB_DOCUMENTS_SQL = text(
    "DELETE FROM public.web_documents;"
)


def parse_args() -> argparse.Namespace:
    """Parse and validate command-line ingestion options."""
    parser = argparse.ArgumentParser(
        description="Ingest crawled airline web pages into Postgres and Qdrant."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"JSONL input path. Default: {DEFAULT_INPUT_PATH}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N valid records for testing.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help=(
            "Delete existing web documents and recreate the web Qdrant "
            "collection before ingestion."
        ),
    )
    args = parser.parse_args()

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")

    return args


def clean_string(value: Any) -> str:
    """Normalize nullable JSON values into trimmed strings."""
    if value is None:
        return ""
    return str(value).strip()


def parse_timestamp(value: Any) -> datetime:
    """Parse an ISO timestamp and ensure it is timezone-aware."""
    raw = clean_string(value)

    if not raw:
        return datetime.now(timezone.utc)

    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"

    parsed = datetime.fromisoformat(raw)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed


def validate_record(record: dict[str, Any], line_number: int) -> dict[str, Any]:
    """Validate and normalize one crawled JSONL record."""
    if not isinstance(record, dict):
        raise TypeError(f"Line {line_number}: record must be a JSON object")

    normalized = {
        "airline_name": clean_string(record.get("airline_name")),
        "source_name": clean_string(record.get("source_name")),
        "source_type": clean_string(
            record.get("source_type") or "passenger_reviews"
        ),
        "source_root_url": clean_string(record.get("source_root_url")),
        "source_url": clean_string(record.get("source_url")),
        "resolved_url": clean_string(record.get("resolved_url")),
        "title": clean_string(record.get("title")),
        "content_markdown": clean_string(
            record.get("markdown") or record.get("content_markdown")
        ),
        "content_hash": clean_string(record.get("content_hash")),
        "crawled_at": parse_timestamp(record.get("crawled_at")),
    }

    required_fields = {
        "airline_name": normalized["airline_name"],
        "source_name": normalized["source_name"],
        "source_url": normalized["source_url"],
        "content_markdown": normalized["content_markdown"],
        "content_hash": normalized["content_hash"],
    }

    missing = [name for name, value in required_fields.items() if not value]

    if missing:
        raise ValueError(
            f"Line {line_number}: missing required fields: {', '.join(missing)}"
        )

    if len(normalized["content_hash"]) != 64:
        raise ValueError(
            f"Line {line_number}: content_hash must be a 64-character SHA-256 hash."
        )

    if not normalized["resolved_url"]:
        normalized["resolved_url"] = normalized["source_url"]

    return normalized


def read_jsonl(
    input_path: Path,
    limit: int | None = None,
) -> Iterable[dict[str, Any]]:
    """Yield valid JSONL records while reporting and skipping bad lines."""
    if not input_path.exists():
        raise FileNotFoundError(
            f"Input file not found: {input_path}\n"
            "Run the Firecrawl collection script first."
        )

    valid_count = 0

    try:
        file = input_path.open("r", encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Unable to open input file: {input_path}") from exc

    with tracked_operation(
        logger,
        "web_jsonl_read",
        path=input_path,
        limit=limit,
    ):
        with file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue

                try:
                    raw_record = json.loads(line)
                    record = validate_record(raw_record, line_number)
                except (json.JSONDecodeError, ValueError, TypeError) as exc:
                    print(f"Skipping invalid line {line_number}: {exc}")
                    logger.warning(
                        "event=web_jsonl_line_skipped path=%s line_number=%s "
                        "error_type=%s",
                        input_path,
                        line_number,
                        type(exc).__name__,
                    )
                    continue

                yield record
                valid_count += 1

                if limit is not None and valid_count >= limit:
                    break


@track_call
def create_schema() -> None:
    """Create the Postgres table and supporting indexes."""
    try:
        with tracked_operation(logger, "postgres_web_schema_setup"):
            with engine.begin() as connection:
                connection.execute(CREATE_TABLE_SQL)
                for statement in CREATE_INDEXES_SQL:
                    connection.execute(statement)
    except SQLAlchemyError as exc:
        raise RuntimeError(
            "Unable to create the web_documents Postgres schema."
        ) from exc

    print("Postgres table ready: public.web_documents")


def upsert_document(record: dict[str, Any]) -> int:
    """Insert or update one source document and return its Postgres ID."""
    try:
        with tracked_operation(
            logger,
            "postgres_web_document_upsert",
            level=10,
            source_url=record.get("source_url", "unknown"),
        ):
            with engine.begin() as connection:
                result = connection.execute(UPSERT_DOCUMENT_SQL, record)
                return int(result.scalar_one())
    except SQLAlchemyError as exc:
        raise RuntimeError(
            f"Unable to upsert web document: {record.get('source_url')}"
        ) from exc


def chunk_text(
    value: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """Split text into overlapping chunks while guaranteeing forward progress."""
    text_value = " ".join(value.replace("\r", "\n").split()).strip()

    if not text_value:
        return []

    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1")

    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and smaller than chunk_size")

    chunks: list[str] = []
    start = 0
    text_length = len(text_value)

    while start < text_length:
        hard_end = min(start + chunk_size, text_length)
        end = hard_end

        if hard_end < text_length:
            search_start = start + int(chunk_size * 0.6)
            candidates = [
                text_value.rfind(". ", search_start, hard_end),
                text_value.rfind(" ", search_start, hard_end),
            ]
            best_break = max(candidates)

            if best_break > start:
                end = best_break + 1

        chunk = text_value[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= text_length:
            break

        next_start = end - overlap
        if next_start <= start:
            next_start = end

        start = next_start

    return chunks


def build_embedding_text(record: dict[str, Any], chunk: str) -> str:
    """Combine source metadata and chunk text for embedding."""
    return (
        f"Airline: {record['airline_name']}\n"
        f"Source: {record['source_name']}\n"
        f"Title: {record['title'] or 'Untitled'}\n"
        f"URL: {record['source_url']}\n\n"
        f"{chunk}"
    )


def deterministic_point_id(source_url: str, chunk_index: int) -> str:
    """Build an idempotent Qdrant point ID for a source-page chunk."""
    value = f"{source_url}:{chunk_index}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, value))


def reset_web_data(
    client: QdrantClient,
    collection_name: str,
) -> None:
    """Remove previously ingested web rows and vectors for a clean rebuild."""
    try:
        with tracked_operation(
            logger,
            "web_data_reset",
            collection=collection_name,
        ):
            existing_names = {
                collection.name
                for collection in client.get_collections().collections
            }
            if collection_name in existing_names:
                client.delete_collection(collection_name=collection_name)

            with engine.begin() as connection:
                connection.execute(DELETE_WEB_DOCUMENTS_SQL)
    except Exception as exc:
        raise RuntimeError(
            "Unable to reset existing web ingestion data."
        ) from exc

    print("Removed existing web documents and vector collection")


def create_qdrant_client() -> QdrantClient:
    """Create a Qdrant client from application settings."""
    return QdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
    )


def ensure_qdrant_collection(
    client: QdrantClient,
    collection_name: str,
) -> None:
    """Ensure the target Qdrant collection exists."""
    try:
        with tracked_operation(
            logger,
            "qdrant_collection_setup",
            collection=collection_name,
        ):
            existing_names = {
                collection.name
                for collection in client.get_collections().collections
            }

            if collection_name in existing_names:
                print(f"Qdrant collection ready: {collection_name}")
                return

            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=VECTOR_SIZE,
                    distance=Distance.COSINE,
                ),
            )
    except Exception as exc:
        raise RuntimeError(
            f"Unable to inspect or create Qdrant collection {collection_name!r}."
        ) from exc

    print(f"Created Qdrant collection: {collection_name}")


def flush_points(
    client: QdrantClient,
    collection_name: str,
    points: list[PointStruct],
) -> int:
    """Upsert and clear one pending Qdrant batch."""
    if not points:
        return 0

    count = len(points)

    try:
        with tracked_operation(
            logger,
            "qdrant_points_upsert",
            collection=collection_name,
            point_count=count,
        ):
            client.upsert(
                collection_name=collection_name,
                points=points,
                wait=True,
            )
    except Exception as exc:
        raise QdrantUpsertError(
            f"Unable to upsert {count} points into {collection_name!r}."
        ) from exc

    points.clear()
    return count


@track_call
def main() -> None:
    """Run the end-to-end web-document ingestion pipeline."""
    args = parse_args()
    collection_name = DEFAULT_COLLECTION
    set_request_id(new_request_id("web-ingest"))

    print("Starting web-document ingestion")
    print(f"Input: {args.input}")
    print(f"Qdrant collection: {collection_name}")
    print(f"Chunk size: {CHUNK_SIZE}")
    print(f"Chunk overlap: {CHUNK_OVERLAP}")
    print()
    logger.info(
        "event=web_ingestion_started input_path=%s collection=%s "
        "replace_existing=%s limit=%s",
        args.input,
        collection_name,
        args.replace,
        args.limit,
    )

    create_schema()

    qdrant = create_qdrant_client()
    if args.replace:
        reset_web_data(qdrant, collection_name)
    ensure_qdrant_collection(qdrant, collection_name)

    records = list(read_jsonl(args.input, args.limit))

    if not records:
        raise RuntimeError("No valid records were found in the JSONL input file.")

    pending_points: list[PointStruct] = []
    documents_processed = 0
    chunks_prepared = 0
    points_upserted = 0
    failed_documents = 0

    # A failed document is reported and skipped without discarding later input.
    for record in tqdm(records, desc="Ingesting web documents"):
        try:
            postgres_id = upsert_document(record)
            chunks = chunk_text(record["content_markdown"])

            if not chunks:
                print(f"Skipping empty document: {record['source_url']}")
                failed_documents += 1
                continue

            for chunk_index, chunk in enumerate(chunks):
                embedding_input = build_embedding_text(record, chunk)
                vector = embed_text(embedding_input)

                payload = {
                    "document_type": "web",
                    "source_type": record["source_type"],
                    "source_root_url": record["source_root_url"],
                    "postgres_id": postgres_id,
                    "airline_name": record["airline_name"],
                    "source_name": record["source_name"],
                    "source_url": record["source_url"],
                    "resolved_url": record["resolved_url"],
                    "title": record["title"],
                    "content_hash": record["content_hash"],
                    "crawled_at": record["crawled_at"].isoformat(),
                    "chunk_index": chunk_index,
                    "chunk_count": len(chunks),
                    "text": chunk,
                }

                pending_points.append(
                    PointStruct(
                        id=deterministic_point_id(
                            record["source_url"],
                            chunk_index,
                        ),
                        vector=vector,
                        payload=payload,
                    )
                )

                chunks_prepared += 1

                if len(pending_points) >= QDRANT_BATCH_SIZE:
                    points_upserted += flush_points(
                        qdrant,
                        collection_name,
                        pending_points,
                    )

            documents_processed += 1

        except QdrantUpsertError:
            # Continuing would create more Postgres rows while Qdrant remains
            # unavailable, so fail the ingestion run immediately.
            raise
        except Exception as exc:
            failed_documents += 1
            print(f"\nFailed document {record.get('source_url')}: {exc}")
            logger.error(
                "event=web_document_failed source_url=%s error_type=%s",
                record.get("source_url", "unknown"),
                type(exc).__name__,
            )

    points_upserted += flush_points(
        qdrant,
        collection_name,
        pending_points,
    )

    print()
    print("Web ingestion completed")
    print(f"Documents processed: {documents_processed}")
    print(f"Chunks prepared: {chunks_prepared}")
    print(f"Qdrant points upserted: {points_upserted}")
    print(f"Failed documents: {failed_documents}")
    print(f"Collection: {collection_name}")
    logger.info(
        "event=web_ingestion_completed documents_processed=%s "
        "chunks_prepared=%s points_upserted=%s failed_documents=%s "
        "collection=%s",
        documents_processed,
        chunks_prepared,
        points_upserted,
        failed_documents,
        collection_name,
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Web ingestion failed: {exc}") from exc
