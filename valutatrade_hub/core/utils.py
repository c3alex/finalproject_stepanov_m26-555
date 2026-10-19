"""Вспомогательные функции ядра: валидация, конвертация, время и форматирование."""

from datetime import UTC, datetime

from valutatrade_hub.core.currencies import get_currency, is_crypto
from valutatrade_hub.core.exceptions import RateUnavailableError

PAIR_SEPARATOR = "_"
BASE_CURRENCY = "USD"
FIAT_DECIMALS = 2
CRYPTO_DECIMALS = 4
RATE_DECIMALS_SMALL = 8
RATE_DECIMALS_MEDIUM = 4
RATE_DECIMALS_LARGE = 2
LARGE_RATE_THRESHOLD = 1000


def validate_currency_code(code: str) -> str:
    """Нормализует и проверяет код валюты по реестру.

    Args:
        code: Код валюты от пользователя (регистр не важен).

    Returns:
        Код валюты в верхнем регистре.

    Raises:
        ValueError: Код пустой или не строка.
        CurrencyNotFoundError: Код отсутствует в реестре валют.
    """
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Код валюты не может быть пустым")
    return get_currency(code).code


def validate_amount(amount: float | int | str) -> float:
    """Проверяет, что сумма — положительное число.

    Args:
        amount: Сумма (число или строка с числом).

    Returns:
        Сумма в виде float.

    Raises:
        ValueError: Сумма не число, не конечна или не больше нуля.
    """
    if isinstance(amount, bool):
        raise ValueError("'amount' должен быть положительным числом")
    try:
        value = float(amount)
    except (TypeError, ValueError):
        raise ValueError("'amount' должен быть положительным числом") from None
    if value != value or value in (float("inf"), float("-inf")) or value <= 0:
        raise ValueError("'amount' должен быть положительным числом")
    return value


def make_pair_key(from_code: str, to_code: str) -> str:
    """Возвращает ключ валютной пары вида "BTC_USD"."""
    return f"{from_code}{PAIR_SEPARATOR}{to_code}"


def split_pair_key(pair_key: str) -> tuple[str, str]:
    """Разбирает ключ пары "BTC_USD" на ("BTC", "USD")."""
    from_code, to_code = pair_key.split(PAIR_SEPARATOR, 1)
    return from_code, to_code


def convert_amount(
    amount: float, from_code: str, to_code: str, rates_to_usd: dict[str, float]
) -> float:
    """Конвертирует сумму между валютами через кросс-курс к USD.

    Args:
        amount: Сумма в валюте from_code.
        from_code: Исходная валюта.
        to_code: Целевая валюта.
        rates_to_usd: Словарь {"EUR_USD": 1.08, ...}: сколько USD стоит
            единица валюты. Курс USD_USD считается равным 1.

    Returns:
        Сумма в валюте to_code.

    Raises:
        RateUnavailableError: Для одной из валют нет курса к USD.
    """
    return amount * cross_rate(from_code, to_code, rates_to_usd)


def cross_rate(from_code: str, to_code: str, rates_to_usd: dict[str, float]) -> float:
    """Вычисляет курс from_code→to_code через курсы обеих валют к USD.

    Args:
        from_code: Исходная валюта.
        to_code: Целевая валюта.
        rates_to_usd: Словарь курсов вида {"BTC_USD": 59337.21, ...}.

    Returns:
        Сколько единиц to_code стоит одна единица from_code.

    Raises:
        RateUnavailableError: Для одной из валют нет курса к USD.
    """
    if from_code == to_code:
        return 1.0
    from_usd = _rate_to_usd(from_code, rates_to_usd)
    to_usd = _rate_to_usd(to_code, rates_to_usd)
    if from_usd is None or to_usd is None or to_usd == 0:
        raise RateUnavailableError(from_code, to_code)
    return from_usd / to_usd


def _rate_to_usd(code: str, rates_to_usd: dict[str, float]) -> float | None:
    """Возвращает курс валюты к USD или None, если курса нет."""
    if code == BASE_CURRENCY:
        return 1.0
    return rates_to_usd.get(make_pair_key(code, BASE_CURRENCY))


def utc_now_iso() -> str:
    """Возвращает текущее время UTC в ISO-формате с суффиксом Z (без микросекунд)."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def local_now_iso() -> str:
    """Возвращает текущее локальное время в ISO-формате (без микросекунд)."""
    return datetime.now().replace(microsecond=0).isoformat()


def parse_iso(timestamp: str) -> datetime:
    """Разбирает ISO-строку в datetime с часовым поясом.

    Строки без часового пояса считаются UTC.

    Args:
        timestamp: Строка ISO 8601, например "2025-10-10T12:00:00Z".

    Raises:
        ValueError: Строка не является корректной ISO-датой.
    """
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def is_fresh(timestamp: str | None, ttl_seconds: int) -> bool:
    """Проверяет, что метка времени моложе TTL.

    Args:
        timestamp: ISO-метка времени или None.
        ttl_seconds: Допустимый возраст данных в секундах.

    Returns:
        True, если метка корректна и данные не старше ttl_seconds.
    """
    if not timestamp:
        return False
    try:
        age = datetime.now(UTC) - parse_iso(timestamp)
    except ValueError:
        return False
    return age.total_seconds() <= ttl_seconds


def format_timestamp(timestamp: str) -> str:
    """Преобразует ISO-метку в вид "2025-10-09 00:03:22" (локальное время)."""
    try:
        return parse_iso(timestamp).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return timestamp


def format_amount(amount: float, code: str) -> str:
    """Форматирует количество валюты: 4 знака для крипты, 2 — для фиата."""
    decimals = CRYPTO_DECIMALS if is_crypto(code) else FIAT_DECIMALS
    return f"{amount:.{decimals}f}"


def format_money(value: float) -> str:
    """Форматирует денежную сумму с разделителем тысяч: 3,329.00."""
    return f"{value:,.2f}"


def format_rate(rate: float) -> str:
    """Форматирует курс: 2 знака для курсов ≥ 1000, 4 — для курсов ≥ 1,
    до 8 значащих знаков после запятой — для малых курсов."""
    if rate >= LARGE_RATE_THRESHOLD:
        return f"{rate:.{RATE_DECIMALS_LARGE}f}"
    if rate >= 1:
        return f"{rate:.{RATE_DECIMALS_MEDIUM}f}"
    formatted = f"{rate:.{RATE_DECIMALS_SMALL}f}".rstrip("0")
    return formatted if not formatted.endswith(".") else formatted + "0"
