"""Иерархия валют: абстрактная Currency и наследники FiatCurrency/CryptoCurrency.

Модуль также содержит реестр поддерживаемых валют и фабрику get_currency().
"""

from abc import ABC, abstractmethod

from valutatrade_hub.core.exceptions import CurrencyNotFoundError

MIN_CODE_LENGTH = 2
MAX_CODE_LENGTH = 5


def _validate_code(code: str) -> str:
    """Проверяет код валюты на соответствие инвариантам.

    Args:
        code: Код валюты (ISO-код или тикер).

    Returns:
        Тот же код, если он корректен.

    Raises:
        ValueError: Код не строка, не в верхнем регистре, содержит пробелы
            или имеет длину вне диапазона 2–5 символов.
    """
    if not isinstance(code, str):
        raise ValueError("Код валюты должен быть строкой")
    if not MIN_CODE_LENGTH <= len(code) <= MAX_CODE_LENGTH:
        raise ValueError(
            f"Код валюты должен содержать от {MIN_CODE_LENGTH} "
            f"до {MAX_CODE_LENGTH} символов"
        )
    if " " in code or not code.isupper():
        raise ValueError("Код валюты должен быть в верхнем регистре и без пробелов")
    return code


class Currency(ABC):
    """Абстрактная валюта с человекочитаемым именем и кодом.

    Attributes:
        name: Человекочитаемое имя ("US Dollar", "Bitcoin").
        code: ISO-код или тикер ("USD", "BTC"): верхний регистр, 2–5 символов.
    """

    def __init__(self, name: str, code: str) -> None:
        """Создаёт валюту, проверяя имя и код.

        Args:
            name: Непустое имя валюты.
            code: Код валюты.

        Raises:
            ValueError: Имя пустое или код некорректен.
        """
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Имя валюты не может быть пустым")
        self.name = name
        self.code = _validate_code(code)

    @abstractmethod
    def get_display_info(self) -> str:
        """Возвращает строковое представление валюты для UI и логов."""

    def __repr__(self) -> str:
        """Возвращает отладочное представление валюты."""
        return f"{type(self).__name__}(code={self.code!r}, name={self.name!r})"


class FiatCurrency(Currency):
    """Фиатная валюта, выпускаемая государством или валютной зоной.

    Attributes:
        issuing_country: Страна или зона эмиссии ("United States", "Eurozone").
    """

    def __init__(self, name: str, code: str, issuing_country: str) -> None:
        """Создаёт фиатную валюту.

        Args:
            name: Имя валюты.
            code: Код валюты.
            issuing_country: Страна/зона эмиссии.
        """
        super().__init__(name, code)
        self.issuing_country = issuing_country

    def get_display_info(self) -> str:
        """Возвращает строку вида "[FIAT] USD — US Dollar (Issuing: ...)"."""
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


class CryptoCurrency(Currency):
    """Криптовалюта с алгоритмом консенсуса и рыночной капитализацией.

    Attributes:
        algorithm: Алгоритм ("SHA-256", "Ethash").
        market_cap: Последняя известная капитализация в USD.
    """

    def __init__(self, name: str, code: str, algorithm: str, market_cap: float) -> None:
        """Создаёт криптовалюту.

        Args:
            name: Имя валюты.
            code: Тикер валюты.
            algorithm: Алгоритм консенсуса/хеширования.
            market_cap: Рыночная капитализация.
        """
        super().__init__(name, code)
        self.algorithm = algorithm
        self.market_cap = float(market_cap)

    def get_display_info(self) -> str:
        """Возвращает строку вида "[CRYPTO] BTC — Bitcoin (Algo: ..., MCAP: ...)"."""
        mantissa, exponent = f"{self.market_cap:.2e}".split("e")
        mcap = f"{mantissa}e{int(exponent)}"
        return (
            f"[CRYPTO] {self.code} — {self.name} (Algo: {self.algorithm}, MCAP: {mcap})"
        )


_CURRENCY_REGISTRY: dict[str, Currency] = {
    currency.code: currency
    for currency in (
        FiatCurrency("US Dollar", "USD", "United States"),
        FiatCurrency("Euro", "EUR", "Eurozone"),
        FiatCurrency("British Pound", "GBP", "United Kingdom"),
        FiatCurrency("Russian Ruble", "RUB", "Russia"),
        FiatCurrency("Japanese Yen", "JPY", "Japan"),
        FiatCurrency("Chinese Yuan", "CNY", "China"),
        FiatCurrency("Swiss Franc", "CHF", "Switzerland"),
        CryptoCurrency("Bitcoin", "BTC", "SHA-256", 1.12e12),
        CryptoCurrency("Ethereum", "ETH", "Ethash", 4.5e11),
        CryptoCurrency("Solana", "SOL", "Proof of History", 6.5e10),
    )
}


def get_currency(code: str) -> Currency:
    """Возвращает валюту из реестра по её коду.

    Args:
        code: Код валюты; регистр и пробелы по краям не важны.

    Returns:
        Объект Currency (FiatCurrency или CryptoCurrency).

    Raises:
        CurrencyNotFoundError: Код отсутствует в реестре.
    """
    normalized = code.strip().upper() if isinstance(code, str) else ""
    currency = _CURRENCY_REGISTRY.get(normalized)
    if currency is None:
        raise CurrencyNotFoundError(code)
    return currency


def get_supported_codes() -> list[str]:
    """Возвращает отсортированный список кодов всех поддерживаемых валют."""
    return sorted(_CURRENCY_REGISTRY)


def is_crypto(code: str) -> bool:
    """Проверяет, является ли валюта с данным кодом криптовалютой.

    Args:
        code: Код валюты из реестра.

    Raises:
        CurrencyNotFoundError: Код отсутствует в реестре.
    """
    return isinstance(get_currency(code), CryptoCurrency)
