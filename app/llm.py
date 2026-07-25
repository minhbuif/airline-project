"""Gemini client creation and answer generation helpers."""

from typing import Any

# Keep the application importable even when Streamlit is started with a Python
# environment that does not contain the Google Gen AI SDK. A clearer error is
# raised when the application actually tries to create a Gemini client.
try:
    from google import genai
except ImportError as exc:
    genai = None
    GENAI_IMPORT_ERROR: ImportError | None = exc
else:
    GENAI_IMPORT_ERROR = None

from app.config import settings


def get_client() -> Any:
    """Validate the Gemini configuration and create an SDK client."""
    if genai is None:
        raise RuntimeError(
            "The Google Gen AI SDK is unavailable. Activate the project's "
            ".venv and run `python -m pip install google-genai`."
        ) from GENAI_IMPORT_ERROR

    if not settings.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is missing. "
            "Add it to your .env file."
        )

    try:
        return genai.Client(
            api_key=settings.GEMINI_API_KEY,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Unable to initialize the Gemini client: {exc}"
        ) from exc


def generate_answer(prompt: str) -> str:
    """Send a prompt to Gemini and return a non-empty text response."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Prompt must be a non-empty string.")

    client = get_client()

    # Convert SDK and network failures into an application-level error that the
    # Streamlit UI can display through its existing try/except block.
    try:
        interaction = client.interactions.create(
            model=settings.GEMINI_MODEL,
            input=prompt,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Gemini API request failed: {exc}"
        ) from exc

    # Guard against an unexpected or incomplete response from the API.
    try:
        answer = interaction.output_text
    except AttributeError as exc:
        raise RuntimeError(
            "Gemini returned a response without an output_text field."
        ) from exc

    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError(
            "Gemini returned an empty response."
        )

    return answer.strip()
