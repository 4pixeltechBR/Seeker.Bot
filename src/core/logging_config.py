"""
Seeker.Bot — Structured Logging Configuration
src/core/logging_config.py

Padroniza prefixos de logs e garante exc_info=True em todos os log.error().
"""

import logging
import sys


class StructuredFormatter(logging.Formatter):
    """Formatter que garante prefixo consistente [module.submodule]."""

    GRAY = "\x1b[38;21m"
    BLUE = "\x1b[38;5;39m"
    YELLOW = "\x1b[38;5;226m"
    RED = "\x1b[38;5;196m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"

    FORMATS = {
        logging.DEBUG: GRAY + "[%(name)s] %(message)s" + RESET,
        logging.INFO: BLUE + "[%(name)s] %(message)s" + RESET,
        logging.WARNING: YELLOW + "[%(name)s] %(message)s" + RESET,
        logging.ERROR: RED + "[%(name)s] %(message)s" + RESET,
        logging.CRITICAL: BOLD_RED + "[%(name)s] %(message)s" + RESET,
    }

    def format(self, record):
        """Format log record with color and prefixed module name."""
        # Garante que logger name tem formato seeker.module.submodule
        if not record.name.startswith("seeker."):
            record.name = f"seeker.{record.name}"

        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        result = formatter.format(record)

        # Se for erro, adiciona exc_info
        if record.exc_info:
            result += "\n" + self.formatException(record.exc_info)

        return result


def configure_logging(level=logging.INFO):
    """Configure structured logging para todo o Seeker.Bot."""
    # Remove handlers existentes
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Handler para stdout
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(StructuredFormatter())

    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    # Silencia loggers barulhentos
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return root_logger


# Export função de uso prático
def get_logger(name):
    """Get logger com prefixo seeker padronizado."""
    if not name.startswith("seeker."):
        name = f"seeker.{name}"
    return logging.getLogger(name)
