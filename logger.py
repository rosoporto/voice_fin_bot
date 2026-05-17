import logging
import sys
from pathlib import Path

from loguru import logger


class _InterceptHandler(logging.Handler):
    """Redirect standard logging (aiogram, httpx, …) into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code is logging.currentframe().f_code:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging(level: str, log_file: Path) -> "logger":
    log_file.parent.mkdir(parents=True, exist_ok=True)

    fmt = "{time:YYYY-MM-DD HH:mm:ss,SSS} {level} {name}: {message}"

    logger.remove()
    logger.add(sys.stdout, format=fmt, level=level.upper())
    logger.add(
        log_file,
        format=fmt,
        level=level.upper(),
        rotation="5 MB",
        retention=5,
        encoding="utf-8",
    )

    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)

    return logger
