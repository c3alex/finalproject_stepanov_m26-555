"""Singleton SettingsLoader: единая точка конфигурации приложения.

Конфигурация читается из секции [tool.valutatrade] файла pyproject.toml
(ищется в текущей директории и выше). Отсутствующие ключи берутся из
DEFAULT_SETTINGS, поэтому приложение работает и после установки пакета,
когда pyproject.toml рядом нет.

Ключи конфигурации:
    data_dir, users_file, portfolios_file, rates_file, history_file —
        пути к JSON-хранилищам (относительно корня проекта);
    rates_ttl_seconds — срок свежести курсов в кеше rates.json;
    default_base_currency — базовая валюта по умолчанию;
    log_dir, log_level, log_format ("text" или "json"),
    log_max_bytes, log_backup_count — параметры логирования и ротации.
"""

import tomllib
from pathlib import Path
from typing import Any

PYPROJECT_FILE = "pyproject.toml"
TOOL_SECTION = "valutatrade"
PATH_KEYS = (
    "data_dir",
    "users_file",
    "portfolios_file",
    "rates_file",
    "history_file",
    "log_dir",
)

DEFAULT_SETTINGS: dict[str, Any] = {
    "data_dir": "data",
    "users_file": "data/users.json",
    "portfolios_file": "data/portfolios.json",
    "rates_file": "data/rates.json",
    "history_file": "data/exchange_rates.json",
    "rates_ttl_seconds": 300,
    "default_base_currency": "USD",
    "log_dir": "logs",
    "log_level": "INFO",
    "log_format": "text",
    "log_max_bytes": 1_048_576,
    "log_backup_count": 5,
}

_MISSING = object()


class SettingsLoader:
    """Загрузчик и кеш конфигурации (Singleton).

    Singleton реализован через __new__: это самый простой и читаемый способ —
    не нужен метакласс, а повторные вызовы SettingsLoader() (в том числе при
    импортах из разных модулей) возвращают один и тот же объект. Конфигурация
    загружается только при первом создании экземпляра.
    """

    _instance: "SettingsLoader | None" = None

    def __new__(cls) -> "SettingsLoader":
        """Возвращает единственный экземпляр, создавая его при первом вызове."""
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._settings = {}
            instance._root = Path.cwd()
            instance._load()
            cls._instance = instance
        return cls._instance

    @staticmethod
    def _find_pyproject() -> Path | None:
        """Ищет pyproject.toml в текущей директории и её родителях."""
        current = Path.cwd().resolve()
        for directory in (current, *current.parents):
            candidate = directory / PYPROJECT_FILE
            if candidate.is_file():
                return candidate
        return None

    def _load(self) -> None:
        """Читает конфигурацию: дефолты, поверх них — [tool.valutatrade]."""
        settings = dict(DEFAULT_SETTINGS)
        pyproject = self._find_pyproject()
        if pyproject is not None:
            self._root = pyproject.parent
            try:
                with pyproject.open("rb") as file:
                    data = tomllib.load(file)
                settings.update(data.get("tool", {}).get(TOOL_SECTION, {}))
            except (OSError, tomllib.TOMLDecodeError):
                pass
        self._settings = settings

    def get(self, key: str, default: Any = _MISSING) -> Any:
        """Возвращает значение настройки.

        Пути (ключи из PATH_KEYS) возвращаются как абсолютные Path
        относительно корня проекта.

        Args:
            key: Имя настройки.
            default: Значение, если ключа нет.

        Raises:
            KeyError: Ключа нет и default не передан.
        """
        if key not in self._settings:
            if default is _MISSING:
                raise KeyError(f"Неизвестная настройка '{key}'")
            return default
        value = self._settings[key]
        if key in PATH_KEYS:
            return self._root / value
        return value

    def reload(self) -> None:
        """Перечитывает конфигурацию из pyproject.toml."""
        self._root = Path.cwd()
        self._load()

    def as_dict(self) -> dict[str, Any]:
        """Возвращает копию всех настроек (пути — в исходном виде)."""
        return dict(self._settings)
