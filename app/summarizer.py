"""Deterministic extractive summaries for passenger reviews."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Mapping


DEFAULT_MAX_SENTENCES = 3
DEFAULT_MAX_CHARACTERS = 600

SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")
WORD_RE = re.compile(r"[a-z0-9']+")

# Common language and domain words carry little information when deciding
# which sentences best represent one airline review.
STOP_WORDS = {
    "about", "after", "again", "against", "airline", "all", "also", "and",
    "any", "are", "because", "been", "before", "being", "between", "both",
    "but", "can", "could", "did", "does", "doing", "during", "each", "few",
    "flight", "for", "from", "further", "had", "has", "have", "having",
    "here", "hers", "him", "himself", "into", "its", "itself", "just",
    "more", "most", "not", "only", "other", "our", "ours", "out", "over",
    "passenger", "review", "same", "she", "should", "some", "such", "than",
    "that", "the", "their", "theirs", "them", "themselves", "then", "there",
    "these", "they", "this", "those", "through", "too", "under", "until",
    "very", "was", "were", "what", "when", "where", "which", "while", "who",
    "whom", "why", "with", "would", "you", "your", "yours", "yourself",
}


def _content_words(sentence: str) -> list[str]:
    """Return lowercase words useful for extractive sentence scoring."""
    return [
        word
        for word in WORD_RE.findall(sentence.casefold())
        if len(word) > 2 and word not in STOP_WORDS
    ]


def _truncate_at_word(value: str, max_characters: int) -> str:
    """Shorten text without cutting through the final word."""
    if len(value) <= max_characters:
        return value

    content_limit = max_characters - 1
    shortened = value[: content_limit + 1].rsplit(" ", 1)[0].rstrip()
    if not shortened:
        shortened = value[:content_limit].rstrip()
    return shortened.rstrip(".,;:") + "…"


def summarize_review(
    review_text: str,
    max_sentences: int = DEFAULT_MAX_SENTENCES,
    max_characters: int = DEFAULT_MAX_CHARACTERS,
) -> str:
    """Select representative original sentences from a passenger review.

    The summary is extractive rather than generative: it never invents text,
    costs no API credits, and produces the same output on every ingestion run.
    """
    if not isinstance(review_text, str):
        raise ValueError("review_text must be a string")
    if max_sentences < 1:
        raise ValueError("max_sentences must be at least 1")
    if max_characters < 50:
        raise ValueError("max_characters must be at least 50")

    normalized = " ".join(review_text.split()).strip()
    if not normalized or len(normalized) <= max_characters:
        return normalized

    raw_sentences = [
        sentence.strip()
        for sentence in SENTENCE_BOUNDARY_RE.split(normalized)
        if sentence.strip()
    ]
    sentences: list[str] = []
    seen_sentences: set[str] = set()
    for sentence in raw_sentences:
        identity = sentence.casefold()
        if identity not in seen_sentences:
            seen_sentences.add(identity)
            sentences.append(sentence)

    if len(sentences) == 1:
        return _truncate_at_word(sentences[0], max_characters)

    sentence_words = [_content_words(sentence) for sentence in sentences]
    frequencies = Counter(
        word
        for words in sentence_words
        for word in set(words)
    )
    highest_frequency = max(frequencies.values(), default=1)

    scored_sentences: list[tuple[float, int]] = []
    for index, words in enumerate(sentence_words):
        if words:
            relevance = sum(
                frequencies[word] / highest_frequency
                for word in set(words)
            ) / math.sqrt(len(words))
        else:
            relevance = 0.0

        # A small position bonus preserves introductory context without always
        # selecting the first sentences regardless of their content.
        position_bonus = 0.2 / (index + 1)
        scored_sentences.append((relevance + position_bonus, index))

    chosen_indexes = sorted(
        index
        for _score, index in sorted(
            scored_sentences,
            key=lambda item: (-item[0], item[1]),
        )[:max_sentences]
    )
    summary = " ".join(sentences[index] for index in chosen_indexes)
    return _truncate_at_word(summary, max_characters)


def build_review_embedding_text(review: Mapping[str, Any]) -> str:
    """Build metadata-rich, summary-first text for review embedding."""
    review_text = str(review.get("review_text") or "")
    review_summary = str(review.get("review_summary") or "")
    if review_summary == review_text:
        review_section = f"Review:\n{review_text}"
    else:
        review_section = (
            f"Review Summary:\n{review_summary}\n\n"
            f"Full Review:\n{review_text}"
        )

    return f"""
Airline: {review.get("airline_name") or ""}
Title: {review.get("title") or ""}
Country: {review.get("country") or ""}
Review Date: {review.get("review_date") or ""}
Verified: {review.get("verified") or ""}
Traveller Type: {review.get("traveller_type") or ""}
Seat Type: {review.get("seat_type") or ""}
Route: {review.get("route") or ""}
Date Flown: {review.get("date_flown") or ""}
Aircraft: {review.get("aircraft") or ""}
Recommended: {review.get("recommended") or ""}

{review_section}
""".strip()
