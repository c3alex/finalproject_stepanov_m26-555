"""Командный интерфейс ValutaTrade Hub.

CLI только разбирает аргументы, вызывает функции core.usecases и печатает
результат. Доменные исключения перехватываются здесь и превращаются
в дружелюбные сообщения.
"""

import argparse
import shlex
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from prettytable import PrettyTable

from valutatrade_hub.core import usecases
from valutatrade_hub.core.currencies import get_currency, get_supported_codes
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
    NotLoggedInError,
    RateUnavailableError,
    ValutaTradeError,
)
from valutatrade_hub.core.utils import (
    format_amount,
    format_money,
    format_rate,
    format_timestamp,
)
from valutatrade_hub.infra.settings import SettingsLoader

PROMPT = "> "
EXIT_COMMANDS = ("exit", "quit")
SEPARATOR_LINE = "-" * 33
WELCOME_MESSAGE = (
    "Добро пожаловать в ValutaTrade Hub! "
    "Введите 'help' для списка команд, 'exit' для выхода."
)


class CommandError(Exception):
    """Ошибка разбора аргументов команды."""


class CommandParser(argparse.ArgumentParser):
    """ArgumentParser, который бросает CommandError вместо выхода из программы."""

    def error(self, message: str) -> None:
        """Преобразует ошибку argparse в CommandError с подсказкой usage."""
        raise CommandError(f"{message}\n{self.format_usage().strip()}")

    def exit(self, status: int = 0, message: str | None = None) -> None:
        """Не завершает процесс (например, после --help)."""
        if message:
            print(message, end="")
        raise CommandError("")


@dataclass
class Session:
    """Текущая сессия CLI: залогиненный пользователь (если есть)."""

    user_id: int | None = None
    username: str | None = None

    @property
    def is_logged_in(self) -> bool:
        """True, если пользователь вошёл в систему."""
        return self.user_id is not None

    def require_login(self) -> int:
        """Возвращает user_id или бросает NotLoggedInError."""
        if self.user_id is None:
            raise NotLoggedInError()
        return self.user_id


@dataclass
class Command:
    """Описание CLI-команды: парсер аргументов, обработчик и справка."""

    name: str
    help: str
    handler: Callable[[argparse.Namespace, Session], None]
    arguments: list[tuple[tuple[str, ...], dict[str, Any]]] = field(
        default_factory=list
    )

    def build_parser(self) -> CommandParser:
        """Создаёт парсер аргументов команды."""
        parser = CommandParser(prog=self.name, description=self.help, add_help=True)
        for flags, options in self.arguments:
            parser.add_argument(*flags, **options)
        return parser


# --------------------------------------------------------------------------
# Обработчики команд
# --------------------------------------------------------------------------


def handle_register(args: argparse.Namespace, session: Session) -> None:
    """register --username <str> --password <str>."""
    user = usecases.register_user(args.username, args.password)
    print(
        f"Пользователь '{user['username']}' зарегистрирован (id={user['user_id']}). "
        f"Войдите: login --username {user['username']} --password ****"
    )


def handle_login(args: argparse.Namespace, session: Session) -> None:
    """login --username <str> --password <str>."""
    user = usecases.login_user(args.username, args.password)
    session.user_id = user["user_id"]
    session.username = user["username"]
    print(f"Вы вошли как '{user['username']}'")


def handle_logout(args: argparse.Namespace, session: Session) -> None:
    """logout — завершить текущую сессию."""
    if not session.is_logged_in:
        print("Вы не вошли в систему")
        return
    print(f"Пользователь '{session.username}' вышел из системы")
    session.user_id = None
    session.username = None


