"""Tests for deterministic extractive passenger-review summaries."""

import unittest

from app.summarizer import summarize_review


class SummarizerTests(unittest.TestCase):
    """Verify summary safety, stability, and size constraints."""

    def test_short_review_is_preserved(self) -> None:
        review = "The cabin crew was friendly and the seat was comfortable."

        self.assertEqual(summarize_review(review), review)

    def test_long_review_is_extractively_shortened(self) -> None:
        review = (
            "Check-in was routine and the airport was crowded. "
            "The economy seat had extremely limited legroom and poor padding. "
            "Cabin crew responded quickly and remained friendly throughout. "
            "The meal was cold, although the dessert tasted good. "
            "Arrival was twenty minutes early and baggage appeared quickly. "
        ) * 4

        summary = summarize_review(
            review,
            max_sentences=3,
            max_characters=240,
        )

        self.assertLessEqual(len(summary), 240)
        self.assertIn("limited legroom", summary)
        self.assertNotEqual(summary, review)

    def test_summary_is_deterministic(self) -> None:
        review = " ".join(
            f"Sentence {index} discusses cabin service and seat comfort."
            for index in range(30)
        )

        self.assertEqual(
            summarize_review(review),
            summarize_review(review),
        )

    def test_repeated_sentences_are_not_repeated_in_summary(self) -> None:
        sentence = "The seat was uncomfortable and legroom was limited."
        review = " ".join([sentence] * 20)

        self.assertEqual(summarize_review(review), sentence)

    def test_invalid_limits_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            summarize_review("A review.", max_sentences=0)

        with self.assertRaises(ValueError):
            summarize_review("A review.", max_characters=20)


if __name__ == "__main__":
    unittest.main()
