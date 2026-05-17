from secrets import token_urlsafe

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from core.models import TransactionType
from core.processor import FinanceProcessor
from handlers.finance import handle_text_transaction
from logger import logger
from services.analytics_db import SQLiteAnalyticsService

router = Router(name="commands")

CLEAR_CONFIRM = "clear_table:confirm"
CLEAR_CANCEL = "clear_table:cancel"
CLEAR_TOKEN_KEY = "clear_table_token"


@router.message(Command("start", "help"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Отправьте голосовое сообщение с тратой или доходом. "
        "Для текста используйте /set кофе 250. "
        "Можно также отправить txt-файл со строками вида «название сумма».\n"
        "Аналитика: /stats — расходы по категориям, /balance — баланс.\n"
        "Категории: /refresh_categories — перечитать справочник из таблицы."
    )


@router.message(Command("set"))
async def cmd_set(
    message: Message,
    command: CommandObject,
    processor: FinanceProcessor,
) -> None:
    if not command.args:
        await message.answer("Введите операцию так: /set кофе 250")
        return
    await handle_text_transaction(message, command.args, processor)


@router.message(Command("stats"))
async def cmd_stats(message: Message, analytics: SQLiteAnalyticsService) -> None:
    expenses = await analytics.get_category_stats(TransactionType.expense)
    if not expenses:
        await message.answer("Расходов пока нет.")
        return

    lines = ["Расходы по категориям:\n"]
    for category, total in expenses:
        lines.append(f"  {category} — {total:,.0f} ₽".replace(",", " "))

    totals = await analytics.get_totals()
    lines.append(f"\nИтого расходы: {totals['expense']:,.0f} ₽".replace(",", " "))
    if totals["income"] > 0:
        lines.append(f"Итого доходы:  {totals['income']:,.0f} ₽".replace(",", " "))

    await message.answer("\n".join(lines))


@router.message(Command("balance"))
async def cmd_balance(message: Message, analytics: SQLiteAnalyticsService) -> None:
    totals = await analytics.get_totals()
    income = totals["income"]
    expense = totals["expense"]
    balance = income - expense
    sign = "+" if balance >= 0 else ""
    await message.answer(
        f"Доходы:  {income:,.0f} ₽\n"
        f"Расходы: {expense:,.0f} ₽\n"
        f"Баланс:  {sign}{balance:,.0f} ₽".replace(",", " ")
    )


@router.message(Command("refresh_categories"))
async def cmd_refresh_categories(message: Message, processor: FinanceProcessor) -> None:
    user_id = message.from_user.id if message.from_user else None
    try:
        categories = await processor.refresh_category_cache(user_id=user_id)
    except Exception:
        logger.exception("Failed to refresh category cache user_id={}", user_id)
        await message.answer("Не удалось обновить кэш категорий.")
        return

    await message.answer(f"Кэш категорий обновлён: {len(categories)} шт.")


@router.message(Command("clear"))
async def cmd_clear(message: Message, clear_confirmations: dict[int, str]) -> None:
    user_id = message.from_user.id if message.from_user else None
    if user_id is None:
        await message.answer("Не удалось определить пользователя.")
        return

    token = token_urlsafe(12)
    clear_confirmations[user_id] = token
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Очистить таблицу", callback_data=f"{CLEAR_CONFIRM}:{token}"),
                InlineKeyboardButton(text="Отмена", callback_data=f"{CLEAR_CANCEL}:{token}"),
            ]
        ]
    )
    await message.answer(
        "Очистить листы «Транзакции» и «Справочник»? Данные будут удалены.",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith(f"{CLEAR_CANCEL}:"))
async def clear_cancel(callback: CallbackQuery, clear_confirmations: dict[int, str]) -> None:
    if not _is_active_clear_token(callback, clear_confirmations):
        await _answer_stale_clear(callback)
        return
    if callback.from_user:
        clear_confirmations.pop(callback.from_user.id, None)
    await callback.answer("Отменено")
    if callback.message:
        await callback.message.edit_text("Очистка отменена.")


@router.callback_query(F.data.startswith(f"{CLEAR_CONFIRM}:"))
async def clear_confirm(
    callback: CallbackQuery,
    processor: FinanceProcessor,
    clear_confirmations: dict[int, str],
) -> None:
    if not _is_active_clear_token(callback, clear_confirmations):
        await _answer_stale_clear(callback)
        return

    user_id = callback.from_user.id if callback.from_user else None
    try:
        await processor.clear_storage(user_id=user_id)
    except Exception:
        logger.exception("Failed to clear finance storage user_id={}", user_id)
        await callback.answer("Не удалось очистить таблицу", show_alert=True)
        return

    if user_id is not None:
        clear_confirmations.pop(user_id, None)
    await callback.answer("Таблица очищена")
    if callback.message:
        await callback.message.edit_text("Таблица очищена. Заголовки оставлены.")


def _is_active_clear_token(
    callback: CallbackQuery,
    clear_confirmations: dict[int, str],
) -> bool:
    if not callback.data or not callback.from_user:  # fix #4: guard on from_user
        return False
    token = callback.data.rsplit(":", maxsplit=1)[-1]
    return token == clear_confirmations.get(callback.from_user.id)


async def _answer_stale_clear(callback: CallbackQuery) -> None:
    await callback.answer("Это старое подтверждение уже не действует", show_alert=True)
    if callback.message:
        await callback.message.edit_text("Это подтверждение устарело. Введите /clear заново.")
