"""API-клиенты внешних источников курсов с единым интерфейсом fetch_rates().

Каждый клиент возвращает курсы в стандартизированном виде
{"BTC_USD": 59337.21, "EUR_USD": 1.0786, ...}: сколько единиц базовой
валюты (USD) стоит одна единица валюты.
"""

import time
from abc import ABC, abstractmethod
from typing import Any

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import make_pair_key
from valutatrade_hub.parser_service.config import ParserConfig

HTTP_OK = 200
HTTP_ERROR_MESSAGES: dict[int, str] = {
    400: "некорректный запрос (400 Bad Request)",
    401: "неверный или отсутствующий API-ключ (401 Unauthorized)",
    403: "доступ запрещён: проверьте API-ключ и тариф (403 Forbidden)",
    404: "ресурс не найден (404 Not Found)",
    429: "превышен лимит запросов, повторите позже (429 Too Many Requests)",
}
SERVER_ERROR_MIN = 500
MS_IN_SECOND = 1000


class BaseApiClient(ABC):
    """Базовый клиент внешнего API курсов.

    Attributes:
        config: Конфигурация Parser Service.
        source_name: Имя источника для логов и метаданных.
        source_key: Короткий ключ источника для CLI-опции --source.
        last_meta: Метаданные последнего запроса по каждой паре
            ({"BTC_USD": {"raw_id": ..., "request_ms": ..., ...}}).
    """

    source_name: str = "Unknown"
    source_key: str = "unknown"

    def __init__(self, config: ParserConfig) -> None:
        """Сохраняет конфигурацию клиента."""
        self.config = config
        self.last_meta: dict[str, dict[str, Any]] = {}

    @abstractmethod
    def fetch_rates(self) -> dict[str, float]:
        """Запрашивает курсы и возвращает их в виде {"BTC_USD": 59337.21, ...}.

        Raises:
            ApiRequestError: Сетевая ошибка, ошибка API или неверный ответ.
        """

    def _get_json(
        self, url: str, params: dict[str, str] | None = None
    ) -> tuple[Any, dict[str, Any]]:
        """Выполняет GET-запрос и возвращает разобранный JSON и метаданные.

        Args:
            url: Адрес запроса.
            params: Параметры строки запроса.

        Returns:
            Пара (данные JSON, {"request_ms", "status_code", "etag"}).

        Raises:
            ApiRequestError: Таймаут, сетевая ошибка, HTTP-статус не 200
                или тело ответа не JSON.
        """
        started = time.perf_counter()
        try:
            response = requests.get(
                url, params=params, timeout=self.config.REQUEST_TIMEOUT
            )
        except requests.exceptions.Timeout:
            raise ApiRequestError(
                f"{self.source_name}: превышен таймаут {self.config.REQUEST_TIMEOUT} с"
            ) from None
        except requests.exceptions.ConnectionError:
            raise ApiRequestError(
                f"{self.source_name}: нет соединения с сервером (проверьте сеть)"
            ) from None
        except requests.exceptions.RequestException as error:
            # Текст исключения не выводим: в нём может оказаться URL с API-ключом.
            raise ApiRequestError(
                f"{self.source_name}: сетевая ошибка ({type(error).__name__})"
            ) from None

        meta = {
            "request_ms": int((time.perf_counter() - started) * MS_IN_SECOND),
            "status_code": response.status_code,
            "etag": response.headers.get("ETag"),
        }
        if response.status_code != HTTP_OK:
            details = self._describe_status(response.status_code)
            api_error = self._extract_api_error(response)
            if api_error:
                details = f"{details}, ответ API: {api_error}"
            raise ApiRequestError(f"{self.source_name}: {details}")
        try:
            return response.json(), meta
        except ValueError:
            raise ApiRequestError(
                f"{self.source_name}: ответ не является корректным JSON"
            ) from None

    @staticmethod
    def _describe_status(status_code: int) -> str:
        """Возвращает понятное описание HTTP-статуса ошибки."""
        if status_code in HTTP_ERROR_MESSAGES:
            return HTTP_ERROR_MESSAGES[status_code]
        if status_code >= SERVER_ERROR_MIN:
            return f"сервер недоступен ({status_code})"
        return f"неожиданный HTTP-статус {status_code}"

    @staticmethod
    def _extract_api_error(response: requests.Response) -> str | None:
        """Достаёт код ошибки из JSON-тела ответа ("error-type"/"error"), если есть."""
        try:
            body = response.json()
        except ValueError:
            return None
        if not isinstance(body, dict):
            return None
        error = body.get("error-type") or body.get("error")
        return str(error) if error else None

    @staticmethod
    def _to_positive_float(value: Any) -> float | None:
        """Возвращает value как положительный float или None при неверном типе."""
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return float(value) if value > 0 else None


