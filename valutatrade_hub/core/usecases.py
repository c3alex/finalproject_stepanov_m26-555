"""Бизнес-логика ValutaTrade Hub: пользователи, портфели, сделки и курсы.

CLI вызывает только функции этого модуля. Синглтоны используются так:
    SettingsLoader — TTL курсов (rates_ttl_seconds) и базовая валюта;
    DatabaseManager — чтение/атомарная запись users/portfolios/rates.
Операции register/login/deposit/buy/sell логируются декоратором @log_action.
"""

from dataclasses import dataclass
from typing import Any

from valutatrade_hub.core.currencies import is_crypto
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    InsufficientFundsError,
    InvalidPasswordError,
    RateNotInCacheError,
    RatesCacheEmptyError,
    RateUnavailableError,
    UsernameTakenError,
    UserNotFoundError,
    WalletNotFoundError,
)
from valutatrade_hub.core.models import Portfolio, User
from valutatrade_hub.core.utils import (
    BASE_CURRENCY,
    cross_rate,
    is_fresh,
    make_pair_key,
    split_pair_key,
    validate_amount,
    validate_currency_code,
)
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import setup_logging

setup_logging()


@dataclass
class RateQuote:
    """Результат запроса курса.

    Attributes:
        from_code: Исходная валюта.
        to_code: Целевая валюта.
        rate: Сколько to_code стоит 1 from_code.
        updated_at: Время обновления самого старого из использованных курсов.
        is_stale: True, если курс старше TTL и обновить его не удалось.
        refresh_error: Причина неудачного обновления (если было).
    """

    from_code: str
    to_code: str
    rate: float
    updated_at: str | None
    is_stale: bool = False
    refresh_error: str | None = None

    @property
    def inverse_rate(self) -> float:
        """Обратный курс to_code→from_code."""
        return 1 / self.rate if self.rate else 0.0


# --------------------------------------------------------------------------
# Пользователи
# --------------------------------------------------------------------------


def _load_users() -> list[User]:
    """Загружает всех пользователей из users.json."""
    return [User.from_dict(record) for record in DatabaseManager().load_users()]


def _find_user_by_name(username: str) -> User | None:
    """Ищет пользователя по имени (без учёта пробелов по краям)."""
    name = username.strip()
    return next((user for user in _load_users() if user.username == name), None)


def _get_user(user_id: int) -> User:
    """Возвращает пользователя по id.

    Raises:
        UserNotFoundError: Пользователя с таким id нет.
    """
    user = next((u for u in _load_users() if u.user_id == user_id), None)
    if user is None:
        raise UserNotFoundError(str(user_id))
    return user


@log_action("REGISTER")
def register_user(username: str, password: str) -> dict[str, Any]:
    """Регистрирует пользователя и создаёт ему пустой портфель.

    Args:
        username: Уникальное непустое имя.
        password: Пароль не короче 4 символов.

    Returns:
        {"user_id": ..., "username": ...}.

    Raises:
        ValueError: Пустое имя или короткий пароль.
        UsernameTakenError: Имя уже занято.
    """
    if not isinstance(username, str) or not username.strip():
        raise ValueError("Имя пользователя не может быть пустым")
    db = DatabaseManager()
    records = db.load_users()
    name = username.strip()
    if any(record["username"] == name for record in records):
        raise UsernameTakenError(name)
    user_id = max((int(record["user_id"]) for record in records), default=0) + 1
    user = User.create(user_id, name, password)

    db.update(db.users_path, [], lambda users: [*users, user.to_dict()])
    _save_portfolio(Portfolio(user_id))
    return {"user_id": user.user_id, "username": user.username}


@log_action("LOGIN")
def login_user(username: str, password: str) -> dict[str, Any]:
    """Проверяет имя и пароль пользователя.

    Returns:
        {"user_id": ..., "username": ...} для сохранения сессии в CLI.

    Raises:
        UserNotFoundError: Пользователь не найден.
        InvalidPasswordError: Пароль неверный.
    """
    user = _find_user_by_name(username)
    if user is None:
        raise UserNotFoundError(username.strip())
    if not user.verify_password(password):
        raise InvalidPasswordError()
    return {"user_id": user.user_id, "username": user.username}


# --------------------------------------------------------------------------
# Портфели
# --------------------------------------------------------------------------


def _load_portfolio(user_id: int) -> Portfolio:
    """Загружает портфель пользователя (пустой, если записи нет)."""
    user = _get_user(user_id)
    for record in DatabaseManager().load_portfolios():
        if int(record["user_id"]) == user_id:
            return Portfolio.from_dict(record, user=user)
    return Portfolio(user_id, user=user)


