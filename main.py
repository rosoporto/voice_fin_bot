import asyncio

from aiogram import Bot, Dispatcher

from config import get_settings
from core.processor import FinanceProcessor
from handlers.commands import router as commands_router
from handlers.finance import router as finance_router
from logger import logger, setup_logging
from middlewares.services_mw import AccessControlMiddleware, ServicesMiddleware
from services.ai_service import AIService
from services.analytics_db import SQLiteAnalyticsService
from services.gsheets import GSheetsService
from services.redis_db import RedisCategoryService


async def _initialize_with_retry(
    processor: FinanceProcessor,
    *,
    max_attempts: int = 5,
    base_delay: float = 2.0,
) -> None:
    delay = base_delay
    for attempt in range(1, max_attempts + 1):
        try:
            await processor.initialize()
            logger.info("Initialized on attempt {}", attempt)
            return
        except Exception:
            if attempt == max_attempts:
                logger.error("Initialization failed after {} attempts, giving up", max_attempts)
                raise
            logger.warning(
                "Initialization attempt {}/{} failed, retrying in {}s",
                attempt,
                max_attempts,
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_file)

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    ai_service = AIService(
        api_key=settings.openrouter_api_key,
        base_url=str(settings.openrouter_base_url),
        chat_model=settings.openrouter_chat_model,
        whisper_model=settings.openrouter_whisper_model,
        transcription_language=settings.openrouter_transcription_language,
        site_url=settings.openrouter_site_url,
        app_name=settings.openrouter_app_name,
    )
    sheets_service = GSheetsService(
        service_account_file=str(settings.google_service_account_file),
        spreadsheet_id=settings.google_spreadsheet_id,
        transactions_sheet=settings.google_transactions_sheet,
        categories_sheet=settings.google_categories_sheet,
    )
    redis_service = RedisCategoryService(
        redis_url=settings.redis_url,
        categories_key=settings.redis_categories_key,
    )
    analytics_service = SQLiteAnalyticsService(db_path=settings.analytics_db_file)
    processor = FinanceProcessor(
        ai_service=ai_service,
        sheets_service=sheets_service,
        redis_service=redis_service,
        analytics_service=analytics_service,
    )

    if not settings.allowed_user_id_set:
        logger.warning("ALLOWED_USER_IDS is empty; all Telegram users will be blocked")

    access_middleware = AccessControlMiddleware(settings.allowed_user_id_set)
    service_middleware = ServicesMiddleware(
        processor=processor,
        clear_confirmations={},
        analytics=analytics_service,
    )
    dp.message.outer_middleware(access_middleware)
    dp.message.outer_middleware(service_middleware)
    dp.callback_query.outer_middleware(access_middleware)
    dp.callback_query.outer_middleware(service_middleware)
    dp.workflow_data.update(processor=processor, analytics=analytics_service)

    dp.include_router(commands_router)
    dp.include_router(finance_router)

    try:
        await _initialize_with_retry(processor)
        logger.info("Bot polling started")
        await dp.start_polling(bot)
    finally:
        logger.info("Bot shutdown started")
        await ai_service.close()
        await redis_service.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
