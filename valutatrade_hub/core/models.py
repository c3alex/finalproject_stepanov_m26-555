"""Доменные модели: пользователь (User), кошелёк (Wallet) и портфель (Portfolio)."""

import hashlib
import secrets
from datetime import datetime
from typing import Any

from valutatrade_hub.core.exceptions import InsufficientFundsError
from valutatrade_hub.core.utils import BASE_CURRENCY, convert_amount

MIN_PASSWORD_LENGTH = 4
SALT_BYTES = 8

# Фиксированные курсы-заглушки (сколько USD стоит 1 единица валюты).
# Используются в Portfolio.get_total_value(), если актуальные курсы не переданы.
STUB_EXCHANGE_RATES: dict[str, float] = {
    "EUR_USD": 1.0786,
    "GBP_USD": 1.2650,
    "RUB_USD": 0.01016,
    "JPY_USD": 0.0067,
    "CNY_USD": 0.1390,
    "CHF_USD": 1.1050,
    "BTC_USD": 59337.21,
    "ETH_USD": 3720.00,
    "SOL_USD": 145.12,
}


def _hash_password(password: str, salt: str) -> str:
    """Возвращает SHA-256 хеш строки password + salt в шестнадцатеричном виде."""
    return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()


def _validate_password(password: str) -> None:
    """Проверяет пароль на тип и минимальную длину.

    Raises:
        ValueError: Пароль не строка или короче MIN_PASSWORD_LENGTH символов.
    """
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")


