"""Конфигурация Parser Service: API-ключи, эндпоинты, списки валют, таймауты.

API-ключ ExchangeRate-API не хранится в коде: он берётся из переменной
окружения EXCHANGERATE_API_KEY или из файла .env в корне проекта
(файл добавлен в .gitignore).
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from valutatrade_hub.infra.settings import SettingsLoader

API_KEY_ENV_VAR = "EXCHANGERATE_API_KEY"
ENV_FILE_NAME = ".env"


def _read_env_file(path: Path, key: str) -> str | None:
    """Ищет значение key в файле формата KEY=VALUE (строки # — комментарии)."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            return value.strip().strip("'\"") or None
    return None


def load_api_key() -> str | None:
    """Возвращает ключ ExchangeRate-API из окружения или файла .env."""
    from_env = os.getenv(API_KEY_ENV_VAR)
    if from_env:
        return from_env.strip()
    env_file = SettingsLoader().get("data_dir").parent / ENV_FILE_NAME
    return _read_env_file(env_file, API_KEY_ENV_VAR)


@dataclass
class ParserConfig:
    """Все изменяемые параметры Parser Service в одном месте."""

    # Ключ загружается из переменной окружения или .env
    EXCHANGERATE_API_KEY: str | None = field(default_factory=load_api_key)

    # Эндпоинты
    COINGECKO_URL: str = "https://api.coingecko.com/api/v3/simple/price"
    EXCHANGERATE_API_URL: str = "https://v6.exchangerate-api.com/v6"

    # Списки валют
    BASE_CURRENCY: str = "USD"
    FIAT_CURRENCIES: tuple[str, ...] = ("EUR", "GBP", "RUB", "JPY", "CNY", "CHF")
    CRYPTO_CURRENCIES: tuple[str, ...] = ("BTC", "ETH", "SOL")
    CRYPTO_ID_MAP: dict[str, str] = field(
        default_factory=lambda: {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
        }
    )

    # Пути (берутся из SettingsLoader, чтобы Core и Parser видели одни файлы)
    RATES_FILE_PATH: Path = field(
        default_factory=lambda: SettingsLoader().get("rates_file")
    )
    HISTORY_FILE_PATH: Path = field(
        default_factory=lambda: SettingsLoader().get("history_file")
    )

    # Сетевые параметры
    REQUEST_TIMEOUT: int = 10

    # Планировщик: интервал периодического обновления по умолчанию
    UPDATE_INTERVAL_SECONDS: int = 300

