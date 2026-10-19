"""Настройка логирования: формат, уровень и ротация файлов.

Выбранный формат по умолчанию — человекочитаемая строка:
    INFO 2025-10-09T12:05:22 BUY user='alice' currency='BTC' amount=0.0500 ...
Формат JSON включается настройкой log_format = "json" в [tool.valutatrade].

Логгеры:
    valutatrade.actions — доменные операции (logs/actions.log);
    valutatrade.parser  — Parser Service (logs/parser.log + вывод в консоль).
Ротация: RotatingFileHandler по размеру (log_max_bytes, log_backup_count).
Уровень по умолчанию — INFO (для отладки задайте log_level = "DEBUG").
"""

import json
import logging
import sys
from logging.handlers import RotatingFileHandler

from valutatrade_hub.infra.settings import SettingsLoader

ACTIONS_LOGGER_NAME = "valutatrade.actions"
PARSER_LOGGER_NAME = "valutatrade.parser"
ACTIONS_LOG_FILE = "actions.log"
PARSER_LOG_FILE = "parser.log"

TEXT_FORMAT = "%(levelname)s %(asctime)s %(message)s"
CONSOLE_FORMAT = "%(levelname)s: %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

_configured = False


class JsonFormatter(logging.Formatter):
    """Форматтер, сериализующий запись лога в одну JSON-строку."""

    def format(self, record: logging.LogRecord) -> str:
        """Возвращает запись в виде JSON с полями timestamp/level/message."""
        payload = {
            "timestamp": self.formatTime(record, DATE_FORMAT),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(getattr(record, "action_data", {}))
        return json.dumps(payload, ensure_ascii=False)


def _make_file_handler(filename: str, settings: SettingsLoader) -> logging.Handler:
    """Создаёт RotatingFileHandler в каталоге логов с выбранным форматом."""
    log_dir = settings.get("log_dir")
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / filename,
        maxBytes=int(settings.get("log_max_bytes")),
        backupCount=int(settings.get("log_backup_count")),
        encoding="utf-8",
    )
    if str(settings.get("log_format")).lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(TEXT_FORMAT, DATE_FORMAT))
    return handler


def setup_logging() -> None:
    """Настраивает логгеры приложения (повторные вызовы ничего не делают).

    Побочные эффекты: создаёт каталог логов и добавляет обработчики
    к логгерам valutatrade.actions и valutatrade.parser.
    """
    global _configured
    if _configured:
        return
    settings = SettingsLoader()
    level = getattr(logging, str(settings.get("log_level")).upper(), logging.INFO)

    actions_logger = logging.getLogger(ACTIONS_LOGGER_NAME)
    actions_logger.setLevel(level)
    actions_logger.propagate = False
    actions_logger.addHandler(_make_file_handler(ACTIONS_LOG_FILE, settings))

    parser_logger = logging.getLogger(PARSER_LOGGER_NAME)
    parser_logger.setLevel(level)
    parser_logger.propagate = False
    parser_logger.addHandler(_make_file_handler(PARSER_LOG_FILE, settings))
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    parser_logger.addHandler(console)

    _configured = True
