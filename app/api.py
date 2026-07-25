"""FastAPI routes for retrieval-only search and generated answers."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.rag import answer_question, prepare_rag_input


app = FastAPI(
    title="Airline Review RAG API",
    version="0.2.0",
)


class AskRequest(BaseModel):
    """Validated request body shared by the search and answer routes."""

    question: str = Field(
        min_length=3,
        max_length=1000,
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=10,
    )


@app.get("/health")
def health() -> dict:
    """Return a lightweight process health response."""
    return {"status": "ok"}


@app.post("/search")
def search_only(request: AskRequest) -> dict:
    """Retrieve relevant reviews without calling the language model."""
    try:
        result = prepare_rag_input(
            question=request.question,
            limit=request.limit,
        )

        return {
            "question": result["question"],
            "retrieved_reviews": result[
                "retrieved_reviews"
            ],
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:
        # Dependency failures are upstream service failures from the API's
        # perspective, rather than invalid requests.
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unexpected server error.",
        ) from exc


@app.post("/ask")
def ask(request: AskRequest) -> dict:
    """Retrieve sources and ask Gemini for a grounded answer."""
    try:
        return answer_question(
            question=request.question,
            limit=request.limit,
        )

    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unexpected server error.",
        ) from exc