class User:
    """Пользователь системы.

    Пароль хранится только в виде SHA-256 хеша с уникальной солью.
    """

    def __init__(
        self,
        user_id: int,
        username: str,
        hashed_password: str,
        salt: str,
        registration_date: datetime,
    ) -> None:
        """Создаёт пользователя из уже подготовленных данных.

        Для регистрации нового пользователя удобнее User.create().

        Args:
            user_id: Уникальный идентификатор.
            username: Непустое имя пользователя.
            hashed_password: SHA-256 хеш пароля с солью.
            salt: Соль пользователя.
            registration_date: Дата регистрации.

        Raises:
            ValueError: Некорректное имя или идентификатор.
        """
        if not isinstance(user_id, int) or user_id <= 0:
            raise ValueError("user_id должен быть положительным целым числом")
        self._user_id = user_id
        self.username = username
        self._hashed_password = hashed_password
        self._salt = salt
        self._registration_date = registration_date

    @classmethod
    def create(cls, user_id: int, username: str, password: str) -> "User":
        """Создаёт нового пользователя: генерирует соль и хеширует пароль.

        Args:
            user_id: Идентификатор нового пользователя.
            username: Имя пользователя.
            password: Пароль в открытом виде (не короче 4 символов).

        Returns:
            Новый объект User с текущей датой регистрации.

        Raises:
            ValueError: Пустое имя или слишком короткий пароль.
        """
        _validate_password(password)
        salt = secrets.token_hex(SALT_BYTES)
        return cls(
            user_id=user_id,
            username=username,
            hashed_password=_hash_password(password, salt),
            salt=salt,
            registration_date=datetime.now().replace(microsecond=0),
        )

    @property
    def user_id(self) -> int:
        """Уникальный идентификатор пользователя (только чтение)."""
        return self._user_id

    @property
    def username(self) -> str:
        """Имя пользователя."""
        return self._username

    @username.setter
    def username(self, value: str) -> None:
        """Устанавливает имя пользователя.

        Raises:
            ValueError: Имя пустое или не строка.
        """
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Имя пользователя не может быть пустым")
        self._username = value.strip()

    @property
    def hashed_password(self) -> str:
        """Хеш пароля (только чтение; изменить — через change_password)."""
        return self._hashed_password

    @property
    def salt(self) -> str:
        """Соль пользователя (только чтение)."""
        return self._salt

    @property
    def registration_date(self) -> datetime:
        """Дата регистрации (только чтение)."""
        return self._registration_date

    def get_user_info(self) -> dict[str, Any]:
        """Возвращает публичную информацию о пользователе (без пароля и соли)."""
        return {
            "user_id": self._user_id,
            "username": self._username,
            "registration_date": self._registration_date.isoformat(),
        }

    def change_password(self, new_password: str) -> None:
        """Меняет пароль: генерирует новую соль и сохраняет новый хеш.

        Args:
            new_password: Новый пароль (не короче 4 символов).

        Raises:
            ValueError: Пароль слишком короткий.
        """
        _validate_password(new_password)
        self._salt = secrets.token_hex(SALT_BYTES)
        self._hashed_password = _hash_password(new_password, self._salt)

    def verify_password(self, password: str) -> bool:
        """Проверяет, совпадает ли введённый пароль с сохранённым хешем.

        Args:
            password: Пароль в открытом виде.

        Returns:
            True, если пароль верный.
        """
        if not isinstance(password, str):
            return False
        candidate = _hash_password(password, self._salt)
        return secrets.compare_digest(candidate, self._hashed_password)

    def to_dict(self) -> dict[str, Any]:
        """Сериализует пользователя для users.json (дата — в ISO-формате)."""
        return {
            "user_id": self._user_id,
            "username": self._username,
            "hashed_password": self._hashed_password,
            "salt": self._salt,
            "registration_date": self._registration_date.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "User":
        """Восстанавливает пользователя из записи users.json."""
        return cls(
            user_id=int(data["user_id"]),
            username=data["username"],
            hashed_password=data["hashed_password"],
            salt=data["salt"],
            registration_date=datetime.fromisoformat(data["registration_date"]),
        )


class Wallet:
    """Кошелёк пользователя для одной конкретной валюты."""

    def __init__(self, currency_code: str, balance: float = 0.0) -> None:
        """Создаёт кошелёк.

        Args:
            currency_code: Код валюты ("USD", "BTC").
            balance: Начальный баланс (по умолчанию 0.0).

        Raises:
            ValueError: Пустой код валюты или некорректный баланс.
        """
        if not isinstance(currency_code, str) or not currency_code.strip():
            raise ValueError("Код валюты не может быть пустым")
        self.currency_code = currency_code.strip().upper()
        self.balance = balance

    @property
    def balance(self) -> float:
        """Текущий баланс кошелька."""
        return self._balance

    @balance.setter
    def balance(self, value: float) -> None:
        """Устанавливает баланс, запрещая отрицательные и нечисловые значения.

        Raises:
            ValueError: Значение не число или отрицательное.
        """
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("Баланс должен быть числом")
        if value < 0:
            raise ValueError("Баланс не может быть отрицательным")
        self._balance = float(value)

    @staticmethod
    def _validate_amount(amount: float) -> float:
        """Проверяет, что сумма операции — положительное число.

        Raises:
            ValueError: Сумма не число или не больше нуля.
        """
        if isinstance(amount, bool) or not isinstance(amount, int | float):
            raise ValueError("'amount' должен быть положительным числом")
        if amount <= 0:
            raise ValueError("'amount' должен быть положительным числом")
        return float(amount)

    def deposit(self, amount: float) -> None:
        """Пополняет баланс на amount.

        Raises:
            ValueError: Сумма не положительное число.
        """
        self.balance = self._balance + self._validate_amount(amount)

    def withdraw(self, amount: float) -> None:
        """Снимает amount с баланса, если средств достаточно.

        Raises:
            ValueError: Сумма не положительное число.
            InsufficientFundsError: Сумма превышает текущий баланс.
        """
        amount = self._validate_amount(amount)
        if amount > self._balance:
            raise InsufficientFundsError(
                available=self._balance, required=amount, code=self.currency_code
            )
        self.balance = self._balance - amount

    def get_balance_info(self) -> str:
        """Возвращает строку с текущим балансом, например "BTC: 0.0500"."""
        return f"{self.currency_code}: {self._balance:.4f}"

    def to_dict(self) -> dict[str, Any]:
        """Сериализует кошелёк для portfolios.json."""
        return {"currency_code": self.currency_code, "balance": self._balance}


class Portfolio:
    """Портфель пользователя: набор кошельков, по одному на валюту."""

    def __init__(
        self,
        user_id: int,
        wallets: dict[str, Wallet] | None = None,
        user: User | None = None,
    ) -> None:
        """Создаёт портфель.

        Args:
            user_id: Идентификатор владельца.
            wallets: Словарь {код валюты: Wallet}; по умолчанию пустой.
            user: Объект владельца (необязательно).
        """
        self._user_id = user_id
        self._wallets: dict[str, Wallet] = dict(wallets or {})
        self._user = user

    @property
    def user_id(self) -> int:
        """Идентификатор владельца портфеля (только чтение)."""
        return self._user_id

    @property
    def user(self) -> User | None:
        """Объект владельца портфеля (только чтение)."""
        return self._user

    @property
    def wallets(self) -> dict[str, Wallet]:
        """Копия словаря кошельков: изменение копии не меняет портфель."""
        return dict(self._wallets)

    def add_currency(self, currency_code: str) -> Wallet:
        """Добавляет в портфель новый пустой кошелёк.

        Args:
            currency_code: Код валюты.

        Returns:
            Созданный кошелёк.

        Raises:
            ValueError: Кошелёк для этой валюты уже существует.
        """
        code = currency_code.strip().upper()
        if code in self._wallets:
            raise ValueError(f"Кошелёк '{code}' уже есть в портфеле")
        wallet = Wallet(code)
        self._wallets[code] = wallet
        return wallet

    def get_wallet(self, currency_code: str) -> Wallet | None:
        """Возвращает кошелёк по коду валюты или None, если его нет."""
        return self._wallets.get(currency_code.strip().upper())

    def get_or_create_wallet(self, currency_code: str) -> Wallet:
        """Возвращает кошелёк, создавая его через add_currency() при отсутствии."""
        return self.get_wallet(currency_code) or self.add_currency(currency_code)

    def get_total_value(
        self,
        base_currency: str = BASE_CURRENCY,
        exchange_rates: dict[str, float] | None = None,
    ) -> float:
        """Считает общую стоимость всех кошельков в базовой валюте.

        Args:
            base_currency: Валюта, в которой считается итог (по умолчанию USD).
            exchange_rates: Курсы вида {"BTC_USD": 59337.21, ...}. Если не
                переданы, используются фиксированные STUB_EXCHANGE_RATES.

        Returns:
            Суммарная стоимость портфеля в base_currency.

        Raises:
            RateUnavailableError: Нет курса для одной из валют.
        """
        rates = STUB_EXCHANGE_RATES if exchange_rates is None else exchange_rates
        base = base_currency.strip().upper()
        return sum(
            convert_amount(wallet.balance, code, base, rates)
            for code, wallet in self._wallets.items()
        )

    def to_dict(self) -> dict[str, Any]:
        """Сериализует портфель для portfolios.json."""
        return {
            "user_id": self._user_id,
            "wallets": {
                code: wallet.to_dict() for code, wallet in self._wallets.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], user: User | None = None) -> "Portfolio":
        """Восстанавливает портфель из записи portfolios.json."""
        wallets = {
            code: Wallet(code, float(raw.get("balance", 0.0)))
            for code, raw in data.get("wallets", {}).items()
        }
        return cls(user_id=int(data["user_id"]), wallets=wallets, user=user)
