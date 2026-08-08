"""FastAPI routes for retrieval-only search and generated answers."""

import re
import time

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app.graph import get_airline_graph_overview, graph_enabled
from app.logging_config import (
    get_logger,
    new_request_id,
    request_context,
)
from app.rag import answer_question, prepare_rag_input


app = FastAPI(
    title="Airline Review RAG API",
    version="0.2.0",
)
logger = get_logger(__name__)


@app.middleware("http")
async def log_http_request(request: Request, call_next):
    """Log safe HTTP metadata and attach a correlation ID to the response."""
    supplied_request_id = request.headers.get("X-Request-ID", "")
    if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", supplied_request_id):
        request_id = supplied_request_id
    else:
        request_id = new_request_id()
    started_at = time.perf_counter()

    with request_context(request_id):
        logger.info(
            "event=http_request_started method=%s path=%s",
            request.method,
            request.url.path,
        )
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round(
                (time.perf_counter() - started_at) * 1000,
                2,
            )
            logger.error(
                "event=http_request_failed method=%s path=%s duration_ms=%s "
                "error_type=%s",
                request.method,
                request.url.path,
                duration_ms,
                type(exc).__name__,
            )
            raise

        duration_ms = round(
            (time.perf_counter() - started_at) * 1000,
            2,
        )
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "event=http_request_completed method=%s path=%s "
            "status_code=%s duration_ms=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


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
    return {
        "status": "ok",
        "neo4j_enabled": graph_enabled(),
    }


@app.get("/graph/airlines/{airline_name}")
def graph_airline_overview(airline_name: str) -> dict:
    """Return Neo4j relationship statistics for one airline."""
    if not graph_enabled():
        raise HTTPException(
            status_code=503,
            detail="Neo4j graph integration is disabled.",
        )
    try:
        result = get_airline_graph_overview(airline_name)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"No graph data found for {airline_name!r}.",
            )
        return result
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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