def handle_show_portfolio(args: argparse.Namespace, session: Session) -> None:
    """show-portfolio [--base <str>]."""
    user_id = session.require_login()
    try:
        summary = usecases.get_portfolio_summary(user_id, args.base)
    except CurrencyNotFoundError as error:
        raise ValutaTradeError(f"Неизвестная базовая валюта '{error.code}'") from None
    base = summary["base"]
    if not summary["wallets"]:
        print(
            f"Портфель пользователя '{summary['username']}' пуст. "
            "Пополните счёт: deposit --currency USD --amount 1000"
        )
        return
    print(f"Портфель пользователя '{summary['username']}' (база: {base}):")
    for item in summary["wallets"]:
        balance = format_amount(item["balance"], item["currency"])
        print(
            f"- {item['currency']}: {balance}  → {format_money(item['value'])} {base}"
        )
    print(SEPARATOR_LINE)
    print(f"ИТОГО: {format_money(summary['total'])} {base}")
    _print_stale_warning(
        summary["is_stale"], summary["updated_at"], summary["refresh_error"]
    )


def handle_deposit(args: argparse.Namespace, session: Session) -> None:
    """deposit --currency <str> --amount <float>."""
    user_id = session.require_login()
    result = usecases.deposit(user_id, args.currency, args.amount)
    code = result["currency"]
    print(f"Пополнение выполнено: {format_amount(result['amount'], code)} {code}")
    print(
        f"- {code}: было {format_amount(result['old_balance'], code)} "
        f"→ стало {format_amount(result['new_balance'], code)}"
    )


def handle_buy(args: argparse.Namespace, session: Session) -> None:
    """buy --currency <str> --amount <float>."""
    user_id = session.require_login()
    result = usecases.buy(user_id, args.currency, args.amount)
    _print_trade(result, "Покупка выполнена", "Оценочная стоимость покупки")


def handle_sell(args: argparse.Namespace, session: Session) -> None:
    """sell --currency <str> --amount <float>."""
    user_id = session.require_login()
    result = usecases.sell(user_id, args.currency, args.amount)
    _print_trade(result, "Продажа выполнена", "Оценочная выручка")


def _print_trade(result: dict[str, Any], title: str, value_label: str) -> None:
    """Печатает итог сделки buy/sell с изменениями в портфеле."""
    code, base = result["currency"], result["base"]
    print(
        f"{title}: {format_amount(result['amount'], code)} {code} "
        f"по курсу {format_rate(result['rate'])} {base}/{code}"
    )
    print("Изменения в портфеле:")
    print(
        f"- {code}: было {format_amount(result['old_balance'], code)} "
        f"→ стало {format_amount(result['new_balance'], code)}"
    )
    print(
        f"- {base}: было {format_money(result['base_old_balance'])} "
        f"→ стало {format_money(result['base_new_balance'])}"
    )
    print(f"{value_label}: {format_money(result['cost'])} {base}")
    _print_stale_warning(
        result["is_stale"], result["updated_at"], result["refresh_error"]
    )


def handle_get_rate(args: argparse.Namespace, session: Session) -> None:
    """get-rate --from <str> --to <str>."""
    quote = usecases.get_rate(args.from_code, args.to_code)
    updated = format_timestamp(quote.updated_at) if quote.updated_at else "—"
    print(
        f"Курс {quote.from_code}→{quote.to_code}: {format_rate(quote.rate)} "
        f"(обновлено: {updated})"
    )
    print(
        f"Обратный курс {quote.to_code}→{quote.from_code}: "
        f"{format_rate(quote.inverse_rate)}"
    )
    _print_stale_warning(quote.is_stale, quote.updated_at, quote.refresh_error)


def _print_stale_warning(
    is_stale: bool, updated_at: str | None, reason: str | None = None
) -> None:
    """Предупреждает, что курсы старше TTL и обновить их не удалось."""
    if not is_stale:
        return
    ttl = SettingsLoader().get("rates_ttl_seconds")
    when = format_timestamp(updated_at) if updated_at else "неизвестно"
    details = f" Причина: {reason}." if reason else ""
    print(
        f"Внимание: курсы устарели (обновлены {when}, TTL {ttl} с) и обновить "
        f"их не удалось.{details} Выполните 'update-rates' позже."
    )


def handle_update_rates(args: argparse.Namespace, session: Session) -> None:
    """update-rates [--source coingecko|exchangerate]."""
    result = usecases.update_rates(args.source)
    if result.has_errors:
        print(
            f"Update completed with errors. Total rates updated: {result.total}. "
            "Check logs/parser.log for details."
        )
    else:
        print(
            f"Update successful. Total rates updated: {result.total}. "
            f"Last refresh: {result.last_refresh}"
        )