class CoinGeckoClient(BaseApiClient):
    """Клиент CoinGecko: курсы криптовалют к базовой валюте."""

    source_name = "CoinGecko"
    source_key = "coingecko"

    def fetch_rates(self) -> dict[str, float]:
        """Запрашивает курсы CRYPTO_CURRENCIES через их ID из CRYPTO_ID_MAP.

        Raises:
            ApiRequestError: Ошибка сети/API или в ответе нет ни одного курса.
        """
        base = self.config.BASE_CURRENCY
        id_to_code = {
            self.config.CRYPTO_ID_MAP[code]: code
            for code in self.config.CRYPTO_CURRENCIES
            if code in self.config.CRYPTO_ID_MAP
        }
        params = {"ids": ",".join(id_to_code), "vs_currencies": base.lower()}
        data, meta = self._get_json(self.config.COINGECKO_URL, params)
        if not isinstance(data, dict):
            raise ApiRequestError(f"{self.source_name}: неожиданный формат ответа")

        rates: dict[str, float] = {}
        self.last_meta = {}
        for raw_id, code in id_to_code.items():
            entry = data.get(raw_id)
            rate = self._to_positive_float(
                entry.get(base.lower()) if isinstance(entry, dict) else None
            )
            if rate is None:
                continue
            pair = make_pair_key(code, base)
            rates[pair] = rate
            self.last_meta[pair] = {"raw_id": raw_id, **meta}
        if not rates:
            raise ApiRequestError(f"{self.source_name}: в ответе нет курсов")
        return rates


class ExchangeRateApiClient(BaseApiClient):
    """Клиент ExchangeRate-API: курсы фиатных валют к базовой валюте."""

    source_name = "ExchangeRate-API"
    source_key = "exchangerate"

    def fetch_rates(self) -> dict[str, float]:
        """Запрашивает курсы FIAT_CURRENCIES относительно BASE_CURRENCY.

        API отдаёт, сколько единиц валюты стоит 1 USD (USD→EUR = 0.927),
        поэтому курс пары EUR_USD вычисляется как 1 / 0.927.

        Если ключ EXCHANGERATE_API_KEY не задан, запрос идёт на открытый
        эндпоинт EXCHANGERATE_OPEN_URL (тот же формат ответа, без ключа).

        Raises:
            ApiRequestError: Ошибка сети/API (неверный ключ, лимит) или
                неверный ответ.
        """
        api_key = self.config.EXCHANGERATE_API_KEY
        base = self.config.BASE_CURRENCY
        if api_key:
            url = f"{self.config.EXCHANGERATE_API_URL}/{api_key}/latest/{base}"
        else:
            url = f"{self.config.EXCHANGERATE_OPEN_URL}/latest/{base}"
        data, meta = self._get_json(url)
        if not isinstance(data, dict) or data.get("result") != "success":
            error_type = data.get("error-type") if isinstance(data, dict) else None
            raise ApiRequestError(
                f"{self.source_name}: API вернул ошибку ({error_type or 'unknown'})"
            )
        raw_rates = data.get("rates")
        if not isinstance(raw_rates, dict):
            raise ApiRequestError(f"{self.source_name}: в ответе нет поля 'rates'")

        rates: dict[str, float] = {}
        self.last_meta = {}
        for code in self.config.FIAT_CURRENCIES:
            per_base = self._to_positive_float(raw_rates.get(code))
            if per_base is None:
                continue
            pair = make_pair_key(code, base)
            rates[pair] = 1 / per_base
            self.last_meta[pair] = {"raw_id": code, **meta}
        if not rates:
            raise ApiRequestError(f"{self.source_name}: в ответе нет курсов")
        return rates
