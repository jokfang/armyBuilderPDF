from __future__ import annotations

import logging
from logging import LoggerAdapter
from pathlib import Path


LOGS_DIR = Path("logs")
LOG_FILE_PATH = LOGS_DIR / "execution.log"
MISSING_TRANSLATIONS_LOG_FILE_PATH = LOGS_DIR / "missingTrad.log"


class ScriptLoggerAdapter(LoggerAdapter):
    def process(self, msg: str, kwargs: dict) -> tuple[str, dict]:
        extra = dict(kwargs.get("extra") or {})
        extra.setdefault("script_name", self.extra["script_name"])
        kwargs["extra"] = extra
        return msg, kwargs


class DefaultScriptNameFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "script_name") or not getattr(record, "script_name", None):
            record.script_name = record.name
        return True


def get_or_create_file_logger(logger_name: str, file_path: Path) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    handler_path = str(file_path.resolve())
    existing_handler = next(
        (
            handler
            for handler in logger.handlers
            if isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", None) == handler_path
        ),
        None,
    )

    if existing_handler is None:
        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        file_handler.addFilter(DefaultScriptNameFilter())
        logger.addHandler(file_handler)

    return logger


def setup_script_logging(script_name: str) -> ScriptLoggerAdapter:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    handler_path = str(LOG_FILE_PATH.resolve())
    existing_handler = next(
        (
            handler
            for handler in root_logger.handlers
            if isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", None) == handler_path
        ),
        None,
    )

    if existing_handler is None:
        file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] [%(script_name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        file_handler.addFilter(DefaultScriptNameFilter())
        root_logger.addHandler(file_handler)

    return ScriptLoggerAdapter(logging.getLogger(script_name), {"script_name": script_name})
