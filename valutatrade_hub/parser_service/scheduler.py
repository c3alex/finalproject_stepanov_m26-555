"""Планировщик периодического обновления курсов."""

import logging
import threading

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.logging_config import PARSER_LOGGER_NAME
from valutatrade_hub.parser_service.updater import RatesUpdater

logger = logging.getLogger(PARSER_LOGGER_NAME)


class RatesScheduler:
    """Запускает RatesUpdater.run_update() каждые interval_seconds секунд."""

    def __init__(self, updater: RatesUpdater, interval_seconds: int) -> None:
        """Создаёт планировщик.

        Args:
            updater: Объект, выполняющий обновление.
            interval_seconds: Интервал между запусками (> 0).

        Raises:
            ValueError: Интервал не положительный.
        """
        if interval_seconds <= 0:
            raise ValueError("Интервал должен быть положительным числом секунд")
        self.updater = updater
        self.interval_seconds = interval_seconds
        self._stop_event = threading.Event()

    def run(self, max_runs: int | None = None) -> int:
        """Выполняет обновления в текущем потоке до остановки.

        Ошибки отдельных запусков логируются и не прерывают расписание.

        Args:
            max_runs: Максимальное число запусков (None — бесконечно).

        Returns:
            Количество выполненных запусков.
        """
        runs = 0
        while not self._stop_event.is_set():
            runs += 1
            logger.info("Scheduled update #%d", runs)
            try:
                self.updater.run_update()
            except ApiRequestError as error:
                logger.error("Scheduled update failed: %s", error.reason)
            if max_runs is not None and runs >= max_runs:
                break
            self._stop_event.wait(self.interval_seconds)
        return runs

    def start_in_background(self) -> threading.Thread:
        """Запускает run() в фоновом daemon-потоке и возвращает поток."""
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        """Останавливает планировщик (текущее ожидание прерывается)."""
        self._stop_event.set()