def handle_show_rates(args: argparse.Namespace, session: Session) -> None:
    """show-rates [--currency <str>] [--top <int>] [--base <str>]."""
    data = usecases.list_cached_rates(args.currency, args.top, args.base)
    print(f"Rates from cache (updated at {data['last_refresh']}):")
    table = PrettyTable(["Pair", "Rate", "Updated at", "Source"])
    table.align["Pair"] = "l"
    table.align["Rate"] = "r"
    for row in data["rows"]:
        updated = format_timestamp(row["updated_at"]) if row["updated_at"] else "—"
        table.add_row([row["pair"], format_rate(row["rate"]), updated, row["source"]])
    print(table)


def handle_schedule_rates(args: argparse.Namespace, session: Session) -> None:
    """schedule-rates [--interval <int>] [--runs <int>]: периодическое обновление."""
    from valutatrade_hub.parser_service.scheduler import RatesScheduler
    from valutatrade_hub.parser_service.updater import RatesUpdater

    updater = RatesUpdater()
    interval = args.interval or updater.config.UPDATE_INTERVAL_SECONDS
    scheduler = RatesScheduler(updater, interval)
    print(f"Планировщик запущен: интервал {interval} с. Остановка — Ctrl+C.")
    try:
        runs = scheduler.run(max_runs=args.runs)
    except KeyboardInterrupt:
        scheduler.stop()
        print("\nПланировщик остановлен.")
        return
    print(f"Планировщик завершён: выполнено обновлений — {runs}.")


def handle_list_currencies(args: argparse.Namespace, session: Session) -> None:
    """list-currencies — показать поддерживаемые валюты."""
    table = PrettyTable(["Code", "Info"])
    table.align["Info"] = "l"
    for code in get_supported_codes():
        table.add_row([code, get_currency(code).get_display_info()])
    print(table)


def handle_help(args: argparse.Namespace, session: Session) -> None:
    """help [command] — список команд или справка по команде."""
    if args.command:
        command = COMMANDS.get(args.command)
        if command is None:
            raise CommandError(f"Неизвестная команда '{args.command}'")
        print(command.build_parser().format_help().strip())
        return
    table = PrettyTable(["Команда", "Описание"])
    table.align = "l"
    for command in COMMANDS.values():
        table.add_row([command.name, command.help])
    table.add_row(["exit", "Выйти из программы"])
    print(table)


# --------------------------------------------------------------------------
# Реестр команд
# --------------------------------------------------------------------------

_USERNAME_ARG = (("--username",), {"required": True, "help": "Имя пользователя"})
_PASSWORD_ARG = (("--password",), {"required": True, "help": "Пароль"})
_CURRENCY_ARG = (("--currency",), {"required": True, "help": "Код валюты, напр. BTC"})
_AMOUNT_ARG = (("--amount",), {"required": True, "help": "Количество (> 0)"})

