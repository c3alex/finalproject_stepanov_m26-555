"""Хранилище Parser Service: снимок rates.json и история exchange_rates.json.

rates.json — последние корректные курсы по каждой паре (кеш для Core):
    {"pairs": {"BTC_USD": {"rate", "updated_at", "source"}, ...},
     "source": "ParserService", "last_refresh": "..."}
exchange_rates.json — журнал всех измерений, по записи на пару и момент:
    [{"id": "BTC_USD_2025-10-10T12:00:00Z", "from_currency": "BTC", ...}, ...]
Обе записи атомарны (временный файл → rename).
"""

from pathlib import Path
from typing import Any

from valutatrade_hub.core.utils import parse_iso
from valutatrade_hub.infra.database import read_json, write_json_atomic

SNAPSHOT_SOURCE = "ParserService"


def _is_newer(candidate: str, current: str | None) -> bool:
    """Проверяет, что метка candidate свежее current (или current нет)."""
    if not current:
        return True
    try:
        return parse_iso(candidate) >= parse_iso(current)
    except ValueError:
        return True


class RatesStorage:
    """Чтение и атомарная запись файлов курсов Parser Service."""

    def __init__(self, rates_path: Path, history_path: Path) -> None:
        """Сохраняет пути к файлам кеша и истории.

        Args:
            rates_path: Путь к data/rates.json.
            history_path: Путь к data/exchange_rates.json.
        """
        self.rates_path = Path(rates_path)
        self.history_path = Path(history_path)

    def load_snapshot(self) -> dict[str, Any]:
        """Возвращает текущий снимок rates.json (пустой при отсутствии файла)."""
        data = read_json(self.rates_path, {})
        if not isinstance(data, dict) or not isinstance(data.get("pairs"), dict):
            return {"pairs": {}, "last_refresh": None}
        return data

    def save_snapshot(
        self, pairs: dict[str, dict[str, Any]], last_refresh: str
    ) -> dict[str, Any]:
        """Объединяет новые курсы со снимком и атомарно сохраняет rates.json.

        Для каждой пары хранится один срез: новое значение «побеждает»,
        только если его updated_at не старше текущего.

        Args:
            pairs: {"BTC_USD": {"rate", "updated_at", "source"}, ...}.
            last_refresh: Время завершения обновления (ISO UTC).

        Returns:
            Записанный снимок.
        """
        snapshot = self.load_snapshot()
        current_pairs: dict[str, Any] = dict(snapshot.get("pairs", {}))
        for pair, entry in pairs.items():
            existing = current_pairs.get(pair, {})
            if _is_newer(entry["updated_at"], existing.get("updated_at")):
                current_pairs[pair] = entry
        new_snapshot = {
            "pairs": dict(sorted(current_pairs.items())),
            "source": SNAPSHOT_SOURCE,
            "last_refresh": last_refresh,
        }
        write_json_atomic(self.rates_path, new_snapshot)
        return new_snapshot

    def load_history(self) -> list[dict[str, Any]]:
        """Возвращает список записей истории exchange_rates.json."""
        data = read_json(self.history_path, [])
        return data if isinstance(data, list) else []

    def append_history(self, records: list[dict[str, Any]]) -> int:
        """Добавляет записи в историю, пропуская уже существующие id.

        Args:
            records: Записи формата exchange_rates.json.

        Returns:
            Количество реально добавленных записей.
        """
        history = self.load_history()
        known_ids = {record.get("id") for record in history}
        new_records = [record for record in records if record["id"] not in known_ids]
        if new_records:
            write_json_atomic(self.history_path, history + new_records)
        return len(new_records)
