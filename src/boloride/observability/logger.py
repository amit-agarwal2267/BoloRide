import json
import logging
from datetime import UTC, datetime
from typing import Any

from boloride.observability.correlation import get_request_id


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", record.getMessage()),
            "logger": record.name,
        }

        request_id = get_request_id()
        if request_id is not None:
            payload["request_id"] = request_id

        for field in (
            "method",
            "path",
            "status_code",
            "duration_ms",
            "query_length",
            "candidate_count",
            "success",
            "error_type",
            "session_id",
            "prompt_name",
            "prompt_label",
            "prompt_source",
            "provider",
            "model",
        ):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True
