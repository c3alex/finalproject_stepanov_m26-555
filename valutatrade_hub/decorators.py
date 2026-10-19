"""Декоратор @log_action для трассировки доменных операций.

Поля записи: timestamp (ставит форматтер), action, user (username или
user_id), currency, amount, rate, base, result (OK/ERROR), а при ошибке —
error_type и error_message. При verbose=True добавляется состояние
кошелька «было→стало».
"""

import functools
import inspect
import logging
from collections.abc import Callable
from typing import Any

from valutatrade_hub.core.utils import format_rate
from valutatrade_hub.logging_config import ACTIONS_LOGGER_NAME

RESULT_OK = "OK"
RESULT_ERROR = "ERROR"
SMALL_FLOAT_THRESHOLD = 0.01
# Поля со значениями-«метками», которые пишутся без кавычек: result=OK
UNQUOTED_FIELDS = ("result", "error_type")


def _format_value(key: str, value: Any) -> str:
    """Форматирует значение поля лога.

    Строки — в кавычках (кроме UNQUOTED_FIELDS), курс — через format_rate(),
    остальные float — 4 знака (8 для очень малых значений).
    """
    if key in UNQUOTED_FIELDS:
        return str(value)
    if isinstance(value, str):
        return f"'{value}'"
    if isinstance(value, float):
        if key == "rate":
            return format_rate(value)
        decimals = 4 if abs(value) >= SMALL_FLOAT_THRESHOLD or value == 0 else 8
        return f"{value:.{decimals}f}"
    return str(value)


def _collect_context(
    signature: inspect.Signature, args: tuple, kwargs: dict
) -> dict[str, Any]:
    """Извлекает из аргументов вызова поля для лога."""
    try:
        bound = signature.bind_partial(*args, **kwargs)
    except TypeError:
        return {}
    arguments = bound.arguments
    context: dict[str, Any] = {}
    user = arguments.get("username", arguments.get("user_id"))
    if user is not None:
        context["user"] = user
    if "currency_code" in arguments:
        context["currency"] = str(arguments["currency_code"]).upper()
    if "amount" in arguments:
        context["amount"] = _as_number(arguments["amount"])
    return context


def _as_number(value: Any) -> Any:
    """Пытается привести значение (например, строку из CLI) к float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _enrich_from_result(context: dict[str, Any], result: Any, verbose: bool) -> None:
    """Дополняет контекст данными из результата операции (если это dict)."""
    if not isinstance(result, dict):
        return
    if "username" in result:
        context["user"] = result["username"]
    for key in ("currency", "amount", "rate", "base"):
        if result.get(key) is not None:
            context[key] = result[key]
    if verbose and "old_balance" in result and "new_balance" in result:
        context["wallet"] = f"{result['old_balance']:.4f}->{result['new_balance']:.4f}"


def log_action(
    action: str, verbose: bool = False
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Создаёт декоратор, логирующий вызов операции на уровне INFO.

    Декоратор не глотает исключения: ошибка записывается в лог с result=ERROR
    и пробрасывается дальше.

    Args:
        action: Имя операции в логе (BUY, SELL, REGISTER, LOGIN, ...).
        verbose: Добавлять ли в лог состояние кошелька «было→стало».

    Returns:
        Декоратор для функции usecase.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            logger = logging.getLogger(ACTIONS_LOGGER_NAME)
            context = _collect_context(signature, args, kwargs)
            try:
                result = func(*args, **kwargs)
            except Exception as error:
                context["result"] = RESULT_ERROR
                context["error_type"] = type(error).__name__
                context["error_message"] = str(error)
                _write(logger, action, context)
                raise
            _enrich_from_result(context, result, verbose)
            context["result"] = RESULT_OK
            _write(logger, action, context)
            return result

        return wrapper

    return decorator


def _write(logger: logging.Logger, action: str, context: dict[str, Any]) -> None:
    """Пишет запись вида "BUY user='alice' currency='BTC' ... result=OK"."""
    fields = " ".join(
        f"{key}={_format_value(key, val)}" for key, val in context.items()
    )
    logger.info(
        "%s %s", action, fields, extra={"action_data": {"action": action, **context}}
    )
