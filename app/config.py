import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
    POSTGRES_DB = os.getenv("POSTGRES_DB", "airline_rag")
    POSTGRES_USER = os.getenv("POSTGRES_USER", "airline_user")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

    QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
    QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
    QDRANT_COLLECTION = os.getenv(
        "QDRANT_COLLECTION",
        "airline_reviews",
    )

    LANDING_PATH = os.getenv("LANDING_PATH", "./landing")

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv(
        "GEMINI_MODEL",
        "gemini-2.5-flash",
    )

    @property
    def postgres_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:"
            f"{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:"
            f"{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()