"""Load application settings from environment variables and `.env`."""

import os

from dotenv import load_dotenv

# Load local development values without overriding variables supplied by the
# process, container, or deployment platform.
load_dotenv()


def _get_int(name: str, default: int) -> int:
    """Read an integer setting and report invalid values clearly."""
    raw_value = os.getenv(name, str(default))

    try:
        return int(raw_value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"{name} must be an integer; received {raw_value!r}."
        ) from exc


class Settings:
    """Centralized environment-backed application configuration."""

    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
    POSTGRES_DB = os.getenv("POSTGRES_DB", "airline_rag")
    POSTGRES_USER = os.getenv("POSTGRES_USER", "airline_user")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

    QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
    QDRANT_PORT = _get_int("QDRANT_PORT", 6333)
    QDRANT_COLLECTION = os.getenv(
        "QDRANT_COLLECTION",
        "airline_reviews",
    )
    QDRANT_WEB_COLLECTION = os.getenv(
        "QDRANT_WEB_COLLECTION",
        "airline_web_documents",
    )

    LANDING_PATH = os.getenv("LANDING_PATH", "./landing")

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv(
        "GEMINI_MODEL",
        "gemini-2.5-flash",
    )

    FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")

    @property
    def postgres_url(self) -> str:
        """Build the SQLAlchemy connection URL from Postgres settings."""
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:"
            f"{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:"
            f"{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


# Import this shared instance instead of re-reading environment variables.
settings = Settings()
