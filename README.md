# ValutaTrade Hub

Консольная платформа для отслеживания и симуляции торговли фиатными и
криптовалютами. Пользователь регистрируется, пополняет виртуальный
USD-счёт, покупает и продаёт валюты, смотрит портфель и актуальные курсы.

Система состоит из двух сервисов:

- **Core Service** — CLI, пользователи, портфели, сделки, получение курсов
  из локального кеша `data/rates.json` с учётом TTL.
- **Parser Service** — получает курсы из CoinGecko (крипта) и
  ExchangeRate-API (фиат), объединяет их, атомарно пишет снимок в
  `data/rates.json` и историю измерений в `data/exchange_rates.json`.

## Структура проекта

```
finalproject_stepanov_m26-555/
├── data/
│   ├── users.json             # пользователи (хеш пароля + соль, ISO-дата)
│   ├── portfolios.json        # портфели и кошельки
│   ├── rates.json             # кеш последних курсов для Core Service
│   └── exchange_rates.json    # история измерений Parser Service
├── valutatrade_hub/
│   ├── logging_config.py      # формат логов, уровень, ротация
│   ├── decorators.py          # @log_action
│   ├── core/
│   │   ├── currencies.py      # Currency (ABC), FiatCurrency, CryptoCurrency, get_currency()
│   │   ├── exceptions.py      # доменные исключения
│   │   ├── models.py          # User, Wallet, Portfolio
│   │   ├── usecases.py        # бизнес-логика: register/login/buy/sell/get_rate...
│   │   └── utils.py           # валидация, конвертация, форматирование
│   ├── infra/
│   │   ├── settings.py        # Singleton SettingsLoader
│   │   └── database.py        # Singleton DatabaseManager (JSON-хранилище)
│   ├── parser_service/
│   │   ├── config.py          # ParserConfig: ключи, URL, списки валют, таймаут
│   │   ├── api_clients.py     # BaseApiClient, CoinGeckoClient, ExchangeRateApiClient
│   │   ├── updater.py         # RatesUpdater.run_update()
│   │   ├── storage.py         # атомарная запись rates.json / exchange_rates.json
│   │   └── scheduler.py       # периодическое обновление
│   └── cli/
│       └── interface.py       # команды CLI
├── docs/demo.cast             # запись asciinema
├── main.py
├── Makefile
├── pyproject.toml
└── uv.lock
```

## Установка и запуск

