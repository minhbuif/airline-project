"""Collect quality-filtered airline review pages with Firecrawl.

The crawler first scrapes each configured listing page to discover review URLs,
then scrapes only a bounded number of URLs matching that source's allow-list.
Fresh runs replace the JSONL output atomically so removed sources and old crawl
runs cannot silently remain in the ingestion input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit

import yaml

try:
    from firecrawl import Firecrawl
except ImportError as exc:
    Firecrawl = None
    FIRECRAWL_IMPORT_ERROR: ImportError | None = exc
else:
    FIRECRAWL_IMPORT_ERROR = None

from app.config import settings
from app.logging_config import (
    get_logger,
    new_request_id,
    set_request_id,
    track_call,
    tracked_operation,
)


CONFIG_PATH = Path("config/airline_sources.yaml")
OUTPUT_PATH = Path("landing/web/crawled_pages.jsonl")
DEFAULT_MIN_CONTENT_CHARACTERS = 1_000
DEFAULT_MAX_PAGES = 5
DEFAULT_REQUEST_DELAY_SECONDS = 1.0
logger = get_logger(__name__)

BLOCKED_CONTENT_MARKERS = (
    "verifying your connection",
    "verify your browser",
    "verification failed",
    "access denied",
    "captcha",
    "enable javascript and cookies to continue",
)

MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^\n)]*\)")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^\s)]+)")
BARE_URL_RE = re.compile(r"https?://[^\s)>\]]+")


def parse_args() -> argparse.Namespace:
    """Parse command-line filters and output behavior."""
    parser = argparse.ArgumentParser(
        description="Crawl quality-filtered airline passenger-review pages."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help=f"Source configuration path. Default: {CONFIG_PATH}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help=f"JSONL output path. Default: {OUTPUT_PATH}",
    )
    parser.add_argument(
        "--airline",
        action="append",
        default=[],
        help="Crawl only this airline. Repeat to select multiple airlines.",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Keep existing valid JSONL records instead of starting fresh.",
    )
    return parser.parse_args()


def content_hash(text: str) -> str:
    """Return a stable SHA-256 digest used for content deduplication."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonicalize_url(url: str) -> str:
    """Normalize a URL for deduplication while preserving meaningful paths."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()

    if not scheme or not hostname:
        raise ValueError(f"Invalid absolute URL: {url!r}")

    port = parts.port
    netloc = hostname
    if port and not (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"

    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")

    # Query strings on the selected sources are tracking or alternate paging;
    # their canonical review/page identity is already encoded in the path.
    return urlunsplit((scheme, netloc, path, "", ""))


def clean_markdown(markdown: str) -> str:
    """Remove image-only noise and collapse excessive blank lines."""
    without_images = MARKDOWN_IMAGE_RE.sub("", markdown)
    lines = [line.rstrip() for line in without_images.splitlines()]
    cleaned_lines: list[str] = []
    blank_pending = False

    for line in lines:
        if not line.strip():
            blank_pending = bool(cleaned_lines)
            continue

        if blank_pending:
            cleaned_lines.append("")
            blank_pending = False

        cleaned_lines.append(line.strip())

    return "\n".join(cleaned_lines).strip()


def get_metadata_value(
    metadata: Any,
    name: str,
    default: Any = "",
) -> Any:
    """Read optional Firecrawl metadata represented as an object or mapping."""
    if metadata is None:
        return default

    if isinstance(metadata, dict):
        return metadata.get(name) or default

    return getattr(metadata, name, default) or default


def extract_links(document: Any, base_url: str) -> list[str]:
    """Extract and canonicalize links returned by Firecrawl or Markdown."""
    candidates: list[str] = []
    raw_links = getattr(document, "links", None) or []

    for item in raw_links:
        if isinstance(item, str):
            candidates.append(item)
        elif isinstance(item, dict):
            candidates.append(str(item.get("url") or ""))
        else:
            candidates.append(str(getattr(item, "url", "") or ""))

    markdown = str(getattr(document, "markdown", "") or "")
    candidates.extend(MARKDOWN_LINK_RE.findall(markdown))
    candidates.extend(BARE_URL_RE.findall(markdown))

    links: list[str] = []
    seen: set[str] = set()

    for candidate in candidates:
        if not candidate:
            continue

        try:
            normalized = canonicalize_url(urljoin(base_url, candidate))
        except ValueError:
            continue

        if normalized not in seen:
            seen.add(normalized)
            links.append(normalized)

    return links


def quality_issue(
    markdown: str,
    required_terms: Iterable[str],
    min_content_characters: int,
) -> str | None:
    """Return a rejection reason, or ``None`` when content is acceptable."""
    lowered = markdown.casefold()

    for marker in BLOCKED_CONTENT_MARKERS:
        if marker in lowered:
            return "blocked_or_verification_page"

    if len(markdown) < min_content_characters:
        return "content_too_short"

    missing_terms = [
        term for term in required_terms
        if term.casefold() not in lowered
    ]
    if missing_terms:
        return "missing_required_terms"

    # Pages dominated by links are generally indexes or navigation shells.
    visible_text = BARE_URL_RE.sub("", markdown)
    if len(visible_text.strip()) < min_content_characters:
        return "insufficient_visible_text"

    return None


def load_source_config(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load and validate the airline source YAML configuration."""
    if not config_path.exists():
        raise FileNotFoundError(
            f"Source configuration not found: {config_path}"
        )

    try:
        with tracked_operation(
            logger,
            "source_config_read",
            path=config_path,
        ):
            with config_path.open("r", encoding="utf-8") as file:
                config = yaml.safe_load(file)
    except OSError as exc:
        raise RuntimeError(
            f"Unable to read source configuration: {config_path}"
        ) from exc
    except yaml.YAMLError as exc:
        raise RuntimeError(
            f"Invalid YAML in source configuration: {config_path}"
        ) from exc

    airlines = config.get("airlines") if isinstance(config, dict) else None
    if not isinstance(airlines, dict) or not airlines:
        raise ValueError(
            "Source configuration must contain a non-empty 'airlines' mapping."
        )

    for airline, sources in airlines.items():
        if not isinstance(sources, list) or not sources:
            raise ValueError(f"{airline}: sources must be a non-empty list.")

        for index, source in enumerate(sources, start=1):
            if not isinstance(source, dict):
                raise ValueError(f"{airline} source {index} must be a mapping.")

            required = ("source_name", "url", "url_pattern")
            missing = [name for name in required if not source.get(name)]
            if missing:
                raise ValueError(
                    f"{airline} source {index} is missing: {', '.join(missing)}"
                )

            try:
                re.compile(str(source["url_pattern"]))
                canonicalize_url(str(source["url"]))
            except (re.error, ValueError) as exc:
                raise ValueError(
                    f"{airline} source {index} has invalid URL configuration."
                ) from exc

    return config


