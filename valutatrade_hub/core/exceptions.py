"""Пользовательские (доменные) исключения ValutaTrade Hub.

Исключения выбрасываются в ядре (models, currencies, usecases) и в Parser
Service, а перехватываются на уровне CLI, где превращаются в понятные
пользователю сообщения.
"""


class ValutaTradeError(Exception):
    """Базовое исключение приложения: все доменные ошибки наследуются от него."""


class InsufficientFundsError(ValutaTradeError):
    """Недостаточно средств на кошельке для списания.

    Выбрасывается в Wallet.withdraw() и в usecases.sell()/buy().
    """

    def __init__(self, available: float, required: float, code: str) -> None:
        """Сохраняет детали ошибки и формирует сообщение.

        Args:
            available: Доступный баланс кошелька.
            required: Требуемая для операции сумма.
            code: Код валюты кошелька.
        """
        self.available = available
        self.required = required
        self.code = code
        super().__init__(
            f"Недостаточно средств: доступно {available:.4f} {code}, "
            f"требуется {required:.4f} {code}"
        )


class CurrencyNotFoundError(ValutaTradeError):
    """Неизвестная (не поддерживаемая) валюта.

    Выбрасывается в currencies.get_currency() и при валидации входа get-rate.
    """

    def __init__(self, code: str) -> None:
        """Сохраняет код валюты и формирует сообщение.

        Args:
            code: Код валюты, который не удалось найти в реестре.
        """
        self.code = code
        super().__init__(f"Неизвестная валюта '{code}'")


class ApiRequestError(ValutaTradeError):
    """Сбой при обращении к внешнему API или недоступность курсов.

    Выбрасывается в API-клиентах Parser Service и в слое получения курсов.
    """

    def __init__(self, reason: str) -> None:
        """Сохраняет причину ошибки и формирует сообщение.

        Args:
            reason: Человекочитаемая причина сбоя.
        """
        self.reason = reason
        super().__init__(f"Ошибка при обращении к внешнему API: {reason}")


class RateUnavailableError(ApiRequestError):
    """Курс валютной пары недоступен ни в кеше, ни у Parser Service."""

    def __init__(self, from_code: str, to_code: str) -> None:
        """Формирует сообщение о недоступности курса пары.

        Args:
            from_code: Исходная валюта.
            to_code: Целевая валюта.
        """
        self.from_code = from_code
        self.to_code = to_code
        self.reason = f"курс {from_code}→{to_code} недоступен"
        ValutaTradeError.__init__(
            self,
            f"Курс {from_code}→{to_code} недоступен. Повторите попытку позже.",
        )


class WalletNotFoundError(ValutaTradeError):
    """У пользователя нет кошелька в указанной валюте."""

    def __init__(self, code: str) -> None:
        """Формирует сообщение об отсутствии кошелька.

        Args:
            code: Код валюты отсутствующего кошелька.
        """
        self.code = code
        super().__init__(
            f"У вас нет кошелька '{code}'. Добавьте валюту: она создаётся "
            "автоматически при первой покупке."
        )


class UsernameTakenError(ValutaTradeError):
    """Имя пользователя уже занято."""

    def __init__(self, username: str) -> None:
        """Формирует сообщение о занятом имени.

        Args:
            username: Имя, которое уже используется.
        """
        self.username = username
        super().__init__(f"Имя пользователя '{username}' уже занято")


class UserNotFoundError(ValutaTradeError):
    """Пользователь с указанным именем не найден."""

    def __init__(self, username: str) -> None:
        """Формирует сообщение об отсутствии пользователя.

        Args:
            username: Имя искомого пользователя.
        """
        self.username = username
        super().__init__(f"Пользователь '{username}' не найден")


class InvalidPasswordError(ValutaTradeError):
    """Введён неверный пароль."""

    def __init__(self) -> None:
        """Формирует стандартное сообщение о неверном пароле."""
        super().__init__("Неверный пароль")


class NotLoggedInError(ValutaTradeError):
    """Команда требует входа в систему."""

    def __init__(self) -> None:
        """Формирует стандартное сообщение о необходимости входа."""
        super().__init__("Сначала выполните login")


class RatesCacheEmptyError(ValutaTradeError):
    """Локальный кеш курсов rates.json пуст или отсутствует."""

    def __init__(self) -> None:
        """Формирует сообщение с подсказкой выполнить update-rates."""
        super().__init__(
            "Локальный кеш курсов пуст. Выполните 'update-rates', "
            "чтобы загрузить данные."
        )


class RateNotInCacheError(ValutaTradeError):
    """Курс для указанной валюты отсутствует в локальном кеше."""

    def __init__(self, code: str) -> None:
        """Формирует сообщение об отсутствии курса в кеше.

        Args:
            code: Код валюты, для которой нет курса.
        """
        self.code = code
        super().__init__(f"Курс для '{code}' не найден в кеше.")
