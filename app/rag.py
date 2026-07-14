from app.llm import generate_answer
from app.retriever import retrieve_reviews


MAX_REVIEW_CHARACTERS = 3000


def format_context(reviews: list[dict]) -> str:
    context_blocks: list[str] = []

    for index, review in enumerate(reviews, start=1):
        review_text = review.get("text") or ""

        # Prevent one long review from consuming the whole prompt.
        review_text = review_text[:MAX_REVIEW_CHARACTERS]

        block = f"""
SOURCE {index}
Airline: {review.get("airline_name") or "Unknown"}
Title: {review.get("title") or "Untitled"}
Review Date: {review.get("review_date") or "Unknown"}
Traveller Type: {review.get("traveller_type") or "Unknown"}
Seat Type: {review.get("seat_type") or "Unknown"}
Route: {review.get("route") or "Unknown"}
Aircraft: {review.get("aircraft") or "Unknown"}
Recommended: {review.get("recommended") or "Unknown"}

Review:
{review_text}
""".strip()

        context_blocks.append(block)

    return "\n\n---\n\n".join(context_blocks)


def build_prompt(question: str, context: str) -> str:
    return f"""
You are an Airline Review Intelligence Assistant.

Your task is to answer questions using only the passenger-review
sources supplied below.

Rules:
1. Use only information contained in the supplied sources.
2. Do not use outside knowledge.
3. Cite claims with [SOURCE 1], [SOURCE 2], and so on.
4. Clearly distinguish individual opinions from repeated patterns.
5. Do not describe passenger reviews as objective facts.
6. Do not make claims about aviation safety, live ticket prices,
   current schedules, or airline performance outside this dataset.
7. If the sources do not contain enough evidence, say:
   "The retrieved reviews do not provide enough information to
   answer this question."
8. Keep the answer clear and concise.
9. When comparing airlines, make sure the retrieved sources actually
   include each airline being compared.

USER QUESTION:
{question}

RETRIEVED PASSENGER REVIEWS:
{context}

ANSWER:
""".strip()


def prepare_rag_input(
    question: str,
    limit: int = 5,
) -> dict:
    question = question.strip()

    if not question:
        raise ValueError("Question cannot be empty.")

    reviews = retrieve_reviews(
        query=question,
        limit=limit,
    )

    context = format_context(reviews)
    prompt = build_prompt(question, context)

    return {
        "question": question,
        "retrieved_reviews": reviews,
        "context": context,
        "prompt": prompt,
    }


def answer_question(
    question: str,
    limit: int = 5,
) -> dict:
    rag_input = prepare_rag_input(
        question=question,
        limit=limit,
    )

    retrieved_reviews = rag_input["retrieved_reviews"]

    if not retrieved_reviews:
        return {
            "question": question,
            "answer": "No relevant reviews were found in the dataset.",
            "sources": [],
        }

    answer = generate_answer(rag_input["prompt"])

    sources = []

    for index, review in enumerate(retrieved_reviews, start=1):
        sources.append({
            "source_id": index,
            **review,
        })

    return {
        "question": question,
        "answer": answer,
        "sources": sources,
    }