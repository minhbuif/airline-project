"""Lazy loading and use of the sentence-transformer embedding model."""

from typing import Any

from app.logging_config import (
    get_logger,
    track_call_debug,
    tracked_operation,
)

# Defer a missing/incompatible dependency error until an embedding is needed,
# allowing API and UI modules to import and show an actionable message.
try:
    from sentence_transformers import SentenceTransformer
except ImportError as exc:
    SentenceTransformer = None
    EMBEDDER_IMPORT_ERROR: ImportError | None = exc
else:
    EMBEDDER_IMPORT_ERROR = None

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
VECTOR_SIZE = 384

_model: Any = None
logger = get_logger(__name__)


@track_call_debug
def get_model() -> Any:
    """Load and cache the embedding model on first use."""
    global _model

    if SentenceTransformer is None:
        raise RuntimeError(
            "sentence-transformers could not be imported. Activate the "
            "project's .venv and reinstall the requirements."
        ) from EMBEDDER_IMPORT_ERROR

    if _model is None:
        print(f"Loading embedding model: {MODEL_NAME}")

        try:
            with tracked_operation(
                logger,
                "embedding_model_load",
                model=MODEL_NAME,
            ):
                _model = SentenceTransformer(MODEL_NAME)
        except Exception as exc:
            raise RuntimeError(
                f"Unable to load embedding model {MODEL_NAME!r}."
            ) from exc

    return _model


@track_call_debug
def embed_text(text: str) -> list[float]:
    """Convert non-empty text into a normalized embedding vector."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Embedding input must be a non-empty string.")

    model = get_model()

    try:
        with tracked_operation(
            logger,
            "text_embedding",
            level=10,
            model=MODEL_NAME,
            input_characters=len(text),
        ):
            vector = model.encode(text, normalize_embeddings=True)
            values = vector.tolist()
    except Exception as exc:
        raise RuntimeError("Unable to generate the text embedding.") from exc

    if len(values) != VECTOR_SIZE:
        raise RuntimeError(
            f"Embedding model returned {len(values)} values; "
            f"expected {VECTOR_SIZE}."
        )

    return values
