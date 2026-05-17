from io import BytesIO

from aiogram import F, Router
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from core.models import ProcessResult
from core.processor import FinanceProcessor, TransactionParseError
from logger import logger
from services.ai_service import AIServiceError

router = Router(name="finance")

PARSE_ERROR_TEXT = "Не разобрал запрос, введите через /set [предмет] [сумма]"
API_ERROR_TEXT = "Сервис распознавания временно недоступен. Попробуйте позже."
TXT_MAX_FILE_SIZE = 1024 * 1024
TXT_FILE_TOO_LARGE_TEXT = "Файл слишком большой. Отправьте txt до 1 МБ."
TXT_INVALID_ENCODING_TEXT = "Не удалось прочитать файл. Нужен txt в кодировке UTF-8."
TXT_EMPTY_FILE_TEXT = "Файл пустой. Добавьте строки вида: название сумма."


@router.message(F.voice)
async def voice_transaction(message: Message, processor: FinanceProcessor) -> None:
    if message.voice is None:
        return

    buffer = BytesIO()
    await message.bot.download(message.voice.file_id, destination=buffer)

    try:
        user_id = message.from_user.id if message.from_user else None
        result = await processor.process_voice(
            buffer.getvalue(),
            filename="voice.oga",
            user_id=user_id,
        )
    except TransactionParseError:
        await message.answer(PARSE_ERROR_TEXT)
        return
    except AIServiceError:
        logger.exception("AI service failed while processing voice message")
        await message.answer(API_ERROR_TEXT)
        return
    except Exception:
        logger.exception("Unexpected voice processing error")
        await message.answer("Не удалось записать операцию. Попробуйте позже.")
        return

    await _confirm(message, result)


@router.message(F.document)
async def document_transaction(message: Message, processor: FinanceProcessor) -> None:
    if message.document is None:
        return

    filename = message.document.file_name or ""
    if not filename.lower().endswith(".txt"):
        await message.answer("Поддерживаются только txt-файлы.")
        return

    if message.document.file_size is not None and message.document.file_size > TXT_MAX_FILE_SIZE:
        await message.answer(TXT_FILE_TOO_LARGE_TEXT)
        return

    buffer = BytesIO()
    await message.bot.download(message.document.file_id, destination=buffer)
    payload = buffer.getvalue()

    if len(payload) > TXT_MAX_FILE_SIZE:
        await message.answer(TXT_FILE_TOO_LARGE_TEXT)
        return

    try:
        text = payload.decode("utf-8-sig").strip()
    except UnicodeDecodeError:
        await message.answer(TXT_INVALID_ENCODING_TEXT)
        return

    if not text:
        await message.answer(TXT_EMPTY_FILE_TEXT)
        return

    status_message = await message.answer("Файл получил, обрабатываю операции…")

    try:
        user_id = message.from_user.id if message.from_user else None
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            result = await processor.process_text(text, user_id=user_id)
    except TransactionParseError:
        await status_message.edit_text(PARSE_ERROR_TEXT)
        return
    except AIServiceError:
        logger.exception("AI service failed while processing txt document")
        await status_message.edit_text(API_ERROR_TEXT)
        return
    except Exception:
        logger.exception("Unexpected txt document processing error")
        await status_message.edit_text("Не удалось записать операции из файла. Попробуйте позже.")
        return

    await status_message.edit_text(_confirmation_text(result))


@router.message(F.text)
async def text_transaction(message: Message, processor: FinanceProcessor) -> None:
    if not message.text or message.text.startswith("/"):
        return
    await handle_text_transaction(message, message.text, processor)


async def handle_text_transaction(
    message: Message,
    text: str,
    processor: FinanceProcessor,
) -> None:
    try:
        user_id = message.from_user.id if message.from_user else None
        result = await processor.process_text(text, user_id=user_id)
    except TransactionParseError:
        await message.answer(PARSE_ERROR_TEXT)
        return
    except AIServiceError:
        logger.exception("AI service failed while processing text message")
        await message.answer(API_ERROR_TEXT)
        return
    except Exception:
        logger.exception("Unexpected text processing error")
        await message.answer("Не удалось записать операцию. Попробуйте позже.")
        return

    await _confirm(message, result)


async def _confirm(message: Message, result: ProcessResult) -> None:
    await message.answer(_confirmation_text(result))


def _confirmation_text(result: ProcessResult) -> str:
    if len(result.transactions) == 1:
        transaction = result.transaction
        amount_text = f"{transaction.amount:g}"
        return f"Записал: {transaction.category} — {amount_text} руб."

    total_text = f"{result.total_amount:g}"
    return f"Записал операций: {len(result.transactions)} на {total_text} руб."
