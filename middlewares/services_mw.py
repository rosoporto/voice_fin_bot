from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from logger import logger


class ServicesMiddleware(BaseMiddleware):
    def __init__(self, **services: Any) -> None:
        self.services = services

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data.update(self.services)
        return await handler(event, data)


class AccessControlMiddleware(BaseMiddleware):
    def __init__(self, allowed_user_ids: set[int]) -> None:
        self.allowed_user_ids = allowed_user_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
            answer = event.answer
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None
            answer = event.answer
        else:
            return await handler(event, data)

        if user_id is not None and user_id in self.allowed_user_ids:
            return await handler(event, data)

        logger.warning("Unauthorized Telegram user blocked user_id={}", user_id)
        await answer("Доступ запрещен.")
        return None
