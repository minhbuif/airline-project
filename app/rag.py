"""Retrieval-augmented prompt construction and answer orchestration."""

from app.llm import generate_answer
from app.logging_config import get_logger, track_call
from app.retriever import retrieve_reviews
from app.prompts import SYSTEM_PROMPT


MAX_REVIEW_CHARACTERS = 3000
logger = get_logger(__name__)


def format_context(reviews: list[dict]) -> str:
    """Format dataset reviews and web chunks as numbered prompt sources."""
    context_blocks: list[str] = []

    for index, review in enumerate(reviews, start=1):
        if not isinstance(review, dict):
            raise ValueError(
                f"Review {index} must be a dictionary."
            )

        review_text = str(review.get("text") or "")
        review_summary = str(review.get("review_summary") or "")

        # Prevent one long review from consuming the whole prompt.
        review_text = review_text[:MAX_REVIEW_CHARACTERS]

        document_type = review.get("document_type") or "passenger_review"
        source_name = review.get("source_name") or "Airline review dataset"
        source_url = review.get("source_url") or "Not available"

        block = f"""
SOURCE {index}
Source Type: {document_type}
Source Name: {source_name}
Source URL: {source_url}
Airline: {review.get("airline_name") or "Unknown"}
Title: {review.get("title") or "Untitled"}
Review Date: {review.get("review_date") or "Unknown"}
Traveller Type: {review.get("traveller_type") or "Unknown"}
Seat Type: {review.get("seat_type") or "Unknown"}
Route: {review.get("route") or "Unknown"}
Aircraft: {review.get("aircraft") or "Unknown"}
Recommended: {review.get("recommended") or "Unknown"}
Review Summary: {review_summary or "Not available"}

Source Content:
{review_text}
""".strip()

        context_blocks.append(block)

    return "\n\n---\n\n".join(context_blocks)


def build_prompt(question: str, context: str) -> str:
    """Build a grounded prompt containing the question and source context."""
    return f"""
{SYSTEM_PROMPT}

USER QUESTION:
{question}

RETRIEVED AIRLINE SOURCES:
{context}

ANSWER:
""".strip()


@track_call
def prepare_rag_input(
    question: str,
    limit: int = 5,
    retrieval_mode: str = 'vector',
    route: str = '',
    seat_type: str = '',
    dataset_only: bool = False,
) -> dict:
    """Validate a question, retrieve reviews, and build the model prompt."""
    if not isinstance(question, str):
        raise ValueError("Question must be a string.")

    question = question.strip()

    if not question:
        raise ValueError("Question cannot be empty.")

    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValueError("limit must be an integer.")

    if not 1 <= limit <= 10:
        raise ValueError("limit must be between 1 and 10.")

    try:
        reviews = retrieve_reviews(
            query=question,
            limit=limit,
            retrieval_mode=retrieval_mode, route=route, seat_type=seat_type,
            dataset_only=dataset_only,
        )
    except (ValueError, RuntimeError):
        # These exceptions already contain user-facing context.
        raise
    except Exception as exc:
        raise RuntimeError("Review retrieval failed unexpectedly.") from exc

    context = format_context(reviews)
    prompt = build_prompt(question, context)

    logger.info(
        "event=rag_input_prepared source_count=%s context_characters=%s "
        "prompt_characters=%s",
        len(reviews),
        len(context),
        len(prompt),
    )

    return {
        "question": question,
        "retrieved_reviews": reviews,
        "context": context,
        "prompt": prompt,
    }


@track_call
def answer_question(
    question: str,
    limit: int = 5,
    retrieval_mode: str = 'vector',
    route: str = '',
    seat_type: str = '',
    dataset_only: bool = False,
) -> dict:
    """Return a grounded answer together with its retrieved sources."""
    rag_input = prepare_rag_input(
        question=question,
        limit=limit,
        retrieval_mode=retrieval_mode, route=route, seat_type=seat_type,
        dataset_only=dataset_only,
    )

    retrieved_reviews = rag_input["retrieved_reviews"]

    if not retrieved_reviews:
        return {
            "question": question,
            "answer": "No relevant indexed airline sources were found.",
            "sources": [],
            "retrieval_mode": retrieval_mode,
        }

    try:
        answer = generate_answer(rag_input["prompt"])
    except (ValueError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError("Answer generation failed unexpectedly.") from exc

    # Add stable source numbers matching the citations requested in the prompt.
    sources = []

    for index, review in enumerate(retrieved_reviews, start=1):
        sources.append({
            "source_id": index,
            **review,
        })

    result = {
        "question": question,
        "answer": answer,
        "sources": sources,
        "retrieval_mode": retrieval_mode,
    }
    logger.info(
        "event=rag_answer_completed source_count=%s answer_characters=%s",
        len(sources),
        len(answer),
    )
    return result