COMMANDS: dict[str, Command] = {
    command.name: command
    for command in (
        Command(
            "register",
            "Зарегистрировать пользователя",
            handle_register,
            [_USERNAME_ARG, _PASSWORD_ARG],
        ),
        Command(
            "login",
            "Войти в систему",
            handle_login,
            [_USERNAME_ARG, _PASSWORD_ARG],
        ),
        Command("logout", "Выйти из учётной записи", handle_logout),
        Command(
            "show-portfolio",
            "Показать кошельки и итоговую стоимость",
            handle_show_portfolio,
            [(("--base",), {"default": None, "help": "Базовая валюта (USD)"})],
        ),
        Command(
            "deposit",
            "Пополнить кошелёк (например, USD для покупок)",
            handle_deposit,
            [_CURRENCY_ARG, _AMOUNT_ARG],
        ),
        Command(
            "buy",
            "Купить валюту за USD",
            handle_buy,
            [_CURRENCY_ARG, _AMOUNT_ARG],
        ),
        Command(
            "sell",
            "Продать валюту за USD",
            handle_sell,
            [_CURRENCY_ARG, _AMOUNT_ARG],
        ),
        Command(
            "get-rate",
            "Получить курс одной валюты к другой",
            handle_get_rate,
            [
                (
                    ("--from",),
                    {"dest": "from_code", "required": True, "help": "Исходная валюта"},
                ),
                (
                    ("--to",),
                    {"dest": "to_code", "required": True, "help": "Целевая валюта"},
                ),
            ],
        ),
        Command(
            "update-rates",
            "Обновить курсы через Parser Service",
            handle_update_rates,
            [
                (
                    ("--source",),
                    {
                        "choices": ["coingecko", "exchangerate"],
                        "default": None,
                        "help": "Только один источник",
                    },
                )
            ],
        ),
        Command(
            "show-rates",
            "Показать курсы из локального кеша",
            handle_show_rates,
            [
                (("--currency",), {"default": None, "help": "Только эта валюта"}),
                (
                    ("--top",),
                    {
                        "type": int,
                        "default": None,
                        "help": "N самых дорогих криптовалют",
                    },
                ),
                (("--base",), {"default": None, "help": "Базовая валюта"}),
            ],
        ),
        Command(
            "schedule-rates",
            "Периодически обновлять курсы",
            handle_schedule_rates,
            [
                (
                    ("--interval",),
                    {
                        "type": int,
                        "default": None,
                        "help": "Интервал, с (по умолчанию 300)",
                    },
                ),
                (
                    ("--runs",),
                    {
                        "type": int,
                        "default": None,
                        "help": "Число запусков (по умолчанию бесконечно)",
                    },
                ),
            ],
        ),
        Command(
            "list-currencies",
            "Список поддерживаемых валют",
            handle_list_currencies,
        ),
        Command(
            "help",
            "Справка по командам",
            handle_help,
            [(("command",), {"nargs": "?", "default": None, "help": "Имя команды"})],
        ),
    )
}


# --------------------------------------------------------------------------
# Выполнение команд
# --------------------------------------------------------------------------


def _format_error(error: Exception) -> str:
    """Возвращает дружелюбное сообщение для исключения."""
    if isinstance(error, InsufficientFundsError):
        return str(error)
    if isinstance(error, CurrencyNotFoundError):
        codes = ", ".join(get_supported_codes())
        return (
            f"{error}. Поддерживаемые коды: {codes}. "
            "Подробнее: list-currencies или help get-rate"
        )
    if isinstance(error, RateUnavailableError):
        return f"{error} Проверьте сеть или выполните 'update-rates'."
    if isinstance(error, ApiRequestError):
        return f"{error}. Повторите попытку позже или проверьте подключение к сети."
    return str(error)


def execute(line: str, session: Session) -> None:
    """Разбирает и выполняет одну строку команды, печатая результат или ошибку.

    Args:
        line: Строка ввода, например "buy --currency BTC --amount 0.05".
        session: Текущая сессия (меняется командами login/logout).
    """
    try:
        tokens = shlex.split(line)
    except ValueError as error:
        print(f"Ошибка разбора команды: {error}")
        return
    if not tokens:
        return
    name, *rest = tokens
    command = COMMANDS.get(name)
    if command is None:
        print(f"Неизвестная команда '{name}'. Введите 'help' для списка команд.")
        return
    try:
        args = command.build_parser().parse_args(rest)
        command.handler(args, session)
    except CommandError as error:
        if str(error):
            print(error)
    except (ValutaTradeError, ValueError) as error:
        print(_format_error(error))


def run_repl() -> None:
    """Запускает интерактивный цикл чтения и выполнения команд."""
    session = Session()
    print(WELCOME_MESSAGE)
    while True:
        try:
            line = input(PROMPT)
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if line.strip() in EXIT_COMMANDS:
            break
        execute(line, session)
    print("До свидания!")


def main() -> None:
    """Точка входа: без аргументов — интерактивный режим, иначе одна команда.

    Пример разового запуска: project show-rates --top 2
    """
    if len(sys.argv) > 1:
        execute(shlex.join(sys.argv[1:]), Session())
        return
    run_repl()