def scrape_document(client: Any, url: str, include_links: bool = False) -> Any:
    """Scrape one page using options tuned for clean RAG input."""
    formats = ["markdown", "links"] if include_links else ["markdown"]

    try:
        with tracked_operation(
            logger,
            "firecrawl_scrape",
            source_url=url,
            include_links=include_links,
        ):
            return client.scrape(
                url,
                formats=formats,
                only_main_content=True,
                remove_base64_images=True,
                block_ads=True,
                timeout=60_000,
            )
    except Exception as exc:
        raise RuntimeError(f"Firecrawl request failed for {url}") from exc


def build_record(
    document: Any,
    airline: str,
    source: dict[str, Any],
    requested_url: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Normalize one Firecrawl response and apply source quality gates."""
    raw_markdown = str(getattr(document, "markdown", "") or "")
    markdown = clean_markdown(raw_markdown)
    metadata = getattr(document, "metadata", None)
    status_code = get_metadata_value(metadata, "status_code", 200)

    try:
        status_code = int(status_code)
    except (TypeError, ValueError):
        status_code = 200

    if status_code >= 400:
        return None, f"http_{status_code}"

    issue = quality_issue(
        markdown=markdown,
        required_terms=source.get("required_terms", [airline, "review"]),
        min_content_characters=int(
            source.get(
                "min_content_characters",
                DEFAULT_MIN_CONTENT_CHARACTERS,
            )
        ),
    )
    if issue:
        return None, issue

    resolved_url = get_metadata_value(metadata, "source_url", requested_url)
    try:
        resolved_url = canonicalize_url(str(resolved_url))
    except ValueError:
        resolved_url = canonicalize_url(requested_url)

    record = {
        "airline_name": airline,
        "source_name": str(source["source_name"]),
        "source_type": "passenger_reviews",
        "source_root_url": canonicalize_url(str(source["url"])),
        "source_url": resolved_url,
        "resolved_url": resolved_url,
        "title": str(get_metadata_value(metadata, "title", "")),
        "markdown": markdown,
        "content_hash": content_hash(markdown),
        "crawled_at": datetime.now(timezone.utc).isoformat(),
    }
    return record, None


def discover_target_urls(
    seed_document: Any,
    source: dict[str, Any],
) -> list[str]:
    """Select only allow-listed review URLs from a source listing page."""
    seed_url = canonicalize_url(str(source["url"]))
    pattern = re.compile(str(source["url_pattern"]), re.IGNORECASE)
    discovered = [
        url for url in extract_links(seed_document, seed_url)
        if pattern.search(url)
    ]

    # Tripadvisor does not consistently expose pagination links in its link
    # payload. Its airline-review paths use deterministic `Reviews-orN-`
    # offsets, so configured sources can add bounded pages without a site-wide
    # crawl.
    pagination_step = int(source.get("pagination_step", 0))
    max_pages = max(1, int(source.get("max_pages", DEFAULT_MAX_PAGES)))
    if pagination_step > 0 and "-Reviews-" in seed_url:
        for page_number in range(1, max_pages):
            paginated = seed_url.replace(
                "-Reviews-",
                f"-Reviews-or{pagination_step * page_number}-",
                1,
            )
            if not paginated.endswith(".html"):
                paginated += ".html"
            if pattern.search(paginated):
                discovered.append(paginated)

    # Preserve the listing order, which normally places newest reviews first.
    return list(dict.fromkeys(discovered))


def load_existing_records(output_path: Path) -> list[dict[str, Any]]:
    """Load valid existing records for explicit append-mode crawls."""
    if not output_path.exists():
        return []

    records: list[dict[str, Any]] = []
    try:
        with tracked_operation(
            logger,
            "crawl_output_read",
            path=output_path,
        ):
            with output_path.open("r", encoding="utf-8") as file:
                for line_number, line in enumerate(file, start=1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        print(
                            "Skipping malformed existing line "
                            f"{line_number}: {exc}"
                        )
                        continue
                    if isinstance(record, dict) and record.get("source_url"):
                        records.append(record)
    except OSError as exc:
        raise RuntimeError(f"Unable to read existing output: {output_path}") from exc

    return records


def write_records_atomically(
    records: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Replace JSONL output only after a complete successful crawl run."""
    try:
        with tracked_operation(
            logger,
            "crawl_output_write",
            path=output_path,
            record_count=len(records),
        ):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
            with temporary_path.open("w", encoding="utf-8") as output:
                for record in records:
                    output.write(json.dumps(record, ensure_ascii=False) + "\n")
            os.replace(temporary_path, output_path)
    except OSError as exc:
        raise RuntimeError(f"Unable to write crawl output: {output_path}") from exc


@track_call
def crawl_sources(
    config_path: Path = CONFIG_PATH,
    output_path: Path = OUTPUT_PATH,
    selected_airlines: Iterable[str] = (),
    append: bool = False,
) -> dict[str, int]:
    """Crawl configured sources and return detailed run metrics."""
    set_request_id(new_request_id("crawl"))
    logger.info(
        "event=crawl_started config_path=%s output_path=%s append=%s",
        config_path,
        output_path,
        append,
    )
    if Firecrawl is None:
        raise RuntimeError(
            "firecrawl-py could not be imported. Activate the project's "
            ".venv and reinstall the requirements."
        ) from FIRECRAWL_IMPORT_ERROR

    if not settings.FIRECRAWL_API_KEY:
        raise RuntimeError("FIRECRAWL_API_KEY is missing from .env")

    config = load_source_config(config_path)
    selected = {name.casefold() for name in selected_airlines}
    configured_names = {name.casefold() for name in config["airlines"]}
    unknown = selected - configured_names
    if unknown:
        raise ValueError(f"Unknown airline selection: {', '.join(sorted(unknown))}")

    try:
        with tracked_operation(logger, "firecrawl_client_initialization"):
            client = Firecrawl(api_key=settings.FIRECRAWL_API_KEY)
    except Exception as exc:
        raise RuntimeError("Unable to initialize Firecrawl.") from exc

    records = load_existing_records(output_path) if append else []
    seen_urls = {
        canonicalize_url(str(record["source_url"]))
        for record in records
        if record.get("source_url")
    }
    seen_hashes = {
        str(record.get("content_hash"))
        for record in records
        if record.get("content_hash")
    }
    metrics: Counter[str] = Counter()
    attempted_airlines: set[str] = set()
    accepted_airlines: set[str] = set()

    for airline, sources in config["airlines"].items():
        if selected and airline.casefold() not in selected:
            continue

        attempted_airlines.add(airline)

        for source in sources:
            source_name = str(source["source_name"])
            seed_url = canonicalize_url(str(source["url"]))
            max_pages = max(1, int(source.get("max_pages", DEFAULT_MAX_PAGES)))
            delay = max(
                0.0,
                float(
                    source.get(
                        "request_delay_seconds",
                        DEFAULT_REQUEST_DELAY_SECONDS,
                    )
                ),
            )

            print(f"Discovering {airline} | {source_name} | {seed_url}")
            logger.info(
                "event=crawl_source_started airline=%s source_name=%s "
                "source_url=%s max_pages=%s",
                airline,
                source_name,
                seed_url,
                max_pages,
            )
            metrics["sources_attempted"] += 1

            try:
                seed_document = scrape_document(client, seed_url, include_links=True)
            except RuntimeError as exc:
                metrics["request_failed"] += 1
                print(f"Source failed: {exc}")
                continue

            if delay:
                time.sleep(delay)

            targets = discover_target_urls(seed_document, source)
            include_seed = bool(source.get("include_seed", False))
            if include_seed:
                targets.insert(0, seed_url)

            # Deduplicate while retaining discovery order, then enforce the
            # configured credit/page budget for this source.
            targets = list(dict.fromkeys(targets))[:max_pages]
            metrics["pages_discovered"] += len(targets)

            if not targets:
                metrics["no_matching_links"] += 1
                print("No allow-listed review pages were discovered")
                continue

            for target_url in targets:
                if target_url in seen_urls:
                    metrics["duplicate_url"] += 1
                    continue

                try:
                    if target_url == seed_url:
                        document = seed_document
                    else:
                        document = scrape_document(client, target_url)
                        if delay:
                            time.sleep(delay)

                    record, issue = build_record(
                        document=document,
                        airline=airline,
                        source=source,
                        requested_url=target_url,
                    )
                except Exception as exc:
                    metrics["request_failed"] += 1
                    print(f"Page failed: {target_url} | {exc}")
                    continue

                if issue or record is None:
                    metrics[f"rejected_{issue or 'unknown'}"] += 1
                    print(f"Rejected: {target_url} | {issue}")
                    logger.info(
                        "event=crawl_page_rejected airline=%s source_name=%s "
                        "source_url=%s reason=%s",
                        airline,
                        source_name,
                        target_url,
                        issue or "unknown",
                    )
                    continue

                if record["content_hash"] in seen_hashes:
                    metrics["duplicate_content"] += 1
                    continue

                records.append(record)
                seen_urls.add(record["source_url"])
                seen_hashes.add(record["content_hash"])
                accepted_airlines.add(airline)
                metrics["pages_accepted"] += 1
                print(
                    f"Accepted: {record['title'] or record['source_url']} "
                    f"({len(record['markdown']):,} chars)"
                )

    missing_airlines = attempted_airlines - accepted_airlines
    if not append and missing_airlines:
        raise RuntimeError(
            "No acceptable pages were collected for: "
            f"{', '.join(sorted(missing_airlines))}. Existing output was preserved."
        )

    if metrics["pages_accepted"] == 0 and not records:
        raise RuntimeError(
            "The crawl produced no acceptable pages; existing output was preserved."
        )

    write_records_atomically(records, output_path)
    metrics["records_written"] = len(records)
    logger.info(
        "event=crawl_completed output_path=%s records_written=%s "
        "pages_accepted=%s request_failed=%s",
        output_path,
        len(records),
        metrics["pages_accepted"],
        metrics["request_failed"],
    )

    print("\nCrawl completed")
    for name, count in sorted(metrics.items()):
        print(f"{name}: {count}")
    print(f"Output: {output_path}")

    return dict(metrics)


if __name__ == "__main__":
    arguments = parse_args()
    try:
        crawl_sources(
            config_path=arguments.config,
            output_path=arguments.output,
            selected_airlines=arguments.airline,
            append=arguments.append,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Crawl failed: {exc}") from exc
