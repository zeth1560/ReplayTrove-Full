"""Deprecated module path; use replaytrove_logging.service_handler."""

from replaytrove_logging.service_handler import DailyJsonlFileHandler, ServiceJsonlFileHandler

__all__ = ["DailyJsonlFileHandler", "ServiceJsonlFileHandler"]
