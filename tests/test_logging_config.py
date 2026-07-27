"""Tests for privacy-safe logging and correlation IDs."""

import unittest

from app.logging_config import (
    format_fields,
    get_logger,
    request_context,
    request_id_context,
    track_call,
)


class LoggingConfigTests(unittest.TestCase):
    """Check that tracing is useful without exposing sensitive values."""

    def test_sensitive_fields_are_redacted(self) -> None:
        fields = format_fields(
            api_key="secret-key",
            prompt="private passenger question",
            review_text="private review",
            path="landing/reviews.csv",
        )

        self.assertIn("api_key=<redacted>", fields)
        self.assertIn("prompt=<redacted>", fields)
        self.assertIn("review_text=<redacted>", fields)
        self.assertIn("path=landing/reviews.csv", fields)
        self.assertNotIn("secret-key", fields)
        self.assertNotIn("private passenger question", fields)

    def test_request_context_is_temporary(self) -> None:
        original_id = request_id_context.get()

        with request_context("test-request"):
            self.assertEqual(request_id_context.get(), "test-request")

        self.assertEqual(request_id_context.get(), original_id)

    def test_track_call_logs_caller_but_not_arguments(self) -> None:
        logger = get_logger(__name__)

        @track_call
        def example_call(value: str) -> int:
            return len(value)

        with self.assertLogs(logger, level="INFO") as captured:
            result = example_call("do-not-record-this")

        output = "\n".join(captured.output)
        self.assertEqual(result, 18)
        self.assertIn("event=call_started", output)
        self.assertIn("event=call_completed", output)
        self.assertIn("caller=test_logging_config.py:", output)
        self.assertNotIn("do-not-record-this", output)


if __name__ == "__main__":
    unittest.main()
