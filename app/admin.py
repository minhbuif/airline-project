"""Bounded, read-only inspection helpers for the admin dashboard."""

import hmac
import os
import re
from pathlib import Path

from app.config import settings
from app.logging_config import DEFAULT_LOG_FILE


HEADER = re.compile(
    r"^(?P<time>\S+) (?P<level>[A-Z]+) request_id=(?P<request_id>\S+) "
    r"logger=(?P<logger>\S+) (?P<message>.*)$"
)
FIELDS = re.compile(r"(?:^|\s)([a-z_]+)=([^\s]+)")


def check_password(candidate: str) -> bool:
    """Fail closed when the administrator has not configured a password."""
    return bool(settings.ADMIN_PASSWORD) and hmac.compare_digest(
        candidate.encode(), settings.ADMIN_PASSWORD.encode()
    )


def redact(value: str) -> str:
    """Mask known credentials and common secret fields before display/export."""
    for name in ("GEMINI_API_KEY", "FIRECRAWL_API_KEY", "POSTGRES_PASSWORD",
                 "NEO4J_PASSWORD", "ADMIN_PASSWORD"):
        secret = getattr(settings, name, "")
        if secret:
            value = value.replace(secret, "<redacted>")
    value = re.sub(
        r"(?i)((?:api_key|password|secret|token|authorization)\s*[=:]\s*)"
        r"(?:Bearer\s+)?[^\s,;]+", r"\1<redacted>", value,
    )
    return re.sub(r"(\w+://)[^/@\s]+:[^/@\s]+@", r"\1<redacted>@", value)


def read_logs(max_lines: int = 2000) -> tuple[list[dict], str]:
    """Read at most 1 MiB of the configured current log, never arbitrary files."""
    path = Path(os.getenv("LOG_FILE", DEFAULT_LOG_FILE)).expanduser()
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            offset = max(0, size - 1024 * 1024)
            handle.seek(offset)
            if offset:
                handle.readline()  # Drop a partial first line.
            lines = handle.read(1024 * 1024).decode("utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return [], "No log file yet. Run a question, crawl, or ingestion to generate activity."
    except OSError:
        return [], "The configured log file cannot be read. Check LOG_FILE and file permissions."
    rows = []
    for line in lines[-max(1, min(max_lines, 5000)):]:
        line = redact(line)
        match = HEADER.match(line)
        if not match:
            continue
        row = match.groupdict()
        fields = dict(FIELDS.findall(row["message"]))
        row.update({key: fields.get(key, "") for key in
                    ("event", "operation", "function", "caller", "duration_ms", "error_type")})
        row["raw"] = line
        rows.append(row)
    return rows, ""


def task_activity(rows: list[dict]) -> list[dict]:
    """Pair observed call/operation events without claiming process liveness."""
    tasks = []
    pending: dict[tuple, list[dict]] = {}
    for row in rows:
        event = row["event"]
        if event not in {"call_started", "call_completed", "call_failed",
                         "operation_started", "operation_completed", "operation_failed"}:
            continue
        kind, status = event.split("_", 1)
        name = row["function"] if kind == "call" else row["operation"]
        key = (row["request_id"], row["logger"], kind, name)
        if status == "started":
            task = {"Task": name, "Request ID": row["request_id"],
                    "Started": row["time"], "Last event": row["time"],
                    "Status": "Started; completion not observed", "Duration (ms)": "",
                    "Caller": row["caller"], "Error": ""}
            tasks.append(task)
            pending.setdefault(key, []).append(task)
        else:
            if pending.get(key):
                task = pending[key].pop()
            else:
                task = {"Task": name, "Request ID": row["request_id"],
                        "Started": "Outside log window", "Caller": row["caller"]}
                tasks.append(task)
            task.update({"Last event": row["time"], "Status": status.capitalize(),
                         "Duration (ms)": row["duration_ms"], "Error": row["error_type"]})
    return sorted(tasks, key=lambda task: task["Last event"], reverse=True)


def visible_config() -> dict:
    """Explicit allowlist avoids ever serializing credentials or connection URLs."""
    names = ("GEMINI_MODEL", "QDRANT_HOST", "QDRANT_PORT", "QDRANT_COLLECTION",
             "QDRANT_WEB_COLLECTION", "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB",
             "NEO4J_ENABLED", "NEO4J_DATABASE", "LANDING_PATH")
    result = {name: redact(str(getattr(settings, name))) for name in names}
    for name in ("GEMINI_API_KEY", "FIRECRAWL_API_KEY", "POSTGRES_PASSWORD", "NEO4J_PASSWORD"):
        result[name] = "Configured" if getattr(settings, name) else "Missing"
    result["LOG_FILE"] = redact(os.getenv("LOG_FILE", DEFAULT_LOG_FILE))
    result["LOG_LEVEL"] = os.getenv("LOG_LEVEL", "INFO")
    return result