Нужны Python 3.12+ и [uv](https://docs.astral.sh/uv/).

```bash
make install      # uv sync — установить зависимости
make project      # uv run project — запустить интерактивный CLI
make lint         # uv run ruff check .
make build        # uv build — собрать пакет в dist/
make publish      # uv publish --dry-run — проверить публикацию
make package-install  # uv tool install dist/*.whl — установить как команду project
```

Также можно запустить `python main.py` (внутри окружения) или выполнить
одну команду без интерактивного режима: `uv run project show-rates --top 2`.
Команды, требующие входа (`buy`, `sell`, `show-portfolio`, `deposit`),
работают в интерактивном режиме, где сохраняется сессия после `login`.

## Команды CLI

| Команда | Описание |
|---|---|
| `register --username <str> --password <str>` | регистрация (пароль ≥ 4 символов) |
| `login --username <str> --password <str>` | вход |
| `logout` | выход из учётной записи |
| `show-portfolio [--base <str>]` | кошельки и итоговая стоимость (по умолчанию в USD) |
| `deposit --currency <str> --amount <float>` | пополнение кошелька (например, USD) |
| `buy --currency <str> --amount <float>` | покупка валюты, стоимость списывается с USD |
| `sell --currency <str> --amount <float>` | продажа валюты, выручка зачисляется на USD |
| `get-rate --from <str> --to <str>` | курс одной валюты к другой |
| `update-rates [--source coingecko\|exchangerate]` | немедленное обновление курсов |
| `show-rates [--currency <str>] [--top <int>] [--base <str>]` | курсы из кеша |
| `schedule-rates [--interval <int>] [--runs <int>]` | периодическое обновление |
| `list-currencies` | поддерживаемые валюты |
| `help [команда]`, `exit` | справка и выход |

Поддерживаемые валюты: USD, EUR, GBP, RUB, JPY, CNY, CHF, BTC, ETH, SOL.

### Пример сессии

```
> register --username alice --password 1234
Пользователь 'alice' зарегистрирован (id=1). Войдите: login --username alice --password ****
> login --username alice --password 1234
Вы вошли как 'alice'
> deposit --currency USD --amount 10000
Пополнение выполнено: 10000.00 USD
- USD: было 0.00 → стало 10000.00
> buy --currency BTC --amount 0.05
Покупка выполнена: 0.0500 BTC по курсу 81853.00 USD/BTC
Изменения в портфеле:
- BTC: было 0.0000 → стало 0.0500
- USD: было 10,000.00 → стало 5,907.35
Оценочная стоимость покупки: 4,092.65 USD
> sell --currency BTC --amount 0.01
Продажа выполнена: 0.0100 BTC по курсу 81853.00 USD/BTC
Изменения в портфеле:
- BTC: было 0.0500 → стало 0.0400
- USD: было 5,907.35 → стало 6,725.88
Оценочная выручка: 818.53 USD
> show-portfolio
Портфель пользователя 'alice' (база: USD):
- BTC: 0.0400  → 3,274.12 USD
- USD: 6725.88  → 6,725.88 USD
---------------------------------
ИТОГО: 10,000.00 USD
> get-rate --from USD --to BTC
Курс USD→BTC: 0.00001222 (обновлено: 2026-10-19 21:42:01)
Обратный курс BTC→USD: 81853.00
> update-rates
INFO: Starting rates update...
INFO: Fetching from CoinGecko... OK (3 rates)
INFO: Fetching from ExchangeRate-API... OK (6 rates)
INFO: Writing 9 rates to data/rates.json...
INFO: Update finished: 9 rates, errors: 0
Update successful. Total rates updated: 9. Last refresh: 2026-10-19T18:44:21Z
> show-rates --top 2
Rates from cache (updated at 2026-10-19T18:44:21Z):
+---------+----------+---------------------+-----------+
| Pair    |     Rate |      Updated at     |   Source  |
+---------+----------+---------------------+-----------+
| BTC_USD | 81846.00 | 2026-10-19 21:44:21 | CoinGecko |
| ETH_USD |  2397.90 | 2026-10-19 21:44:21 | CoinGecko |
+---------+----------+---------------------+-----------+
```

### Обработка ошибок

| Ситуация | Сообщение |
|---|---|
| Не выполнен вход | `Сначала выполните login` |
| Имя занято / короткий пароль | `Имя пользователя 'alice' уже занято` / `Пароль должен быть не короче 4 символов` |
| Неверные данные входа | `Пользователь 'bob' не найден` / `Неверный пароль` |
| Некорректная сумма | `'amount' должен быть положительным числом` |
| Недостаточно средств | `Недостаточно средств: доступно 0.0400 BTC, требуется 5.0000 BTC` |
| Нет кошелька | `У вас нет кошелька 'ETH'. Добавьте валюту: она создаётся автоматически при первой покупке.` |
| Неизвестная валюта | `Неизвестная валюта 'ABC'` + список поддерживаемых кодов |
| Неизвестная база | `Неизвестная базовая валюта 'ABC'` |
| Курс недоступен | `Курс USD→BTC недоступен. Повторите попытку позже.` |
| Пустой кеш | `Локальный кеш курсов пуст. Выполните 'update-rates', чтобы загрузить данные.` |

## Кеш курсов и TTL

`data/rates.json` хранит по одному последнему срезу на пару:

```json
{
  "pairs": {
    "EUR_USD": {"rate": 1.1225, "updated_at": "2026-10-19T18:44:21Z", "source": "ExchangeRate-API"},
    "BTC_USD": {"rate": 81846.0, "updated_at": "2026-10-19T18:44:21Z", "source": "CoinGecko"}
  },
  "source": "ParserService",
  "last_refresh": "2026-10-19T18:44:21Z"
}
```

Курс считается свежим, если он моложе `rates_ttl_seconds` (по умолчанию
300 секунд). Если нужный курс устарел или отсутствует, `get-rate`, `buy`,
`sell` и `show-portfolio` сами запускают Parser Service. Если обновиться
не удалось, используется последний известный курс с предупреждением
«курсы устарели… Выполните 'update-rates' позже», а при полном отсутствии
данных выводится «Курс … недоступен». Кросс-курсы (например, EUR→RUB)
считаются через USD.

`data/exchange_rates.json` — журнал всех измерений; id записи
`<FROM>_<TO>_<ISO-UTC timestamp>`, дубликаты не записываются. Обе записи
выполняются атомарно (временный файл → `os.replace`). Падение одного
источника не останавливает обновление по другим.

## Parser Service и API-ключ

- CoinGecko работает без ключа.
- ExchangeRate-API: получите бесплатный ключ на
  <https://www.exchangerate-api.com/> и передайте его через переменную
  окружения или файл `.env` в корне проекта (он в `.gitignore`):

  ```bash
  export EXCHANGERATE_API_KEY=ваш_ключ
  # или
  cp .env.example .env   # и впишите ключ
  ```

  Без ключа клиент использует открытый эндпоинт `open.er-api.com`
  (тот же формат, обновление раз в сутки).

Запуск: `update-rates` (разово), `update-rates --source coingecko`
(один источник), `schedule-rates --interval 300` (по расписанию, Ctrl+C
для остановки). Списки валют, URL, таймаут и пути задаются в
`valutatrade_hub/parser_service/config.py`.

## Конфигурация и логи

Настройки читаются Singleton-классом `SettingsLoader` из секции
`[tool.valutatrade]` в `pyproject.toml`: пути к JSON-файлам, `rates_ttl_seconds`,
`default_base_currency`, `log_dir`, `log_level` (`INFO`/`DEBUG`),
`log_format` (`text`/`json`), параметры ротации.

Логи пишутся в `logs/` с ротацией по размеру (1 МБ, 5 архивов):

- `logs/actions.log` — операции REGISTER/LOGIN/DEPOSIT/BUY/SELL через `@log_action`:
  ```
  INFO 2026-10-19T21:42:01 BUY user='alice' currency='BTC' amount=0.0500 rate=81853.00 base='USD' wallet='0.0000->0.0500' result=OK
  INFO 2026-10-19T21:42:01 BUY user=1 currency='BTC' amount=-1.0000 result=ERROR error_type=ValueError error_message=''amount' должен быть положительным числом'
  ```
- `logs/parser.log` — шаги Parser Service.

## Демо

[![asciicast](https://asciinema.org/a/4BGDhGFAjsYRlgry.svg)](https://asciinema.org/a/4BGDhGFAjsYRlgry)

Локальная запись: [`docs/demo.cast`](docs/demo.cast) (воспроизвести:
`asciinema play docs/demo.cast`). Показан полный цикл register → login →
deposit → buy/sell → show-portfolio → get-rate, затем update-rates,
show-rates с фильтрами и обработка ошибок.
