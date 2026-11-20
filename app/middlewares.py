from __future__ import annotations

import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.i18n import DEFAULT_LANGUAGE, t
from app.repository import Repository, display_name_of
from app.roles import Role, effective_role, permissions_for

logger = logging.getLogger(__name__)

# Answers that mean “nothing is broken”: an old button, a message that was
# deleted or closed, or a line that blinked for a second.
HARMLESS_PHRASES: tuple[str, ...] = (
    "query is too old",
    "query id is invalid",
    "callback query id is invalid",
    "message to edit not found",
    "message to delete not found",
    "message is not modified",
    "message can't be edited",
    "message can't be deleted",
    "message id invalid",
    "message to reply not found",
    "message identifier is not specified",
)


def _is_harmless(message: str) -> bool:
    lowered = message.lower()
    return any(phrase in lowered for phrase in HARMLESS_PHRASES)


def _short(exception: BaseException) -> str:
    text = str(exception).strip().replace("\n", " ")
    return text[:180]


class StaleTelegramMiddleware(BaseMiddleware):
    """Turn harmless Telegram complaints into one line and one short alert.

    Registered as the outermost callback middleware of the router, so it also
    covers the answers the handlers send at the very end of their work. Only
    the two harmless families are handled; a real bug still raises and is
    logged with its traceback, which is exactly what it deserves.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except TelegramNetworkError as exc:
            logger.warning(
                "Сеть мигнула во время ответа Telegram: %s. Бот продолжает работу.",
                _short(exc),
            )
            if isinstance(event, CallbackQuery):
                with contextlib.suppress(Exception):
                    await event.answer()
            return None
        except TelegramBadRequest as exc:
            if not _is_harmless(str(exc)):
                raise
            logger.info("Устаревшее нажатие или удалённое сообщение: %s", _short(exc))
            if isinstance(event, CallbackQuery):
                language = data.get("lang") or DEFAULT_LANGUAGE
                with contextlib.suppress(Exception):
                    await event.answer(t(language, "stale_button"), show_alert=True)
            return None


class AccessMiddleware(BaseMiddleware):
    def __init__(
        self,
        allowed_user_ids: frozenset[int],
        super_admin_ids: frozenset[int],
    ) -> None:
        self.allowed_user_ids = allowed_user_ids
        self.super_admin_ids = super_admin_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if (
            user is None
            or not self.allowed_user_ids
            or user.id in self.allowed_user_ids
            or user.id in self.super_admin_ids
        ):
            return await handler(event, data)

        text = t(DEFAULT_LANGUAGE, "access_denied", user_id=user.id)
        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer(
                t(DEFAULT_LANGUAGE, "access_denied_short"), show_alert=True
            )
            if event.message:
                await event.message.answer(text)
        return None


class UserContextMiddleware(BaseMiddleware):
    def __init__(
        self,
        repository: Repository,
        super_admin_ids: frozenset[int],
    ) -> None:
        self.repository = repository
        self.super_admin_ids = super_admin_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            data["lang"] = DEFAULT_LANGUAGE
            data["display_name"] = ""
            data["user_registered"] = False
            data["role"] = Role.DRIVER.value
            data["permissions"] = permissions_for(Role.DRIVER)
            data["is_admin"] = False
            data["is_superadmin"] = False
            return await handler(event, data)

        stored_user = await self.repository.touch_user(
            telegram_id=user.id,
            full_name=user.full_name,
            username=user.username,
        )
        is_superadmin = user.id in self.super_admin_ids
        role = effective_role(stored_user.role, is_superadmin=is_superadmin)
        data["lang"] = stored_user.language or DEFAULT_LANGUAGE
        data["display_name"] = display_name_of(stored_user) or user.full_name
        data["user_registered"] = stored_user.language is not None
        data["role"] = role.value
        data["permissions"] = permissions_for(role)
        data["is_superadmin"] = is_superadmin
        data["is_admin"] = role in {Role.ADMIN, Role.SUPERADMIN}
        return await handler(event, data)
