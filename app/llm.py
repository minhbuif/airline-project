from google import genai

from app.config import settings


def get_client() -> genai.Client:
    if not settings.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is missing. "
            "Add it to your .env file."
        )

    return genai.Client(
        api_key=settings.GEMINI_API_KEY,
    )


def generate_answer(prompt: str) -> str:
    if not prompt.strip():
        raise ValueError("Prompt cannot be empty.")

    client = get_client()

    try:
        interaction = client.interactions.create(
            model=settings.GEMINI_MODEL,
            input=prompt,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Gemini API request failed: {exc}"
        ) from exc

    answer = interaction.output_text

    if not answer or not answer.strip():
        raise RuntimeError(
            "Gemini returned an empty response."
        )

    return answer.strip()