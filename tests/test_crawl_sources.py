"""Tests for crawler URL discovery, cleaning, and quality gates."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.crawl_sources import (
    build_record,
    canonicalize_url,
    clean_markdown,
    discover_target_urls,
    load_source_config,
    quality_issue,
    write_records_atomically,
)


class CrawlSourceTests(unittest.TestCase):
    """Exercise crawler behavior without making Firecrawl requests."""

    def test_source_configuration_has_two_sources_per_airline(self) -> None:
        config = load_source_config()

        self.assertGreater(len(config["airlines"]), 3)
        for sources in config["airlines"].values():
            self.assertEqual(len(sources), 2)

    def test_canonicalize_url_removes_tracking_and_fragment(self) -> None:
        result = canonicalize_url(
            "HTTPS://Example.COM/reviews/?utm_source=test#latest"
        )

        self.assertEqual(result, "https://example.com/reviews")

    def test_clean_markdown_removes_images(self) -> None:
        result = clean_markdown(
            "# Review\n\n![photo](https://example.com/photo.jpg)\n\nUseful text"
        )

        self.assertNotIn("photo.jpg", result)
        self.assertIn("Useful text", result)

    def test_quality_gate_rejects_verification_page(self) -> None:
        issue = quality_issue(
            "# Verifying your connection\nPlease wait.",
            required_terms=[],
            min_content_characters=10,
        )

        self.assertEqual(issue, "blocked_or_verification_page")

    def test_discovery_keeps_only_allowed_links_in_page_order(self) -> None:
        document = SimpleNamespace(
            links=[
                "https://flight-report.com/en/report/200/example",
                "https://flight-report.com/en/airline/1/example",
                "https://flight-report.com/en/report/100/example",
            ],
            markdown="",
        )
        source = {
            "url": "https://flight-report.com/en/airline/1/example/",
            "url_pattern": r"^https://flight-report\.com/en/report/",
        }

        result = discover_target_urls(document, source)

        self.assertEqual(
            result,
            [
                "https://flight-report.com/en/report/200/example",
                "https://flight-report.com/en/report/100/example",
            ],
        )

    def test_discovery_generates_bounded_tripadvisor_pages(self) -> None:
        document = SimpleNamespace(links=[], markdown="")
        source = {
            "url": (
                "https://www.tripadvisor.com/"
                "Airline_Review-d1-Reviews-Example-Air"
            ),
            "url_pattern": (
                r"^https://www\.tripadvisor\.com/"
                r"Airline_Review-d1-Reviews(?:-or\d+)?-Example-Air(?:\.html)?$"
            ),
            "pagination_step": 10,
            "max_pages": 3,
        }

        result = discover_target_urls(document, source)

        self.assertEqual(
            result,
            [
                "https://www.tripadvisor.com/"
                "Airline_Review-d1-Reviews-or10-Example-Air.html",
                "https://www.tripadvisor.com/"
                "Airline_Review-d1-Reviews-or20-Example-Air.html",
            ],
        )

    def test_build_record_accepts_meaningful_review(self) -> None:
        markdown = (
            "# Review of Example Air flight\n\n"
            + "Flight review by a passenger. "
            + ("Comfortable cabin and helpful crew. " * 80)
        )
        document = SimpleNamespace(
            markdown=markdown,
            metadata=SimpleNamespace(
                title="Example Air flight review",
                source_url="https://example.com/review/1",
                status_code=200,
            ),
        )
        source = {
            "source_name": "Example Reviews",
            "url": "https://example.com/list",
            "required_terms": ["Example Air", "flight review"],
            "min_content_characters": 1_000,
        }

        record, issue = build_record(
            document,
            airline="Example Air",
            source=source,
            requested_url="https://example.com/review/1",
        )

        self.assertIsNone(issue)
        self.assertIsNotNone(record)
        self.assertEqual(record["airline_name"], "Example Air")

    def test_atomic_writer_replaces_old_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "crawl.jsonl"
            output_path.write_text('{"old": true}\n', encoding="utf-8")

            write_records_atomically([{"new": True}], output_path)

            self.assertEqual(output_path.read_text(encoding="utf-8"), '{"new": true}\n')


if __name__ == "__main__":
    unittest.main()
