"""Centralized, privacy-conscious application logging and call tracing."""

from __future__ import annotations

import contextvars
import inspect
import logging
import os
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar


DEFAULT_LOG_FILE = "logs/airline_app.log"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5
LOGGER_ROOT = "airline"

SENSITIVE_FIELD_MARKERS = (
    "api_key",
    "authorization",
    "content",
    "password",
    "prompt",
    "question",
    "review_text",
    "secret",
    "text",
    "token",
)

request_id_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id",
    default="-",
)

F = TypeVar("F", bound=Callable[..., Any])
_configured = False


class RequestContextFilter(logging.Filter):
    """Attach the current request or session identifier to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_context.get()
        return True


def _read_int(name: str, default: int) -> int:
    """Read a positive integer logging setting with a safe fallback."""
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _safe_value(name: str, value: Any) -> str:
    """Format metadata while redacting fields likely to contain user data."""
    lowered_name = name.casefold()
    if any(marker in lowered_name for marker in SENSITIVE_FIELD_MARKERS):
        return "<redacted>"

    rendered = str(value).replace("\n", "\\n")
    if len(rendered) > 500:
        return rendered[:497] + "..."
    return rendered


def format_fields(**fields: Any) -> str:
    """Return stable key-value log fields with automatic redaction."""
    return " ".join(
        f"{name}={_safe_value(name, fields[name])}"
        for name in sorted(fields)
        if fields[name] is not None
    )


def configure_logging() -> logging.Logger:
    """Configure console and rotating-file handlers once per process."""
    global _configured

    root_logger = logging.getLogger(LOGGER_ROOT)
    if _configured:
        return root_logger

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root_logger.setLevel(level)
    root_logger.propagate = False

    log_filter = RequestContextFilter()
    formatter = logging.Formatter(
        fmt=(
            "%(asctime)s %(levelname)s request_id=%(request_id)s "
            "logger=%(name)s %(message)s"
        ),
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.addFilter(log_filter)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    log_path = Path(os.getenv("LOG_FILE", DEFAULT_LOG_FILE)).expanduser()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=_read_int("LOG_MAX_BYTES", DEFAULT_MAX_BYTES),
            backupCount=_read_int(
                "LOG_BACKUP_COUNT",
                DEFAULT_BACKUP_COUNT,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        root_logger.warning(
            "event=file_logging_unavailable log_file=%s error_type=%s",
            log_path,
            type(exc).__name__,
        )
    else:
        file_handler.setLevel(level)
        file_handler.addFilter(log_filter)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    _configured = True
    root_logger.info(
        "event=logging_configured %s",
        format_fields(level=logging.getLevelName(level), log_file=log_path),
    )
    return root_logger


def get_logger(module_name: str) -> logging.Logger:
    """Return a configured child logger for an application module."""
    configure_logging()
    clean_name = module_name.removeprefix("app.")
    return logging.getLogger(f"{LOGGER_ROOT}.{clean_name}")


def new_request_id(prefix: str = "req") -> str:
    """Create a short identifier for correlating related log messages."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def set_request_id(request_id: str) -> contextvars.Token[str]:
    """Set the request identifier in the current execution context."""
    return request_id_context.set(request_id)


@contextmanager
def request_context(request_id: str) -> Iterator[None]:
    """Temporarily associate log messages with a request identifier."""
    token = set_request_id(request_id)
    try:
        yield
    finally:
        request_id_context.reset(token)


@contextmanager
def tracked_operation(
    logger: logging.Logger,
    operation: str,
    level: int = logging.INFO,
    **fields: Any,
) -> Iterator[None]:
    """Log the start, duration, success, and failure of an operation."""
    started_at = time.perf_counter()
    metadata = format_fields(operation=operation, **fields)
    logger.log(level, "event=operation_started %s", metadata)

    try:
        yield
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        # Exception strings from SDKs and database drivers can contain request
        # payloads or SQL parameters. Record the type, but never serialize the
        # exception or traceback into the persistent application log.
        logger.error(
            "event=operation_failed %s",
            format_fields(
                operation=operation,
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
                **fields,
            ),
        )
        raise
    else:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.log(
            level,
            "event=operation_completed %s",
            format_fields(
                operation=operation,
                duration_ms=duration_ms,
                **fields,
            ),
        )


def track_call(func: F) -> F:
    """Trace a function call without logging its arguments or return value."""
    return _decorate_call(func, logging.INFO)


def track_call_debug(func: F) -> F:
    """Trace a high-frequency function call at DEBUG level."""
    return _decorate_call(func, logging.DEBUG)


def _decorate_call(func: F, level: int) -> F:
    """Build a call-tracing decorator at the requested logging level."""
    logger = get_logger(func.__module__)
    function_name = f"{func.__module__}.{func.__qualname__}"

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        frame = inspect.currentframe()
        caller_frame = frame.f_back if frame else None
        caller_file = (
            Path(caller_frame.f_code.co_filename).name
            if caller_frame
            else "unknown"
        )
        caller_line = caller_frame.f_lineno if caller_frame else 0
        started_at = time.perf_counter()

        logger.log(
            level,
            "event=call_started %s",
            format_fields(
                function=function_name,
                caller=f"{caller_file}:{caller_line}",
            ),
        )

        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            logger.error(
                "event=call_failed %s",
                format_fields(
                    function=function_name,
                    caller=f"{caller_file}:{caller_line}",
                    duration_ms=duration_ms,
                    error_type=type(exc).__name__,
                ),
            )
            raise

        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.log(
            level,
            "event=call_completed %s",
            format_fields(
                function=function_name,
                caller=f"{caller_file}:{caller_line}",
                duration_ms=duration_ms,
            ),
        )
        return result

    return wrapper  # type: ignore[return-value]