def _save_portfolio(portfolio: Portfolio) -> None:
    """Сохраняет портфель через безопасное «чтение → модификация → запись»."""
    db = DatabaseManager()
    new_record = portfolio.to_dict()

    def replace_record(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        others = [r for r in records if int(r["user_id"]) != portfolio.user_id]
        return sorted([*others, new_record], key=lambda r: int(r["user_id"]))

    db.update(db.portfolios_path, [], replace_record)


def get_portfolio_summary(user_id: int, base: str | None = None) -> dict[str, Any]:
    """Возвращает кошельки пользователя и их стоимость в базовой валюте.

    Args:
        user_id: Идентификатор залогиненного пользователя.
        base: Базовая валюта (по умолчанию из настроек, обычно USD).

    Returns:
        {"username", "base", "wallets": [{"currency", "balance", "value"}],
         "total", "is_stale", "updated_at", "refresh_error"}.

    Raises:
        CurrencyNotFoundError: Неизвестная базовая валюта.
        RateUnavailableError: Нет курса для одной из валют портфеля.
    """
    base_code = validate_currency_code(
        base or SettingsLoader().get("default_base_currency")
    )
    portfolio = _load_portfolio(user_id)
    wallets = portfolio.wallets
    rates: dict[str, float] = {}
    updated_at, is_stale, refresh_error = None, False, None
    if wallets:
        rates, updated_at, is_stale, refresh_error = _ensure_rates(
            [*wallets, base_code]
        )

    items = [
        {
            "currency": code,
            "balance": wallet.balance,
            "value": wallet.balance * cross_rate(code, base_code, rates),
        }
        for code, wallet in sorted(wallets.items())
    ]
    total = portfolio.get_total_value(base_code, rates) if wallets else 0.0
    return {
        "username": portfolio.user.username if portfolio.user else str(user_id),
        "base": base_code,
        "wallets": items,
        "total": total,
        "is_stale": is_stale,
        "updated_at": updated_at,
        "refresh_error": refresh_error,
    }


@log_action("DEPOSIT", verbose=True)
def deposit(user_id: int, currency_code: str, amount: float) -> dict[str, Any]:
    """Пополняет кошелёк пользователя (кошелёк создаётся при отсутствии).

    Returns:
        {"username", "currency", "amount", "old_balance", "new_balance"}.

    Raises:
        ValueError: Некорректная сумма.
        CurrencyNotFoundError: Неизвестная валюта.
    """
    amount = validate_amount(amount)
    code = validate_currency_code(currency_code)
    portfolio = _load_portfolio(user_id)
    wallet = portfolio.get_or_create_wallet(code)
    old_balance = wallet.balance
    wallet.deposit(amount)
    _save_portfolio(portfolio)
    return {
        "username": portfolio.user.username,
        "currency": code,
        "amount": amount,
        "old_balance": old_balance,
        "new_balance": wallet.balance,
    }


def _reject_base_trade(code: str, base: str) -> None:
    """Запрещает покупку/продажу базовой валюты за саму себя."""
    if code == base:
        raise ValueError(
            f"Операции buy/sell для {base} не нужны: пополнить счёт можно "
            f"командой deposit --currency {base} --amount <сумма>"
        )


@log_action("BUY", verbose=True)
def buy(user_id: int, currency_code: str, amount: float) -> dict[str, Any]:
    """Покупает amount единиц валюты, списывая стоимость с USD-кошелька.

    Если кошелька покупаемой валюты нет, он создаётся автоматически.

    Args:
        user_id: Идентификатор залогиненного пользователя.
        currency_code: Код покупаемой валюты (например, BTC).
        amount: Количество покупаемой валюты (> 0).

    Returns:
        Детали сделки: currency, amount, rate, base, old_balance,
        new_balance, cost, base_old_balance, base_new_balance,
        updated_at, is_stale.

    Raises:
        ValueError: Некорректная сумма или покупка базовой валюты.
        CurrencyNotFoundError: Неизвестная валюта.
        RateUnavailableError: Курс недоступен.
        InsufficientFundsError: На USD-кошельке не хватает средств.
    """
    amount = validate_amount(amount)
    code = validate_currency_code(currency_code)
    base = BASE_CURRENCY
    _reject_base_trade(code, base)
    quote = get_rate(code, base)
    cost = amount * quote.rate

    portfolio = _load_portfolio(user_id)
    base_wallet = portfolio.get_wallet(base)
    if base_wallet is None:
        raise InsufficientFundsError(available=0.0, required=cost, code=base)
    base_old = base_wallet.balance
    base_wallet.withdraw(cost)

    wallet = portfolio.get_or_create_wallet(code)
    old_balance = wallet.balance
    wallet.deposit(amount)
    _save_portfolio(portfolio)
    return _trade_result(
        portfolio,
        code,
        amount,
        quote,
        old_balance,
        wallet.balance,
        cost,
        base_old,
        base_wallet.balance,
    )


@log_action("SELL", verbose=True)
def sell(user_id: int, currency_code: str, amount: float) -> dict[str, Any]:
    """Продаёт amount единиц валюты и начисляет выручку на USD-кошелёк.

    Args:
        user_id: Идентификатор залогиненного пользователя.
        currency_code: Код продаваемой валюты.
        amount: Количество продаваемой валюты (> 0).

    Returns:
        Детали сделки (как у buy(), cost — оценочная выручка).

    Raises:
        ValueError: Некорректная сумма или продажа базовой валюты.
        CurrencyNotFoundError: Неизвестная валюта.
        WalletNotFoundError: У пользователя нет такого кошелька.
        InsufficientFundsError: На кошельке недостаточно средств.
        RateUnavailableError: Курс недоступен.
    """
    amount = validate_amount(amount)
    code = validate_currency_code(currency_code)
    base = BASE_CURRENCY
    _reject_base_trade(code, base)

    portfolio = _load_portfolio(user_id)
    wallet = portfolio.get_wallet(code)
    if wallet is None:
        raise WalletNotFoundError(code)
    if amount > wallet.balance:
        raise InsufficientFundsError(
            available=wallet.balance, required=amount, code=code
        )
    quote = get_rate(code, base)
    revenue = amount * quote.rate

    old_balance = wallet.balance
    wallet.withdraw(amount)
    base_wallet = portfolio.get_or_create_wallet(base)
    base_old = base_wallet.balance
    base_wallet.deposit(revenue)
    _save_portfolio(portfolio)
    return _trade_result(
        portfolio,
        code,
        amount,
        quote,
        old_balance,
        wallet.balance,
        revenue,
        base_old,
        base_wallet.balance,
    )


def _trade_result(
    portfolio: Portfolio,
    code: str,
    amount: float,
    quote: RateQuote,
    old_balance: float,
    new_balance: float,
    value: float,
    base_old: float,
    base_new: float,
) -> dict[str, Any]:
    """Собирает словарь с результатом сделки для CLI и логов."""
    return {
        "username": portfolio.user.username,
        "currency": code,
        "amount": amount,
        "rate": quote.rate,
        "base": quote.to_code,
        "old_balance": old_balance,
        "new_balance": new_balance,
        "cost": value,
        "base_old_balance": base_old,
        "base_new_balance": base_new,
        "updated_at": quote.updated_at,
        "is_stale": quote.is_stale,
        "refresh_error": quote.refresh_error,
    }


# --------------------------------------------------------------------------
# Курсы
# --------------------------------------------------------------------------


def _read_cached_pairs() -> dict[str, dict[str, Any]]:
    """Возвращает словарь пар из rates.json: {"BTC_USD": {"rate", ...}}."""
    pairs = DatabaseManager().load_rates().get("pairs", {})
    return {
        pair: entry
        for pair, entry in pairs.items()
        if isinstance(entry, dict) and isinstance(entry.get("rate"), int | float)
    }


def _needed_pairs(codes: list[str]) -> list[str]:
    """Возвращает пары вида "<CODE>_USD", нужные для пересчёта codes."""
    return sorted(
        {make_pair_key(code, BASE_CURRENCY) for code in codes if code != BASE_CURRENCY}
    )


def _refresh_rates() -> str | None:
    """Пытается обновить кеш через Parser Service.

    Returns:
        None при успехе, иначе текст причины неудачи.
    """
    from valutatrade_hub.parser_service.updater import RatesUpdater

    try:
        RatesUpdater().run_update()
    except ApiRequestError as error:
        return error.reason
    return None


def _ensure_rates(
    codes: list[str],
) -> tuple[dict[str, float], str | None, bool, str | None]:
    """Возвращает курсы к USD для codes, обновляя кеш при истечении TTL.

    Returns:
        (курсы {"BTC_USD": ...}, самый старый updated_at, устарели ли данные,
        причина неудачного обновления или None).
    """
    ttl = int(SettingsLoader().get("rates_ttl_seconds"))
    needed = _needed_pairs(codes)
    pairs = _read_cached_pairs()

    def all_fresh() -> bool:
        return all(
            pair in pairs and is_fresh(pairs[pair].get("updated_at"), ttl)
            for pair in needed
        )

    refresh_error = None
    if not all_fresh():
        refresh_error = _refresh_rates()
        pairs = _read_cached_pairs()

    rates = {pair: float(entry["rate"]) for pair, entry in pairs.items()}
    timestamps = [pairs[p].get("updated_at") for p in needed if p in pairs]
    oldest = min((t for t in timestamps if t), default=None)
    return rates, oldest, not all_fresh(), refresh_error


def get_rate(from_code: str, to_code: str) -> RateQuote:
    """Возвращает курс from_code→to_code с учётом TTL кеша.

    Курс берётся из rates.json. Если он старше TTL (rates_ttl_seconds из
    SettingsLoader) или отсутствует — запускается обновление через Parser
    Service. Если обновить не удалось, но старый курс есть, он возвращается
    с флагом is_stale=True.

    Raises:
        ValueError: Пустой код валюты.
        CurrencyNotFoundError: Неизвестная валюта.
        RateUnavailableError: Курса нет ни в кеше, ни у Parser Service.
    """
    source = validate_currency_code(from_code)
    target = validate_currency_code(to_code)
    if source == target:
        return RateQuote(source, target, 1.0, None)
    rates, updated_at, is_stale, refresh_error = _ensure_rates([source, target])
    try:
        rate = cross_rate(source, target, rates)
    except RateUnavailableError:
        raise RateUnavailableError(source, target) from None
    return RateQuote(source, target, rate, updated_at, is_stale, refresh_error)


def update_rates(source: str | None = None) -> Any:
    """Запускает немедленное обновление курсов через Parser Service.

    Args:
        source: "coingecko", "exchangerate" или None (все источники).

    Returns:
        UpdateResult с итогами обновления.

    Raises:
        ValueError: Неизвестный источник.
        ApiRequestError: Ни один источник не вернул данные.
    """
    from valutatrade_hub.parser_service.updater import RatesUpdater

    return RatesUpdater().run_update(source)


def list_cached_rates(
    currency: str | None = None,
    top: int | None = None,
    base: str | None = None,
) -> dict[str, Any]:
    """Возвращает курсы из локального кеша с фильтрами.

    Args:
        currency: Показать только курс этой валюты.
        top: Показать N самых дорогих криптовалют.
        base: Пересчитать курсы относительно этой валюты (по умолчанию USD).

    Returns:
        {"last_refresh", "base", "rows": [{"pair", "rate", "updated_at",
        "source"}]}; без --top строки отсортированы по алфавиту.

    Raises:
        RatesCacheEmptyError: Кеш пуст или не найден.
        RateNotInCacheError: Для currency нет курса в кеше.
        CurrencyNotFoundError: Неизвестная валюта в currency/base.
        ValueError: top не положительный.
    """
    snapshot = DatabaseManager().load_rates()
    pairs = _read_cached_pairs()
    if not pairs:
        raise RatesCacheEmptyError()
    base_code = validate_currency_code(base) if base else BASE_CURRENCY
    rates = {pair: float(entry["rate"]) for pair, entry in pairs.items()}

    rows = []
    for pair, entry in pairs.items():
        code, _ = split_pair_key(pair)
        if code == base_code:
            continue
        try:
            rate = cross_rate(code, base_code, rates)
        except RateUnavailableError:
            continue
        rows.append(
            {
                "currency": code,
                "pair": make_pair_key(code, base_code),
                "rate": rate,
                "updated_at": entry.get("updated_at"),
                "source": entry.get("source", ""),
            }
        )

    if currency:
        code = currency.strip().upper()
        rows = [row for row in rows if row["currency"] == code]
        if not rows:
            raise RateNotInCacheError(code)
    if top is not None:
        if top <= 0:
            raise ValueError("'top' должен быть положительным целым числом")
        crypto_rows = [row for row in rows if is_crypto(row["currency"])]
        rows = sorted(crypto_rows, key=lambda row: row["rate"], reverse=True)[:top]
    else:
        rows.sort(key=lambda row: row["pair"])
    return {
        "last_refresh": snapshot.get("last_refresh"),
        "base": base_code,
        "rows": [{k: v for k, v in row.items() if k != "currency"} for row in rows],
    }
