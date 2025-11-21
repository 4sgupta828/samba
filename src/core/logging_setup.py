"""
Logging setup module for the Cloud Infrastructure Simulator.

Provides structured logging with JSON formatting and proper log levels.
"""
import logging
import json
import sys
import os
from pathlib import Path
from typing import Dict, Any, Optional


class JSONFormatter(logging.Formatter):
    """Custom formatter that outputs logs as JSON for easier parsing."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields if present
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)

        return json.dumps(log_data)


def setup_logging(log_level: str = "INFO", use_json: bool = False, log_file: str = None) -> None:
    """
    Set up logging for the entire application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        use_json: If True, use JSON formatting; otherwise use standard formatting
        log_file: Path to log file. If None, defaults to 'logs/simulator.log'
                  Set to False to disable file logging (console only)
    """
    # Get root logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Set formatter
    if use_json:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Create file handler (unless explicitly disabled with log_file=False)
    if log_file is not False:
        if log_file is None:
            log_file = "logs/simulator.log"

        # Ensure log directory exists
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, mode='a')
        file_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the specified name.

    Args:
        name: The name of the logger (typically __name__)

    Returns:
        A configured logger instance
    """
    return logging.getLogger(name)


class SimulationLoggerAdapter(logging.LoggerAdapter):
    """
    Logger adapter that adds simulation time and component context to log messages.
    """

    def __init__(self, logger: logging.Logger, sim_time_func=None, component_id: str = None):
        """
        Initialize the adapter.

        Args:
            logger: Base logger instance
            sim_time_func: Function that returns current simulation time
            component_id: ID of the component this logger is for
        """
        super().__init__(logger, {})
        self.sim_time_func = sim_time_func
        self.component_id = component_id

    def process(self, msg, kwargs):
        """Add simulation context to log messages."""
        extra = kwargs.get("extra", {})

        # Add simulation time if available
        if self.sim_time_func:
            extra["sim_time"] = f"{self.sim_time_func():.2f}s"

        # Add component ID if available
        if self.component_id:
            extra["component_id"] = self.component_id

        kwargs["extra"] = {"extra_fields": extra}
        return msg, kwargs
