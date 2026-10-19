"""Singleton DatabaseManager: абстракция над JSON-хранилищем в data/.

Все записи выполняются атомарно: данные пишутся во временный файл рядом
с целевым, затем временный файл переименовывается (os.replace).
"""

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from valutatrade_hub.infra.settings import SettingsLoader

JSON_INDENT = 2


def read_json(path: Path, default: Any) -> Any:
    """Читает JSON-файл.

    Args:
        path: Путь к файлу.
        default: Значение, возвращаемое при отсутствии/пустоте/порче файла.

    Returns:
        Содержимое файла или default.
    """
    try:
        with path.open("r", encoding="utf-8") as file:
            content = file.read()
    except (FileNotFoundError, IsADirectoryError):
        return default
    if not content.strip():
        return default
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return default


def write_json_atomic(path: Path, data: Any) -> None:
    """Атомарно записывает данные в JSON-файл (tmp → rename).

    Args:
        path: Целевой файл; родительские каталоги создаются при необходимости.
        data: JSON-сериализуемые данные.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=JSON_INDENT)
            file.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


class DatabaseManager:
    """Единая точка доступа к JSON-файлам пользователей, портфелей и курсов.

    Singleton через __new__ (см. комментарий в SettingsLoader): так же просто
    и читаемо, а все модули работают с одним объектом и одними путями.
    """

    _instance: "DatabaseManager | None" = None

    def __new__(cls) -> "DatabaseManager":
        """Возвращает единственный экземпляр менеджера."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._settings = SettingsLoader()
        return cls._instance

    @property
    def users_path(self) -> Path:
        """Путь к users.json."""
        return self._settings.get("users_file")

    @property
    def portfolios_path(self) -> Path:
        """Путь к portfolios.json."""
        return self._settings.get("portfolios_file")

    @property
    def rates_path(self) -> Path:
        """Путь к rates.json."""
        return self._settings.get("rates_file")

    def load_users(self) -> list[dict[str, Any]]:
        """Возвращает список записей пользователей."""
        return read_json(self.users_path, [])

    def save_users(self, users: list[dict[str, Any]]) -> None:
        """Сохраняет список записей пользователей."""
        write_json_atomic(self.users_path, users)

    def load_portfolios(self) -> list[dict[str, Any]]:
        """Возвращает список записей портфелей."""
        return read_json(self.portfolios_path, [])

    def save_portfolios(self, portfolios: list[dict[str, Any]]) -> None:
        """Сохраняет список записей портфелей."""
        write_json_atomic(self.portfolios_path, portfolios)

    def load_rates(self) -> dict[str, Any]:
        """Возвращает кеш курсов в формате {"pairs": {...}, "last_refresh": ...}."""
        data = read_json(self.rates_path, {})
        if not isinstance(data, dict):
            return {"pairs": {}, "last_refresh": None}
        data.setdefault("pairs", {})
        data.setdefault("last_refresh", None)
        return data

    def update(
        self, path: Path, default: Any, modifier: Callable[[Any], Any]
    ) -> Any:
        """Безопасная операция «чтение → модификация → запись».

        Если modifier выбросит исключение, файл не изменится.

        Args:
            path: JSON-файл.
            default: Значение по умолчанию при пустом/отсутствующем файле.
            modifier: Функция, получающая данные и возвращающая новые данные.

        Returns:
            Записанные данные.
        """
        data = read_json(path, default)
        new_data = modifier(data)
        write_json_atomic(path, new_data)
        return new_data
