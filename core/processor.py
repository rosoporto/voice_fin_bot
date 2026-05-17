from datetime import UTC, datetime

from core.category_rules import should_override_category
from core.models import ProcessResult, Transaction
from logger import logger
from services.ai_service import AIService, AIServiceError
from services.analytics_db import SQLiteAnalyticsService
from services.gsheets import GSheetsService
from services.redis_db import RedisCategoryService


class TransactionParseError(Exception):
    pass


class FinanceProcessor:
    def __init__(
        self,
        ai_service: AIService,
        sheets_service: GSheetsService,
        redis_service: RedisCategoryService,
        analytics_service: SQLiteAnalyticsService,
    ) -> None:
        self.ai_service = ai_service
        self.sheets_service = sheets_service
        self.redis_service = redis_service
        self.analytics_service = analytics_service

    async def initialize(self) -> None:
        await self.analytics_service.init_db()
        logger.info("Initializing Google Sheets and category cache")
        await self.sheets_service.ensure_schema()
        categories = await self.sheets_service.get_categories()
        try:
            await self.redis_service.replace_categories(categories)
        except Exception:
            logger.exception("Redis is unavailable during startup; continuing without cache")

    async def clear_storage(self, user_id: int | None = None) -> None:
        logger.warning("Clearing finance storage requested user_id={}", user_id)
        await self.sheets_service.clear_all()
        await self.analytics_service.clear()
        try:
            await self.redis_service.clear_categories()
        except Exception:
            logger.exception("Redis is unavailable while clearing categories")
        logger.warning("Finance storage cleared user_id={}", user_id)

    async def refresh_category_cache(self, user_id: int | None = None) -> set[str]:
        logger.info("Refreshing category cache requested user_id={}", user_id)
        categories = await self.sheets_service.get_categories()
        await self.redis_service.replace_categories(categories)
        logger.info(
            "Category cache refreshed user_id={} count={}",
            user_id,
            len(categories),
        )
        return categories

    async def process_voice(
        self,
        audio: bytes,
        filename: str = "voice.oga",
        user_id: int | None = None,
    ) -> ProcessResult:
        text = await self.ai_service.transcribe_audio(audio=audio, filename=filename)
        logger.info("Voice transcription user_id={} text={!r}", user_id, text)
        return await self.process_text(text, user_id=user_id)

    async def process_text(self, raw_text: str, user_id: int | None = None) -> ProcessResult:
        text = raw_text.strip()
        if not text:
            raise TransactionParseError("Empty transaction text")

        logger.info("Transaction input user_id={} text={!r}", user_id, text)
        categories = await self._get_categories()
        parsed_batch = await self.ai_service.parse_transaction(text=text, categories=categories)
        parsed_transactions = parsed_batch.complete_transactions
        if not parsed_transactions:
            logger.info("LLM could not parse transaction: {}", text)
            raise TransactionParseError("Incomplete transaction")

        now = datetime.now(UTC)
        transactions: list[Transaction] = []
        new_categories: list[str] = []
        known_categories = set(categories)

        for parsed in parsed_transactions:
            category = parsed.category
            item_text = parsed.raw_text or text
            category_override = should_override_category(category, item_text, source_text=text)
            if category_override is not None:
                logger.info(
                    "Category overridden user_id={} old={} new={} text={!r}",
                    user_id,
                    category,
                    category_override,
                    item_text,
                )
                category = category_override

            transaction = Transaction(
                timestamp=now,
                amount=parsed.amount,
                category=category,
                type=parsed.type,
                raw_text=parsed.raw_text or self._fallback_raw_text(category, parsed.amount),
            )
            transactions.append(transaction)

            if transaction.category not in known_categories:
                new_categories.append(transaction.category)
                known_categories.add(transaction.category)

        # fix #2: save transactions first — category sync is best-effort
        await self.sheets_service.append_transactions(transactions)

        try:
            await self.analytics_service.save_transactions(transactions)
        except Exception:
            logger.exception("SQLite analytics write failed")

        created_categories: list[str] = []
        for category in new_categories:
            try:
                await self._add_category(category)
                created_categories.append(category)
            except Exception:
                logger.exception("Failed to sync category {!r} to sheets/redis", category)

        logger.info(
            "Transactions saved count={} total={} categories={}",
            len(transactions),
            sum(transaction.amount for transaction in transactions),
            [transaction.category for transaction in transactions],
        )
        return ProcessResult(transactions=transactions, categories_created=created_categories)

    async def _get_categories(self) -> set[str]:
        try:
            return await self.redis_service.get_categories()
        except Exception:
            logger.exception("Redis is unavailable; reading categories from Google Sheets")
            return await self.sheets_service.get_categories()

    async def _add_category(self, category: str) -> None:
        await self.sheets_service.add_category(category)
        try:
            await self.redis_service.add_category(category)
        except Exception:
            logger.exception("Redis is unavailable; category saved only to Google Sheets")

    @staticmethod
    def _fallback_raw_text(category: str, amount: float) -> str:
        amount_text = f"{amount:g}"
        return f"{category} {amount_text} руб."
