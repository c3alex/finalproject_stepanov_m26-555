"""RatesUpdater: координация обновления курсов из всех источников."""

import logging
from dataclasses import dataclass, field
from typing import Any

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import split_pair_key, utc_now_iso
from valutatrade_hub.logging_config import PARSER_LOGGER_NAME, setup_logging
from valutatrade_hub.parser_service.api_clients import (
    BaseApiClient,
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage

logger = logging.getLogger(PARSER_LOGGER_NAME)


@dataclass
class UpdateResult:
    """Итог одного запуска обновления.

    Attributes:
        total: Число записанных в rates.json курсов.
        per_source: Число курсов, полученных от каждого источника.
        errors: Сообщения об ошибках по источникам, которые не ответили.
        last_refresh: Время завершения обновления (ISO UTC).
        history_added: Число новых записей в exchange_rates.json.
    """

    total: int = 0
    per_source: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    last_refresh: str | None = None
    history_added: int = 0

    @property
    def has_errors(self) -> bool:
        """True, если хотя бы один источник завершился ошибкой."""
        return bool(self.errors)


class RatesUpdater:
    """Опрашивает API-клиентов, объединяет курсы и сохраняет их в хранилище."""

    def __init__(
        self,
        clients: list[BaseApiClient] | None = None,
        storage: RatesStorage | None = None,
        config: ParserConfig | None = None,
    ) -> None:
        """Создаёт обновлятор.

        Args:
            clients: API-клиенты; по умолчанию CoinGecko и ExchangeRate-API.
            storage: Хранилище; по умолчанию файлы из конфигурации.
            config: Конфигурация Parser Service.
        """
        setup_logging()
        self.config = config or ParserConfig()
        self.clients = clients or [
            CoinGeckoClient(self.config),
            ExchangeRateApiClient(self.config),
        ]
        self.storage = storage or RatesStorage(
            self.config.RATES_FILE_PATH, self.config.HISTORY_FILE_PATH
        )

    @property
    def source_keys(self) -> list[str]:
        """Ключи доступных источников (для CLI-опции --source)."""
        return [client.source_key for client in self.clients]

    def run_update(self, source: str | None = None) -> UpdateResult:
        """Запускает обновление курсов.

        Падение одного клиента логируется и не останавливает обновление
        по остальным источникам.

        Args:
            source: Ключ источника ("coingecko" или "exchangerate");
                None — опросить все источники.

        Returns:
            UpdateResult с количеством курсов и ошибками по источникам.

        Raises:
            ValueError: Неизвестный ключ источника.
            ApiRequestError: Ни один источник не вернул курсы.
        """
        clients = self._select_clients(source)
        logger.info("Starting rates update...")
        result = UpdateResult()
        pairs: dict[str, dict[str, Any]] = {}
        history: list[dict[str, Any]] = []

        for client in clients:
            try:
                rates = client.fetch_rates()
            except ApiRequestError as error:
                reason = error.reason.removeprefix(f"{client.source_name}: ")
                result.errors[client.source_name] = reason
                logger.error("Failed to fetch from %s: %s", client.source_name, reason)
                continue
            timestamp = utc_now_iso()
            logger.info(
                "Fetching from %s... OK (%d rates)", client.source_name, len(rates)
            )
            result.per_source[client.source_name] = len(rates)
            for pair, rate in rates.items():
                pairs[pair] = {
                    "rate": rate,
                    "updated_at": timestamp,
                    "source": client.source_name,
                }
                history.append(
                    self._history_record(
                        pair,
                        rate,
                        timestamp,
                        client.source_name,
                        client.last_meta.get(pair, {}),
                    )
                )

        if not pairs:
            reasons = "; ".join(result.errors.values()) or "нет источников"
            logger.error("Rates update failed: no data received")
            raise ApiRequestError(
                f"не удалось получить курсы ни из одного источника ({reasons})"
            )

        result.last_refresh = utc_now_iso()
        logger.info("Writing %d rates to %s...", len(pairs), self._display_path())
        self.storage.save_snapshot(pairs, result.last_refresh)
        result.history_added = self.storage.append_history(history)
        result.total = len(pairs)
        logger.debug("History records added: %d", result.history_added)
        logger.info(
            "Update finished: %d rates, errors: %d",
            result.total,
            len(result.errors),
        )
        return result

    def _select_clients(self, source: str | None) -> list[BaseApiClient]:
        """Возвращает клиентов по ключу источника (или всех)."""
        if source is None:
            return list(self.clients)
        key = source.strip().lower()
        selected = [client for client in self.clients if client.source_key == key]
        if not selected:
            available = ", ".join(self.source_keys)
            raise ValueError(f"Неизвестный источник '{source}'. Доступные: {available}")
        return selected

    def _display_path(self) -> str:
        """Возвращает путь к rates.json для логов (относительно data/, если можно)."""
        path = self.storage.rates_path
        return f"{path.parent.name}/{path.name}"

    @staticmethod
    def _history_record(
        pair: str,
        rate: float,
        timestamp: str,
        source: str,
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        """Формирует запись exchange_rates.json с id = <FROM>_<TO>_<timestamp>."""
        from_code, to_code = split_pair_key(pair)
        return {
            "id": f"{pair}_{timestamp}",
            "from_currency": from_code,
            "to_currency": to_code,
            "rate": rate,
            "timestamp": timestamp,
            "source": source,
            "meta": meta,
        }
