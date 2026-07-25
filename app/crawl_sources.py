"""Crawl configured airline sources and append normalized records to JSONL."""

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# Make dependency errors readable when the script is run outside the project
# environment, rather than failing before configuration can be checked.
try:
    from firecrawl import Firecrawl
except ImportError as exc:
    Firecrawl = None
    FIRECRAWL_IMPORT_ERROR: ImportError | None = exc
else:
    FIRECRAWL_IMPORT_ERROR = None

from app.config import settings


CONFIG_PATH = Path("config/airline_sources.yaml")
OUTPUT_PATH = Path("landing/web/crawled_pages.jsonl")


def content_hash(text: str) -> str:
    """Return a stable SHA-256 digest used for change detection."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_source_config() -> dict:
    """Load and validate the airline source YAML configuration."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Source configuration not found: {CONFIG_PATH}"
        )

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as file:
            config = yaml.safe_load(file)
    except OSError as exc:
        raise RuntimeError(
            f"Unable to read source configuration: {CONFIG_PATH}"
        ) from exc
    except yaml.YAMLError as exc:
        raise RuntimeError(
            f"Invalid YAML in source configuration: {CONFIG_PATH}"
        ) from exc

    if not isinstance(config, dict) or not isinstance(
        config.get("airlines"), dict
    ):
        raise ValueError(
            "Source configuration must contain an 'airlines' mapping."
        )

    return config


def get_metadata_value(
    metadata: Any,
    name: str,
    default: str = "",
) -> str:
    """Read optional metadata returned as either an object or dictionary."""
    if metadata is None:
        return default

    if isinstance(metadata, dict):
        return str(metadata.get(name) or default)

    return str(getattr(metadata, name, default) or default)


def crawl_sources() -> None:
    """Crawl every configured source and append successful pages to JSONL."""
    if Firecrawl is None:
        raise RuntimeError(
            "firecrawl-py could not be imported. Activate the project's "
            ".venv and reinstall the requirements."
        ) from FIRECRAWL_IMPORT_ERROR

    if not settings.FIRECRAWL_API_KEY:
        raise RuntimeError(
            "FIRECRAWL_API_KEY is missing from .env"
        )

    config = load_source_config()
    try:
        firecrawl = Firecrawl(
            api_key=settings.FIRECRAWL_API_KEY
        )
    except Exception as exc:
        raise RuntimeError("Unable to initialize Firecrawl.") from exc

    try:
        OUTPUT_PATH.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
    except OSError as exc:
        raise RuntimeError(
            f"Unable to create output directory: {OUTPUT_PATH.parent}"
        ) from exc

    successful = 0
    failed = 0

    try:
        output = OUTPUT_PATH.open("a", encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"Unable to open crawl output: {OUTPUT_PATH}"
        ) from exc

    # Append mode preserves previous crawl runs for downstream deduplication.
    with output:
        for airline, sources in config["airlines"].items():
            if not isinstance(sources, list):
                print(f"Skipped {airline}: sources must be a list")
                failed += 1
                continue

            for source in sources:
                if not isinstance(source, dict):
                    print(f"Skipped {airline}: invalid source entry")
                    failed += 1
                    continue

                source_name = str(source.get("source_name") or "").strip()
                url = str(source.get("url") or "").strip()

                if not source_name or not url:
                    print(f"Skipped {airline}: source_name and url are required")
                    failed += 1
                    continue

                print(
                    f"Crawling {airline} | "
                    f"{source_name} | {url}"
                )

                try:
                    result = firecrawl.scrape(
                        url,
                        formats=["markdown"],
                    )

                    markdown = result.markdown or ""

                    if not markdown.strip():
                        print("Skipped: empty content")
                        failed += 1
                        continue

                    record = {
                        "airline_name": airline,
                        "source_name": source_name,
                        "source_url": url,
                        "resolved_url": get_metadata_value(
                            result.metadata,
                            "source_url",
                            url,
                        ),
                        "title": get_metadata_value(
                            result.metadata,
                            "title",
                        ),
                        "markdown": markdown,
                        "content_hash": content_hash(markdown),
                        "crawled_at": datetime.now(
                            timezone.utc
                        ).isoformat(),
                    }

                    output.write(
                        json.dumps(
                            record,
                            ensure_ascii=False,
                        )
                        + "\n"
                    )

                    successful += 1
                    print("Success")

                except Exception as exc:
                    failed += 1
                    print(f"Failed: {exc}")

                # Avoid immediately hitting the next source.
                time.sleep(2)

    print()
    print("Crawl completed")
    print("Successful:", successful)
    print("Failed:", failed)
    print("Output:", OUTPUT_PATH)


if __name__ == "__main__":
    try:
        crawl_sources()
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Crawl failed: {exc}") from exc
