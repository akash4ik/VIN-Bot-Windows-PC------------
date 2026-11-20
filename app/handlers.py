from __future__ import annotations

import asyncio
import contextlib
import html
import io
import logging
import math
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
    PhotoSize,
)

from app.archive import ARCHIVE_KIND_CARD, ARCHIVE_KIND_PAINT, ArchiveService
from app.backup_service import (
    BackupError,
    create_snapshot,
    decompress,
    format_size,
    list_snapshots,
    restore_snapshot,
    rotate_snapshots,
    split_for_telegram,
    table_counts,
    validate_sqlite,
)
from app.config import Config
from app.database import AuditAction, PaintCard, PaintStatus, VehicleCard
from app.i18n import all_labels, t
from app.keyboards import (
    admin_delete_confirm_keyboard,
    admin_panel_keyboard,
    admin_users_keyboard,
    archive_status_keyboard,
    backup_apply_keyboard,
    backup_import_keyboard,
    backup_menu_keyboard,
    cancel_menu,
    card_keyboard,
    delete_confirmation_keyboard,
    journal_keyboard,
    language_keyboard,
    main_menu,
    manual_keyboard,
    paint_card_keyboard,
    paint_menu_keyboard,
    paint_take_keyboard,
    paint_vin_confirmation_keyboard,
    second_reader_keyboard,
    snapshot_confirm_keyboard,
    snapshot_keyboard,
    trash_keyboard,
    trash_list_keyboard,
    trash_search_keyboard,
    vin_confirmation_keyboard,
    vin_fix_keyboard,
    vin_replace_keyboard,
    vin_source_keyboard,
)
from app.manual import ADMIN, WORKER, is_valid_page, manual_text
from app.middlewares import StaleTelegramMiddleware
from app.ocr import (
    SHAKY_CONFIDENCE,
    VIN_ALPHABET,
    VIN_LENGTH,
    OCRResult,
    OCRService,
    OCRUnavailableError,
    is_fixable_vin,
    is_valid_vin,
    is_valid_vin_fragment,
    judged_vin,
    mask_vin,
    parse_manual_card_vin,
    parse_search_query,
    unsure_positions,
    vin_check_digit_is_wrong,
    vin_check_digit_matches,
)
from app.repository import Repository, display_name_of, normalize_paint_status
from app.roles import (
    Role,
    can_assign_role,
    can_delete_user,
    can_rename_user,
    effective_role,
    normalize_stored_role,
    permissions_for,
)
from app.vin_gemini import (
    DEFAULT_MODEL,
    GeminiSettings,
    probe_key,
    read_with_gemini,
)
from app.vin_report import UNREADABLE, ReadingReport, build_report

logger = logging.getLogger(__name__)
ADMIN_USERS_PAGE_SIZE = 8
MAX_PHOTO_BYTES = 10 * 1024 * 1024
DISPLAY_NAME_MIN_LENGTH = 2
DISPLAY_NAME_MAX_LENGTH = 64


def local_reading_is_uncertain(result, report) -> bool:
    """Whether the local engine left something worth asking the cloud about.

    The cloud costs money per photograph, so it is only asked where the
    local reading is in trouble: nothing found, a character it could not
    make out, a photograph worth reshooting, or a code whose ninth
    character does not add up. A clean reading stays local.
    """

    if not result.vin or not result.suffix6:
        return True
    if report.partial_vin and UNREADABLE in report.partial_vin:
        return True
    if report.need_retake:
        return True
    # A reading the engine itself calls shaky is worth a second look,
    # however well the arithmetic came out. One photograph was read at
    # nine per cent, passed the check digit by luck and was handed to the
    # person while the correct code sat in the journal.
    if result.confidence is not None and result.confidence < SHAKY_CONFIDENCE:
        return True
    return vin_check_digit_is_wrong(result.vin)


def cloud_beats_local(reading, result, report) -> bool:
    """Whether the cloud's code should be handed on instead of the local one.

    Confidence against confidence. A local reading with something wrong
    with it is always worth replacing. Otherwise the two are weighed: the
    engine's own number against how sure the model said it was, and the
    surer one is handed to the person. A code the engine read once at nine
    per cent no longer outranks a code the cloud was ninety-five per cent
    sure of.
    """

    if local_reading_is_uncertain(result, report):
        return True
    local_confidence = float(result.confidence or 0.0)
    cloud_confidence = float(reading.confidence or 0.0) * 100.0
    return cloud_confidence > local_confidence + CLOUD_WINS_BY

#: How much surer the cloud has to be before its code replaces the local one.
#:
#: Both sides report how sure they are, the engine as a percentage and the
#: model as a fraction, and the surer one should win. The margin stops the two
#: trading places over a rounding difference: a cloud that is a hair surer
#: than a reading the engine is happy with is not worth overriding it for.
CLOUD_WINS_BY = 5.0


class CreateCardStates(StatesGroup):
    vehicle_photo = State()
    invoice_photo = State()
    vin_photo = State()
    manual_vin = State()
    confirming = State()


class SearchStates(StatesGroup):
    query = State()


class PaintCreateStates(StatesGroup):
    """Handing a vehicle over for painting: vehicle photo + VIN photo only."""

    vehicle_photo = State()
    vin_photo = State()
    manual_vin = State()
    confirming = State()


class PaintSearchStates(StatesGroup):
    query = State()


class RenameUserStates(StatesGroup):
    """Waiting for the new name an administrator gives to a user."""

    name = State()


class BackupStates(StatesGroup):
    """Waiting for a database file the administrator wants to inject."""

    waiting_file = State()
    confirming = State()


class TrashSearchStates(StatesGroup):
    """Waiting for the VIN or name to look for in the bin."""

    query = State()


def clean_display_name(value: str) -> str | None:
    """Return the sanitised name an administrator assigns to a user.

    Control characters are dropped, repeated whitespace is collapsed and the
    result must stay between 2 and 64 characters with at least one letter or
    digit, so the administrator list cannot be filled with empty or junk names.
    """

    cleaned = " ".join(
        "".join(
            character if character.isprintable() or character.isspace() else " "
            for character in value
        ).split()
    )
    if not DISPLAY_NAME_MIN_LENGTH <= len(cleaned) <= DISPLAY_NAME_MAX_LENGTH:
        return None
    if not any(character.isalnum() for character in cleaned):
        return None
    return cleaned


def build_router(
    config: Config,
    repository: Repository,
    ocr: OCRService,
    *,
    archive: ArchiveService | None = None,
) -> Router:
    router = Router(name="vin-bot")
    # Outermost: catches the answers the handlers send at the very end of their
    # work, the ones that used to print a forty line traceback for an old
    # button and leave the person staring at a dead keyboard.
    router.callback_query.outer_middleware(StaleTelegramMiddleware())
    router.message.outer_middleware(StaleTelegramMiddleware())
    # The scheduler in app.main keeps the same instance so the daily digest and
    # the card mirroring share one channel client.
    archive = archive or ArchiveService(config, repository)

    # Second reader in the cloud. Built once from the same .env the bot token
    # comes from; without a key it stays silent and every photograph is read
    # locally, which is how the bot has always worked.
    second_reader = GeminiSettings(
        api_key=config.gemini_api_key,
        model=config.gemini_model or DEFAULT_MODEL,
        mode=config.gemini_mode,
        timeout=config.gemini_timeout,
        proxy=config.gemini_proxy,
    )
    if second_reader.enabled:
        logger.info(
            "Второй читатель включён: %s, режим %s",
            second_reader.model,
            second_reader.mode,
        )

    async def remember_creation(bot, card, *, kind: str, owner: str) -> None:
        """Journal entry plus a permanent copy in the archive channel.

        Both steps are optional: a problem here must never stop the card from
        being saved, therefore every error is only logged.
        """

        with contextlib.suppress(Exception):
            await repository.add_audit(
                actor_id=card.owner_id,
                actor_name=owner,
                action=AuditAction.CARD_CREATED,
                details=f"#{card.id} {card.vin_full or card.vin_suffix6}",
            )
        with contextlib.suppress(Exception):
            await archive.mirror_card(bot, card, kind=kind, owner=owner)

    def safe_role(value: str | Role) -> Role:
        try:
            return Role(value)
        except ValueError:
            return Role.DRIVER

    def role_name(language: str, role: str | Role) -> str:
        return t(language, f"role_{safe_role(role).value}")

    def can_delete(role: str | Role) -> bool:
        return permissions_for(safe_role(role)).can_delete_cards

    def can_open_card(card: VehicleCard, user_id: int, role: str | Role) -> bool:
        return (
            permissions_for(safe_role(role)).can_view_cards or card.owner_id == user_id
        )

    def photo_validation_error(
        photo: PhotoSize, *, vin_crop: bool = False
    ) -> str | None:
        if photo.file_size is not None and photo.file_size > MAX_PHOTO_BYTES:
            return "photo_too_large"
        short_side, long_side = sorted((photo.width, photo.height))
        minimum_short = 50 if vin_crop else 240
        minimum_long = 160 if vin_crop else 320
        if short_side < minimum_short or long_side < minimum_long:
            return "vin_photo_too_small" if vin_crop else "photo_too_small"
        return None

    async def reject_message_for_role(
        message: Message, state: FSMContext, language: str, role: str | Role
    ) -> None:
        await state.clear()
        await message.answer(
            t(language, "role_forbidden"),
            reply_markup=main_menu(language, role=safe_role(role)),
        )

    async def reject_callback_for_role(callback: CallbackQuery, language: str) -> None:
        await callback.answer(t(language, "role_forbidden"), show_alert=True)

    def card_caption(
        card: VehicleCard,
        language: str,
        *,
        position: int | None = None,
        total: int | None = None,
    ) -> str:
        created_at = card.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        local_date = created_at.astimezone(config.timezone).strftime("%d.%m.%Y %H:%M")
        owner = html.escape(card.owner_name or str(card.owner_id))
        masked = mask_vin(card.vin_full, card.vin_suffix6)
        lines = [
            t(language, "card_title", card_id=card.id),
            t(language, "card_vin", masked_vin=masked),
            t(
                language,
                "card_search_keys",
                suffix6=card.vin_suffix6,
                suffix4=card.vin_suffix6[-4:],
            ),
            t(language, "card_owner", owner=owner),
            t(language, "card_date", date=local_date),
        ]
        if position is not None and total is not None:
            lines.append(t(language, "card_position", position=position, total=total))
        return "\n".join(lines)

    async def send_card(
        message: Message,
        card: VehicleCard,
        language: str,
        *,
        mode: str,
        query: str,
        offset: int,
        total: int,
        viewer_role: str | Role,
    ) -> None:
        await message.answer_photo(
            photo=card.vehicle_photo_file_id,
            caption=card_caption(card, language, position=offset + 1, total=total),
            reply_markup=card_keyboard(
                language,
                mode=mode,
                query=query,
                offset=offset,
                total=total,
                card_id=card.id,
                can_delete=can_delete(viewer_role),
                has_invoice=bool(card.invoice_photo_file_id),
            ),
        )

    def remembered_observations(
        observations: tuple[tuple[str, float], ...] | list[tuple[str, float]],
    ) -> list[list]:
        """Keep the codes the engine saw, trimmed small enough for the state.

        Only whole seventeen-character codes are worth keeping, and only the
        first two hundred: they are carried along so that the person can be
        shown which characters the camera read two ways.
        """

        kept = [
            [text, float(confidence or 0.0)]
            for text, confidence in observations
            if isinstance(text, str) and len(text) == VIN_LENGTH
        ]
        return kept[:200]

    async def offer_fix_board(
        target: Message, state: FSMContext, language: str, *, prefix: str
    ) -> None:
        """Show the seventeen characters and ask which one is wrong."""

        data = await state.get_data()
        vin = data.get("vin_full")
        if not isinstance(vin, str) or not is_fixable_vin(vin):
            await target.answer(t(language, "operation_expired"))
            return
        unsure = unsure_positions(
            vin, tuple(tuple(item) for item in data.get("vin_observations") or ())
        )
        await target.answer(
            t(language, "ocr_fix_which"),
            reply_markup=vin_fix_keyboard(language, vin, prefix=prefix, unsure=unsure),
        )

    async def offer_replacements(
        target: Message,
        state: FSMContext,
        language: str,
        *,
        prefix: str,
        index: int,
    ) -> None:
        """Show what the chosen character could be instead."""

        data = await state.get_data()
        vin = data.get("vin_full")
        if not isinstance(vin, str) or not is_fixable_vin(vin):
            await target.answer(t(language, "operation_expired"))
            return
        if not 0 <= index < VIN_LENGTH:
            await target.answer(t(language, "operation_expired"))
            return
        current = vin[index]
        # Characters another reading of the same picture saw here come first:
        # the plate said something and the camera heard it differently.
        unsure = unsure_positions(
            vin, tuple(tuple(item) for item in data.get("vin_observations") or ())
        )
        seen_here = [char for char in unsure.get(index, []) if char != current]
        # Then the ones the arithmetic allows. The ninth character is worked
        # out from the other sixteen, so only about one character in eleven
        # keeps the code consistent — a short row, and usually the right one.
        fits = [
            char
            for char in VIN_ALPHABET
            if char != current
            and vin_check_digit_matches(vin[:index] + char + vin[index + 1 :])
        ]
        suggestions = seen_here + [c for c in fits if c not in seen_here]
        lines = [t(language, "ocr_fix_replace", position=index + 1, current=current)]
        # If exactly one character keeps the code consistent, say so out
        # loud rather than only marking it: on the form this all started
        # with, the ninth character is the only one that can be wrong and
        # «4» is the only character that fits there — and that is the answer.
        if len(fits) == 1:
            lines.append(
                t(
                    language,
                    "ocr_fix_hint",
                    position=index + 1,
                    current=current,
                    fixed=fits[0],
                )
            )
        await target.answer(
            "\n\n".join(lines),
            reply_markup=vin_replace_keyboard(
                language,
                prefix=prefix,
                index=index,
                current=current,
                suggestions=suggestions,
            ),
        )

    async def show_partial_reading(
        target: Message,
        state: FSMContext,
        language: str,
        vin: str,
        *,
        prefix: str,
        manual_state,
    ) -> None:
        """A code with gaps in it: read what was readable, ask for the rest."""

        gaps = [index + 1 for index, char in enumerate(vin) if char == UNREADABLE]
        await state.update_data(vin_full=vin, vin_suffix6=None)
        await state.set_state(manual_state)
        await target.answer(
            t(
                language,
                "ocr_partial",
                positions=", ".join(str(i) for i in gaps),
                vin=vin,
            ),
            reply_markup=vin_fix_keyboard(
                language,
                vin,
                prefix=prefix,
                unsure={index - 1: [] for index in gaps},
            ),
        )

    async def apply_character_fix(
        target: Message,
        state: FSMContext,
        language: str,
        *,
        index: int,
        char: str,
        confirming_state,
        manual_state,
        show_confirmation,
        prefix: str,
    ) -> None:
        """Put the chosen character in place and show the code again."""

        data = await state.get_data()
        vin = data.get("vin_full")
        if not isinstance(vin, str) or not is_fixable_vin(vin):
            await target.answer(t(language, "operation_expired"))
            return
        fixed = vin[:index] + char + vin[index + 1 :]
        await state.update_data(vin_full=fixed)
        # Still carrying gaps? Then the code is not finished, and offering it
        # as a reading would be pretending the camera had read all of it.
        if UNREADABLE in fixed:
            await show_partial_reading(
                target, state, language, fixed, prefix=prefix, manual_state=manual_state
            )
            return
        await state.update_data(vin_suffix6=fixed[-6:])
        await target.answer(
            t(language, "ocr_fix_done", position=index + 1, char=char, vin=fixed)
        )
        await show_confirmation(
            target,
            state,
            language,
            vin_full=fixed,
            suffix6=fixed[-6:],
            confidence=data.get("ocr_confidence"),
        )
        await state.set_state(confirming_state)

    def _recognize_with_report(image_bytes: bytes, language: str):
        # One reading, not two: the report is built from what the engine just
        # saw. Reading the picture again would double the wait for nothing.
        result = ocr.recognize(image_bytes)
        return result, build_report(
            image_bytes,
            language=language,
            vin=result.vin,
            observations=result.observations,
        )

    async def download_telegram_file(bot: Bot, file_id: str) -> bytes:
        buffer = io.BytesIO()
        await bot.download(file_id, destination=buffer)
        return buffer.getvalue()

    async def recognize_photo(bot: Bot, file_id: str):
        image_bytes = await download_telegram_file(bot, file_id)
        return await asyncio.to_thread(ocr.recognize, image_bytes)

    async def ask_cloud_first(
        image_bytes: bytes, language: str
    ) -> tuple[object, ReadingReport, str]:
        """Let the cloud read the photograph first, before the local engine.

        Only a code that proves itself is handed on: seventeen characters,
        only letters a VIN may hold, and a ninth character that adds up from
        the other sixteen. Anything else — no answer, a half-read code, a
        code that does not add up — leaves the local engine to do the work,
        exactly as it always has.
        """

        reading = await read_with_gemini(
            image_bytes,
            api_key=second_reader.api_key,
            model=second_reader.model,
            timeout=second_reader.timeout,
        )
        if reading is None or not reading.believable:
            logger.info(
                "Второй читатель не дал годного кода: %s",
                reading.raw[:200] if reading else "ответа нет",
            )
            return None, None, ""

        result = OCRResult(
            vin=reading.vin,
            suffix6=reading.vin[-6:],
            confidence=None,
            raw_text=reading.raw,
            observations=((reading.vin, 1.0),),
        )
        report = build_report(
            image_bytes,
            language=language,
            vin=result.vin,
            observations=result.observations,
        )
        return result, report, t(language, "ocr_cloud_read")

    async def ask_second_reader(
        image_bytes: bytes, language: str, result, report
    ) -> tuple[object, ReadingReport, str]:
        """One question to the cloud, taken only if it proves itself.

        Nothing the model says is believed on its word. Its answer has to be
        seventeen characters long, use only characters a VIN may contain and
        have a ninth character that adds up from the other sixteen. Failing
        that, the local reading stands and the person is told what the cloud
        saw, so a half-read code can still be finished by hand.
        """

        reading = await read_with_gemini(
            image_bytes,
            api_key=second_reader.api_key,
            model=second_reader.model,
            timeout=second_reader.timeout,
        )
        if reading is None:
            return result, report, ""
        logger.info("Второй читатель: %s", reading.raw)

        if reading.believable and reading.vin != result.vin:
            if result.vin:
                note = t(
                    language,
                    "ocr_second_opinion_differs",
                    vin=reading.vin,
                    local=result.vin,
                )
                # A settled local reading outranks a lone cloud answer only
                # while it is the surer of the two. A code that merely adds up
                # is not evidence: one line of noise in eleven adds up by
                # chance, and that is exactly what reached the person.
                if not cloud_beats_local(reading, result, report):
                    return result, report, note
            else:
                note = t(language, "ocr_second_opinion_took", vin=reading.vin)
            adopted = OCRResult(
                vin=reading.vin,
                suffix6=reading.vin[-6:],
                confidence=None,
                raw_text=reading.raw,
                observations=((reading.vin, 1.0),),
            )
            fresh = build_report(
                image_bytes,
                language=language,
                vin=adopted.vin,
                observations=adopted.observations,
            )
            return adopted, fresh, note
        if reading.believable:
            return (
                result,
                report,
                t(language, "ocr_second_opinion_agrees", vin=reading.vin),
            )
        if reading.partial:
            return (
                result,
                report,
                t(language, "ocr_second_opinion_partial", partial=reading.partial),
            )
        return result, report, ""

    async def read_and_report(
        bot: Bot, file_id: str, language: str
    ) -> tuple[object, ReadingReport, str]:
        """Read the photograph and give the whole account of it.

        The report carries what the prompt he brought asks for: every
        candidate, the characters the camera could not make out, how bad the
        photograph itself is, and what to do about it. It is written to the
        journal in full, so a reading can be looked into afterwards.

        The third value is a line for the person, when the second reader in
        the cloud was asked and had something to say.
        """

        image_bytes = await download_telegram_file(bot, file_id)

        if second_reader.cloud_reads_first:
            # He asked for one reader that is not bothered by glare, dirt or a
            # code etched into glass — so in this mode the photograph goes to
            # the cloud before anything else runs, and the local engine is
            # only asked when the cloud came back with nothing usable. On a
            # hard picture this is also faster: it is no longer read twice,
            # once slowly by each.
            with contextlib.suppress(Exception):
                cloud_result, cloud_report, note = await ask_cloud_first(
                    image_bytes, language
                )
                if cloud_result is not None:
                    logger.info("Отчёт распознавания: %s", cloud_report.as_json())
                    return cloud_result, cloud_report, note

        result, report = await asyncio.to_thread(
            _recognize_with_report, image_bytes, language
        )
        note = ""
        if second_reader.enabled and (
            not second_reader.only_when_unsure
            or local_reading_is_uncertain(result, report)
        ):
            with contextlib.suppress(Exception):
                # The cloud is a luxury. Any trouble reaching it is logged and
                # the local reading is used, exactly as before it existed.
                result, report, note = await ask_second_reader(
                    image_bytes, language, result, report
                )
        logger.info("Отчёт распознавания: %s", report.as_json())
        return result, report, note

    async def show_vin_confirmation(
        message: Message,
        state: FSMContext,
        language: str,
        *,
        vin_full: str | None,
        suffix6: str,
        confidence: float | None,
        observations: tuple[tuple[str, float], ...] = (),
    ) -> None:
        if (
            not is_valid_vin_fragment(suffix6, {6})
            or (vin_full is not None and not is_valid_vin(vin_full))
            or (vin_full is not None and not vin_full.endswith(suffix6))
            or (confidence is not None and not 0 <= confidence <= 100)
        ):
            await state.set_state(CreateCardStates.manual_vin)
            await message.answer(t(language, "vin_invalid"))
            return
        await state.update_data(
            vin_full=vin_full,
            vin_suffix6=suffix6,
            ocr_confidence=confidence,
            vin_observations=remembered_observations(observations),
        )
        await state.set_state(CreateCardStates.confirming)
        if vin_full and vin_check_digit_is_wrong(vin_full):
            await message.answer(t(language, "ocr_check_digit"))
        await message.answer(
            t(
                language,
                "ocr_found",
                vin_display=vin_full or mask_vin(None, suffix6),
                suffix=suffix6,
            ),
            reply_markup=vin_confirmation_keyboard(language),
        )

    async def show_first_page(
        message: Message,
        *,
        language: str,
        query: str | None,
        viewer_role: str | Role,
    ) -> bool:
        card, total = await repository.get_page(query=query, offset=0)
        if card is None:
            key = "no_results" if query else "all_empty"
            kwargs = {"query": query} if query else {}
            await message.answer(
                t(language, key, **kwargs),
                reply_markup=main_menu(language, role=safe_role(viewer_role)),
            )
            return False
        await send_card(
            message,
            card,
            language,
            mode="s" if query else "a",
            query=query or "-",
            offset=0,
            total=total,
            viewer_role=viewer_role,
        )
        return True

    async def build_admin_panel_text(language: str, *, actor_role: str | Role) -> str:
        stats = await repository.get_admin_stats(config.admin_user_ids)
        return t(
            language,
            "admin_panel",
            role=role_name(language, actor_role),
            users=stats.users,
            main_admins=stats.main_admins,
            admins=stats.admins,
            all_admins=stats.main_admins + stats.admins,
            workers=stats.workers,
            drivers=stats.drivers,
            active_cards=stats.active_cards,
            deleted_cards=stats.deleted_cards,
            total_cards=stats.total_cards,
            paint_in_progress=stats.paint_in_progress,
            paint_completed=stats.paint_completed,
        )

    def short_user_label(user, *, limit: int = 14) -> str:
        """Name of a person, trimmed so a button stays readable.

        An empty profile is common enough; returning the numeric id there would
        put the very numbers back into the list that this screen now hides, so
        the caller decides what to show for a nameless person.
        """

        name = " ".join(
            (
                (getattr(user, "display_name", None) or user.full_name or "").strip()
            ).split()
        )
        if not name:
            return ""
        if len(name) <= limit:
            return name
        # Break at a word when possible: "Иван Петров" beats "Иван Петро…".
        cut = name[: limit - 1]
        space = cut.rfind(" ")
        if space >= max(limit // 2, 6):
            return cut[:space].rstrip() + "…"
        return cut.rstrip() + "…"

    def page_user_labels(users: list) -> dict[int, str]:
        """Names for one page; people with the same name get a short suffix."""

        labels: dict[int, str] = {}
        counts: dict[str, int] = {}
        for user in users:
            label = short_user_label(user)
            labels[user.telegram_id] = label
            counts[label] = counts.get(label, 0) + 1
        repeated = {label for label, count in counts.items() if count > 1}
        for user in users:
            if labels[user.telegram_id] in repeated:
                labels[user.telegram_id] = (
                    f"{labels[user.telegram_id]} ({str(user.telegram_id)[-2:]})"
                )
        return labels

    async def build_admin_users_view(
        language: str,
        *,
        requested_offset: int,
        actor_role: str | Role,
        actor_id: int = 0,
    ) -> tuple[str, InlineKeyboardMarkup]:
        total_users = (await repository.get_admin_stats(config.admin_user_ids)).users
        if total_users:
            maximum_offset = (
                (total_users - 1) // ADMIN_USERS_PAGE_SIZE
            ) * ADMIN_USERS_PAGE_SIZE
            offset = min(max(requested_offset, 0), maximum_offset)
        else:
            offset = 0
        users, total = await repository.list_users(
            offset=offset,
            limit=ADMIN_USERS_PAGE_SIZE,
        )
        lines: list[str] = []
        roles: list[tuple[int, str]] = []
        renamable_ids: set[int] = set()
        deletable_ids: set[int] = set()
        role_icons = {
            Role.SUPERADMIN: "👑",
            Role.ADMIN: "🛡",
            Role.WORKER: "👷",
            Role.DRIVER: "🚚",
        }
        page_labels = page_user_labels(users)
        unnamed = t(language, "admin_user_unnamed")
        for index, user in enumerate(users, offset + 1):
            user_role = effective_role(
                user.role,
                is_superadmin=user.telegram_id in config.admin_user_ids,
            )
            roles.append((user.telegram_id, user_role.value))
            if can_rename_user(actor_role, user.telegram_id, config.admin_user_ids):
                renamable_ids.add(user.telegram_id)
            if can_delete_user(
                actor_role,
                user.telegram_id,
                config.admin_user_ids,
                actor_id=actor_id,
                target_role=user_role,
            ):
                deletable_ids.add(user.telegram_id)
            name = html.escape(page_labels.get(user.telegram_id) or unnamed)
            username = f" · @{html.escape(user.username)}" if user.username else ""
            # A renamed user keeps the Telegram profile name as a hint so the
            # administrator still recognises who is behind the new label.
            telegram_note = (
                t(
                    language,
                    "admin_user_telegram_note",
                    name=html.escape(user.full_name),
                )
                if user.display_name and user.full_name
                else ""
            )
            lines.append(
                f"{index}. {role_icons[user_role]} <b>{name}</b>{username}"
                f"{telegram_note}\n"
                f"   {role_name(language, user_role)}"
            )

        pages = max((total + ADMIN_USERS_PAGE_SIZE - 1) // ADMIN_USERS_PAGE_SIZE, 1)
        page = offset // ADMIN_USERS_PAGE_SIZE + 1
        body = "\n\n".join(lines) if lines else t(language, "admin_users_empty")
        body += t(
            language,
            "admin_manage_hint"
            if safe_role(actor_role) in {Role.ADMIN, Role.SUPERADMIN}
            else "admin_view_hint",
        )
        text = t(
            language,
            "admin_users",
            page=page,
            pages=pages,
            total=total,
            users=body,
        )
        markup = admin_users_keyboard(
            language,
            roles=roles,
            offset=offset,
            total=total,
            page_size=ADMIN_USERS_PAGE_SIZE,
            actor_role=safe_role(actor_role),
            renamable_ids=renamable_ids,
            deletable_ids=deletable_ids,
            labels=page_labels,
        )
        return text, markup

    @router.message(CommandStart())
    async def command_start(
        message: Message,
        state: FSMContext,
        lang: str,
        user_registered: bool,
        role: str,
    ) -> None:
        await state.clear()
        if not user_registered:
            await message.answer(
                t(lang, "choose_language"), reply_markup=language_keyboard()
            )
            return
        welcome = (
            f"{t(lang, 'welcome')}\n\n"
            f"{t(lang, 'welcome_role', role=role_name(lang, role))}"
        )
        await message.answer(
            welcome, reply_markup=main_menu(lang, role=safe_role(role))
        )

    @router.message(Command("menu"))
    async def command_menu(
        message: Message, state: FSMContext, lang: str, role: str
    ) -> None:
        await state.clear()
        await message.answer(
            t(lang, "main_menu"),
            reply_markup=main_menu(lang, role=safe_role(role)),
        )

    @router.message(Command("help"))
    async def command_help(message: Message, lang: str, role: str) -> None:
        await message.answer(
            t(lang, "help"), reply_markup=main_menu(lang, role=safe_role(role))
        )

    @router.message(Command("manual"))
    @router.message(F.text.in_(all_labels("btn_manual")))
    async def open_manual(
        message: Message, state: FSMContext, lang: str, role: str
    ) -> None:
        """Open the worker manual as a readable paged message."""

        await state.clear()
        await message.answer(
            manual_text(lang, WORKER, 0),
            reply_markup=manual_keyboard(lang, which=WORKER, index=0),
        )

    @router.callback_query(F.data.startswith("manual|"))
    async def browse_manual(callback: CallbackQuery, lang: str, role: str) -> None:
        parts = (callback.data or "").split("|")
        if len(parts) == 2 and parts[1] == "close":
            await callback.answer()
            if callback.message is not None:
                with contextlib.suppress(TelegramBadRequest):
                    await callback.message.delete()
            return
        if len(parts) != 3:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        if parts[1] == "open":
            which = parts[2]
            index = 0
        else:
            which = parts[1]
            try:
                index = int(parts[2])
            except (TypeError, ValueError):
                await callback.answer(t(lang, "operation_expired"), show_alert=True)
                return
        if which not in {WORKER, ADMIN} or not is_valid_page(which, index):
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        if which == ADMIN and not permissions_for(safe_role(role)).can_manage_users:
            await callback.answer(t(lang, "manual_admin_only"), show_alert=True)
            return
        markup = manual_keyboard(lang, which=which, index=index)
        if callback.message is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        if parts[1] == "open":
            await callback.answer()
            await callback.message.answer(
                manual_text(lang, which, index), reply_markup=markup
            )
            return
        try:
            await callback.message.edit_text(
                manual_text(lang, which, index), reply_markup=markup
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
        await callback.answer()

    @router.callback_query(F.data == "nav|home")
    async def go_home(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        """Close the current message and show the main menu again."""

        await state.clear()
        await callback.answer()
        if callback.message is None:
            return
        with contextlib.suppress(TelegramBadRequest):
            await callback.message.delete()
        await callback.message.answer(
            t(lang, "main_menu"),
            reply_markup=main_menu(lang, role=safe_role(role)),
        )

    @router.callback_query(F.data.startswith("lang|"))
    async def change_language(
        callback: CallbackQuery,
        state: FSMContext,
        role: str,
    ) -> None:
        language = (callback.data or "").split("|", maxsplit=1)[-1]
        if language not in {"ru", "de"}:
            await callback.answer()
            return
        await repository.set_language(callback.from_user.id, language)
        await state.clear()
        await callback.answer(t(language, "language_saved"))
        if callback.message:
            with contextlib.suppress(TelegramBadRequest):
                await callback.message.edit_text(t(language, "language_saved"))
            welcome = (
                f"{t(language, 'welcome')}\n\n"
                f"{t(language, 'welcome_role', role=role_name(language, role))}"
            )
            await callback.message.answer(
                welcome,
                reply_markup=main_menu(language, role=safe_role(role)),
            )

    @router.message(Command("cancel"))
    @router.message(F.text.in_(all_labels("btn_cancel")))
    async def cancel_flow(
        message: Message, state: FSMContext, lang: str, role: str
    ) -> None:
        await state.clear()
        await message.answer(
            t(lang, "cancelled"),
            reply_markup=main_menu(lang, role=safe_role(role)),
        )

    @router.callback_query(F.data == "flow|cancel")
    async def cancel_flow_callback(
        callback: CallbackQuery,
        state: FSMContext,
        lang: str,
        role: str,
    ) -> None:
        await state.clear()
        await callback.answer()
        if callback.message:
            with contextlib.suppress(TelegramBadRequest):
                await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(
                t(lang, "cancelled"),
                reply_markup=main_menu(lang, role=safe_role(role)),
            )

    @router.message(F.text.in_(all_labels("btn_create")))
    async def begin_create(
        message: Message, state: FSMContext, lang: str, role: str
    ) -> None:
        await state.clear()
        if not permissions_for(safe_role(role)).can_create:
            await reject_message_for_role(message, state, lang, role)
            return
        await state.set_state(CreateCardStates.vehicle_photo)
        await message.answer(
            t(lang, "create_vehicle_photo"), reply_markup=cancel_menu(lang)
        )

    @router.message(F.text.in_(all_labels("btn_search")))
    async def begin_search(
        message: Message, state: FSMContext, lang: str, role: str
    ) -> None:
        await state.clear()
        if not permissions_for(safe_role(role)).can_search:
            await reject_message_for_role(message, state, lang, role)
            return
        await state.set_state(SearchStates.query)
        await message.answer(t(lang, "search_prompt"), reply_markup=cancel_menu(lang))

    @router.message(F.text.in_(all_labels("btn_cards")))
    async def list_cards(
        message: Message, state: FSMContext, lang: str, role: str
    ) -> None:
        await state.clear()
        if not permissions_for(safe_role(role)).can_view_cards:
            await reject_message_for_role(message, state, lang, role)
            return
        await show_first_page(
            message,
            language=lang,
            query=None,
            viewer_role=role,
        )

    @router.message(F.text.in_(all_labels("btn_settings")))
    async def settings(
        message: Message,
        state: FSMContext,
        lang: str,
        role: str,
    ) -> None:
        await state.clear()
        await message.answer(
            t(lang, "settings", role=role_name(lang, role)),
            reply_markup=language_keyboard(),
        )

    @router.message(F.text.in_(all_labels("btn_admin")))
    async def open_admin_panel(
        message: Message,
        state: FSMContext,
        lang: str,
        role: str,
    ) -> None:
        await state.clear()
        if not permissions_for(safe_role(role)).can_view_statistics:
            await message.answer(
                t(lang, "admin_forbidden"),
                reply_markup=main_menu(lang, role=safe_role(role)),
            )
            return
        await message.answer(
            await build_admin_panel_text(lang, actor_role=role),
            reply_markup=admin_panel_keyboard(lang),
        )

    @router.callback_query(F.data == "adm|panel")
    async def refresh_admin_panel(
        callback: CallbackQuery,
        lang: str,
        role: str,
    ) -> None:
        if (
            not permissions_for(safe_role(role)).can_view_statistics
            or callback.message is None
        ):
            await callback.answer(t(lang, "admin_forbidden"), show_alert=True)
            return
        text = await build_admin_panel_text(lang, actor_role=role)
        try:
            await callback.message.edit_text(
                text,
                reply_markup=admin_panel_keyboard(lang),
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
        await callback.answer()

    @router.callback_query(F.data.startswith("adm|users|"))
    async def show_admin_users(
        callback: CallbackQuery,
        lang: str,
        role: str,
    ) -> None:
        if (
            not permissions_for(safe_role(role)).can_view_statistics
            or callback.message is None
        ):
            await callback.answer(t(lang, "admin_forbidden"), show_alert=True)
            return
        try:
            requested_offset = int((callback.data or "").rsplit("|", 1)[-1])
        except (TypeError, ValueError):
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        text, markup = await build_admin_users_view(
            lang,
            requested_offset=requested_offset,
            actor_role=role,
            actor_id=callback.from_user.id,
        )
        await callback.message.edit_text(text, reply_markup=markup)
        await callback.answer()

    def parse_user_target(data: str | None) -> tuple[int, int] | None:
        """Read ``(user_id, offset)`` from an ``adm|…|{id}|{offset}`` callback."""

        try:
            _, _, user_id_raw, offset_raw = (data or "").split("|", 3)
            user_id = int(user_id_raw)
            offset = max(int(offset_raw), 0)
        except (TypeError, ValueError):
            return None
        if user_id <= 0:
            return None
        return user_id, offset

    def build_archive_status(language: str) -> str:
        """Static part of the archive screen: configuration as it is loaded."""

        state = (
            t(language, "archive_state_on")
            if archive.enabled
            else t(language, "archive_state_off")
        )
        immediate = (
            t(language, "archive_yes")
            if config.archive_immediate
            else t(language, "archive_no")
        )
        lines = [
            t(language, "archive_title"),
            "━━━━━━━━━━━━━━━━━━",
            t(language, "archive_state_line", state=state),
            t(
                language,
                "archive_channel_line",
                channel=config.archive_channel_id or "—",
            ),
            t(language, "archive_immediate_line", value=immediate),
            t(language, "archive_digest_line", time=config.archive_digest_time),
        ]
        return "\n".join(lines)

    def build_second_reader_status(language: str) -> str:
        """What the second reader is, and whether it is plugged in.

        The key itself is never printed: the last five characters are enough
        for him to tell two keys apart, and the screen is a Telegram message
        that could end up in somebody else's hands.
        """

        state = (
            t(language, "second_reader_state_on")
            if second_reader.enabled
            else t(language, "second_reader_state_off")
        )
        if second_reader.api_key:
            shown = t(
                language,
                "second_reader_key_shown",
                tail=second_reader.api_key[-5:],
                length=len(second_reader.api_key),
            )
        else:
            shown = t(language, "second_reader_key_absent")
        mode = t(language, f"second_reader_mode_{second_reader.mode}")
        return "\n".join(
            [
                t(language, "second_reader_title"),
                "━━━━━━━━━━━━━━━━━━",
                t(language, "second_reader_state_line", state=state),
                t(language, "second_reader_key_line", value=shown),
                t(language, "second_reader_mode_line", mode=mode),
                t(language, "second_reader_model_line", model=second_reader.model),
            ]
        )

    @router.callback_query(F.data == "gem|menu")
    async def open_second_reader(callback: CallbackQuery, lang: str, role: str) -> None:
        """Show whether the cloud reader is on, and what it costs him."""

        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        text = build_second_reader_status(lang) + t(lang, "second_reader_hint")
        try:
            await callback.message.edit_text(
                text, reply_markup=second_reader_keyboard(lang)
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
        await callback.answer()

    @router.callback_query(F.data == "gem|test")
    async def test_second_reader(callback: CallbackQuery, lang: str, role: str) -> None:
        """Ask the cloud one cheap question and report what came back.

        A key that was mistyped fails here, in front of him, instead of
        failing silently on the one photograph that needed help.
        """

        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        works, detail, seconds = await probe_key(
            second_reader.api_key,
            model=second_reader.model,
            timeout=second_reader.timeout,
        )
        if works:
            verdict = t(
                lang,
                "second_reader_test_ok",
                model=second_reader.model,
                seconds=seconds,
            )
        else:
            verdict = t(lang, "second_reader_test_fail", error=html.escape(detail))
        text = build_second_reader_status(lang) + "\n\n" + verdict
        try:
            await callback.message.edit_text(
                text, reply_markup=second_reader_keyboard(lang)
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
        await callback.answer()

    @router.callback_query(F.data == "arch|menu")
    async def open_archive_status(
        callback: CallbackQuery, lang: str, role: str
    ) -> None:
        """Show whether the channel mirror really works, and why not if it does not."""

        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        text = build_archive_status(lang)
        if callback.bot is not None:
            with contextlib.suppress(Exception):
                _ok, report = await archive.probe(callback.bot)
                text += f"\n\n{report}"
        text += t(lang, "archive_hint")
        try:
            await callback.message.edit_text(
                text, reply_markup=archive_status_keyboard(lang)
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
        await callback.answer()

    @router.callback_query(F.data == "arch|test")
    async def test_archive_channel(
        callback: CallbackQuery, lang: str, role: str
    ) -> None:
        """Send a real card photograph into the channel and report the result.

        A plain text message would prove the chat id is right but not that the
        bot may publish photographs, which is exactly what the mirror needs.
        """

        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        text = build_archive_status(lang)
        try:
            card, _total = await repository.get_page(query=None, offset=0)
            stamp = (
                datetime.now(UTC).astimezone(config.timezone).strftime("%d.%m.%Y %H:%M")
            )
            if card is not None:
                await callback.bot.send_photo(
                    config.archive_channel_id,
                    card.vehicle_photo_file_id,
                    caption=(
                        f"🧪 Тест архива · карточка №{card.id}\n"
                        f"🔑 VIN: <code>{card.vin_full or card.vin_suffix6}</code>\n"
                        f"🕓 {stamp}"
                    ),
                )
                result = t(lang, "archive_test_photo_ok", card_id=card.id)
            else:
                await callback.bot.send_message(
                    config.archive_channel_id,
                    f"🧪 Тест архива · {stamp}\nБот может публиковать сообщения.",
                )
                result = t(lang, "archive_test_ok")
        except Exception as exc:  # noqa: BLE001 - the administrator needs the text
            result = t(lang, "archive_test_fail", error=html.escape(str(exc))[:900])
        if callback.bot is not None:
            with contextlib.suppress(Exception):
                _ok, report = await archive.probe(callback.bot)
                text += f"\n\n{report}"
        text += f"\n\n{result}"
        try:
            await callback.message.edit_text(
                text, reply_markup=archive_status_keyboard(lang)
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
        await callback.answer()

    @router.callback_query(F.data == "arch|retry")
    async def retry_archive_channel(
        callback: CallbackQuery, lang: str, role: str
    ) -> None:
        """Send everything that did not reach the channel the first time."""

        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        text = build_archive_status(lang)
        try:
            sent = await archive.mirror_pending(callback.bot, limit=20)
        except (TelegramAPIError, OSError, RuntimeError, ValueError) as exc:
            # The administrator needs the reason, not a crash.
            result = t(lang, "archive_test_fail", error=html.escape(str(exc))[:900])
        else:
            result = (
                t(lang, "archive_retry_done", count=sent)
                if sent
                else t(lang, "archive_retry_none")
            )
        if callback.bot is not None:
            with contextlib.suppress(Exception):
                _ok, report = await archive.probe(callback.bot)
                text += f"\n\n{report}"
        text += f"\n\n{result}"
        try:
            await callback.message.edit_text(
                text, reply_markup=archive_status_keyboard(lang)
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
        await callback.answer()

    @router.callback_query(F.data == "arch|digest")
    async def send_archive_digest_now(
        callback: CallbackQuery, lang: str, role: str
    ) -> None:
        """Fire the daily database dump by hand."""

        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        text = build_archive_status(lang)
        try:
            sent = await archive.send_daily_digest(callback.bot)
        except Exception as exc:  # noqa: BLE001 - the administrator needs the text
            result = t(lang, "archive_digest_fail", error=html.escape(str(exc))[:900])
        else:
            result = (
                t(lang, "archive_digest_ok")
                if sent
                else t(lang, "archive_digest_fail", error="архив отключён")
            )
        text += f"\n\n{result}"
        try:
            await callback.message.edit_text(
                text, reply_markup=archive_status_keyboard(lang)
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
        await callback.answer()

    @router.callback_query(F.data.startswith("adm|del|"))
    async def delete_user_ask(
        callback: CallbackQuery,
        lang: str,
        role: str,
    ) -> None:
        """Ask for confirmation before a user is removed from the bot."""

        actor_role = safe_role(role)
        if not permissions_for(actor_role).can_manage_users or callback.message is None:
            await callback.answer(t(lang, "admin_forbidden"), show_alert=True)
            return
        parsed = parse_user_target(callback.data)
        if parsed is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        target_id, offset = parsed
        target = await repository.get_user(target_id)
        if target is None:
            await callback.answer(t(lang, "admin_delete_missing"), show_alert=True)
            return
        target_role = effective_role(
            target.role, is_superadmin=target_id in config.admin_user_ids
        )
        if not can_delete_user(
            actor_role,
            target_id,
            config.admin_user_ids,
            actor_id=callback.from_user.id,
            target_role=target_role,
        ):
            await callback.answer(
                t(lang, "admin_delete_self")
                if target_id == callback.from_user.id
                else t(lang, "admin_delete_forbidden"),
                show_alert=True,
            )
            return
        vehicles, paints = await repository.count_user_cards(target_id)
        text = t(
            lang,
            "admin_delete_confirm",
            name=html.escape(display_name_of(target)),
            user_id=target_id,
            role=role_name(lang, target_role),
            cards=vehicles,
            paint=paints,
        )
        await callback.message.edit_text(
            text,
            reply_markup=admin_delete_confirm_keyboard(
                lang, user_id=target_id, offset=offset
            ),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("adm|delgo|"))
    async def delete_user_confirmed(
        callback: CallbackQuery,
        lang: str,
        role: str,
    ) -> None:
        """Remove the user and return to the same page of the list."""

        actor_role = safe_role(role)
        if not permissions_for(actor_role).can_manage_users or callback.message is None:
            await callback.answer(t(lang, "admin_forbidden"), show_alert=True)
            return
        parsed = parse_user_target(callback.data)
        if parsed is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        target_id, offset = parsed
        target = await repository.get_user(target_id)
        if target is not None:
            target_role = effective_role(
                target.role, is_superadmin=target_id in config.admin_user_ids
            )
            if not can_delete_user(
                actor_role,
                target_id,
                config.admin_user_ids,
                actor_id=callback.from_user.id,
                target_role=target_role,
            ):
                await callback.answer(
                    t(lang, "admin_delete_self")
                    if target_id == callback.from_user.id
                    else t(lang, "admin_delete_forbidden"),
                    show_alert=True,
                )
                return
            vehicles, paints = await repository.count_user_cards(target_id)
            deleted_name = display_name_of(target)
            removed = await repository.delete_user(target_id)
        else:
            vehicles, paints, removed = 0, 0, False
            deleted_name = str(target_id)
        if not removed:
            await callback.answer(t(lang, "admin_delete_missing"), show_alert=True)
        else:
            await callback.answer(
                t(
                    lang,
                    "admin_delete_done",
                    user=html.escape(deleted_name),
                    cards=vehicles + paints,
                ),
                show_alert=True,
            )
        text, markup = await build_admin_users_view(
            lang,
            requested_offset=offset,
            actor_role=actor_role,
            actor_id=callback.from_user.id,
        )
        text += f"\n\n{
            t(
                lang,
                'admin_delete_done',
                user=html.escape(deleted_name),
                cards=vehicles + paints,
            )
        }"
        await callback.message.edit_text(text, reply_markup=markup)

    @router.callback_query(F.data.startswith("adm|role|"))
    async def change_user_role(
        callback: CallbackQuery,
        lang: str,
        role: str,
    ) -> None:
        actor_role = safe_role(role)
        if (
            not permissions_for(actor_role).can_view_statistics
            or callback.message is None
        ):
            await callback.answer(t(lang, "admin_forbidden"), show_alert=True)
            return
        try:
            _, _, user_id_raw, requested_role_raw, offset_raw = (
                callback.data or ""
            ).split("|", 4)
            target_id = int(user_id_raw)
            requested_role = Role(requested_role_raw)
            offset = int(offset_raw)
            if target_id <= 0 or offset < 0:
                raise ValueError
        except (TypeError, ValueError):
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        if target_id in config.admin_user_ids:
            await callback.answer(
                t(lang, "admin_master_protected"),
                show_alert=True,
            )
            return
        target = await repository.get_user(target_id)
        if target is None:
            await callback.answer(t(lang, "admin_user_missing"), show_alert=True)
            return
        target_role = normalize_stored_role(target.role)
        if not can_assign_role(actor_role, target_role, requested_role):
            await callback.answer(t(lang, "admin_role_forbidden"), show_alert=True)
            return
        updated = await repository.set_role(target_id, requested_role)
        if updated is None:
            await callback.answer(t(lang, "admin_user_missing"), show_alert=True)
            return
        await callback.answer(
            t(
                lang,
                "admin_role_changed",
                user=html.escape(display_name_of(target)),
                role=role_name(lang, requested_role),
            )
        )
        text, markup = await build_admin_users_view(
            lang,
            requested_offset=offset,
            actor_role=actor_role,
            actor_id=callback.from_user.id,
        )
        text += f"\n\n{t(lang, 'admin_role_changed_hint')}"
        await callback.message.edit_text(text, reply_markup=markup)

    @router.callback_query(F.data.startswith("adm|rename|"))
    async def rename_user_start(
        callback: CallbackQuery,
        state: FSMContext,
        lang: str,
        role: str,
    ) -> None:
        """Ask an administrator for the new name of one user."""

        actor_role = safe_role(role)
        if not permissions_for(actor_role).can_manage_users or callback.message is None:
            await callback.answer(t(lang, "admin_forbidden"), show_alert=True)
            return
        parts = (callback.data or "").split("|")
        if len(parts) != 4:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        try:
            target_id = int(parts[2])
            offset = int(parts[3])
            if target_id <= 0 or offset < 0:
                raise ValueError
        except (TypeError, ValueError):
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        if not can_rename_user(actor_role, target_id, config.admin_user_ids):
            await callback.answer(t(lang, "admin_rename_forbidden"), show_alert=True)
            return
        target = await repository.get_user(target_id)
        if target is None:
            await callback.answer(t(lang, "admin_user_missing"), show_alert=True)
            return
        await state.set_state(RenameUserStates.name)
        await state.update_data(
            rename_user_id=target_id,
            rename_offset=offset,
            rename_chat_id=callback.message.chat.id,
            rename_message_id=callback.message.message_id,
        )
        await callback.answer()
        await callback.message.answer(
            t(
                lang,
                "admin_rename_prompt",
                user=html.escape(display_name_of(target)),
                name=html.escape(display_name_of(target)),
            ),
            reply_markup=cancel_menu(lang),
        )

    @router.message(RenameUserStates.name)
    async def receive_new_user_name(
        message: Message,
        state: FSMContext,
        bot: Bot,
        lang: str,
        role: str,
    ) -> None:
        actor_role = safe_role(role)
        stored = await state.get_data()
        if not permissions_for(actor_role).can_manage_users:
            await state.clear()
            await message.answer(
                t(lang, "admin_forbidden"),
                reply_markup=main_menu(lang, role=actor_role),
            )
            return
        try:
            target_id = int(stored.get("rename_user_id", 0))
            offset = max(int(stored.get("rename_offset", 0)), 0)
        except (TypeError, ValueError):
            target_id, offset = 0, 0
        if target_id <= 0 or not can_rename_user(
            actor_role, target_id, config.admin_user_ids
        ):
            await state.clear()
            await message.answer(
                t(lang, "admin_rename_forbidden"),
                reply_markup=main_menu(lang, role=actor_role),
            )
            return
        cleaned = clean_display_name(message.text or "")
        if cleaned is None:
            await message.answer(
                t(lang, "admin_rename_invalid"), reply_markup=cancel_menu(lang)
            )
            return
        previous_name = display_name_of(await repository.get_user(target_id))
        updated = await repository.set_display_name(target_id, cleaned)
        await state.clear()
        if updated is None:
            await message.answer(
                t(lang, "admin_user_missing"),
                reply_markup=main_menu(lang, role=actor_role),
            )
            return
        await message.answer(
            t(
                lang,
                "admin_rename_done",
                user=html.escape(previous_name),
                name=html.escape(cleaned),
            ),
            reply_markup=main_menu(lang, role=actor_role),
        )
        # Keep the open list of users in sync with the new name.
        chat_id = stored.get("rename_chat_id")
        message_id = stored.get("rename_message_id")
        if chat_id is None or message_id is None:
            return
        text, markup = await build_admin_users_view(
            lang,
            requested_offset=offset,
            actor_role=actor_role,
            actor_id=message.from_user.id,
        )
        text += f"\n\n{
            t(
                lang,
                'admin_rename_done',
                user=html.escape(previous_name),
                name=html.escape(cleaned),
            )
        }"
        with contextlib.suppress(TelegramBadRequest):
            await bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
                parse_mode=ParseMode.HTML,
            )

    @router.callback_query(F.data == "adm|close")
    async def close_admin_panel(callback: CallbackQuery, role: str, lang: str) -> None:
        if not permissions_for(safe_role(role)).can_view_statistics:
            await callback.answer(t(lang, "admin_forbidden"), show_alert=True)
            return
        if callback.message:
            with contextlib.suppress(TelegramBadRequest):
                await callback.message.delete()
        await callback.answer()

    @router.message(CreateCardStates.vehicle_photo)
    async def receive_vehicle_photo(
        message: Message, state: FSMContext, lang: str, role: str
    ) -> None:
        if not permissions_for(safe_role(role)).can_create:
            await reject_message_for_role(message, state, lang, role)
            return
        if not message.photo:
            await message.answer(t(lang, "vehicle_photo_required"))
            return
        photo = message.photo[-1]
        validation_error = photo_validation_error(photo)
        if validation_error:
            await message.answer(t(lang, validation_error))
            return
        await state.update_data(
            vehicle_photo_file_id=photo.file_id,
            vehicle_photo_unique_id=photo.file_unique_id,
        )
        await state.set_state(CreateCardStates.invoice_photo)
        await message.answer(
            t(lang, "create_invoice_photo"), reply_markup=cancel_menu(lang)
        )

    @router.message(CreateCardStates.invoice_photo)
    async def receive_invoice_photo(
        message: Message, state: FSMContext, lang: str, role: str
    ) -> None:
        if not permissions_for(safe_role(role)).can_create:
            await reject_message_for_role(message, state, lang, role)
            return
        if not message.photo:
            await message.answer(t(lang, "invoice_photo_required"))
            return
        photo = message.photo[-1]
        validation_error = photo_validation_error(photo)
        if validation_error:
            await message.answer(t(lang, validation_error))
            return
        data = await state.get_data()
        if photo.file_unique_id == data.get("vehicle_photo_unique_id"):
            await message.answer(t(lang, "photo_reused"))
            return
        await state.update_data(
            invoice_photo_file_id=photo.file_id,
            invoice_photo_unique_id=photo.file_unique_id,
        )
        await state.set_state(CreateCardStates.vin_photo)
        await message.answer(
            t(lang, "create_vin_photo"), reply_markup=vin_source_keyboard(lang)
        )

    async def read_vin_off_photo(
        message: Message,
        state: FSMContext,
        lang: str,
        bot: Bot,
        *,
        file_id: str,
        unique_id: str,
    ) -> None:
        """Read the code off one photograph and put the result on screen.

        Which photograph is nobody's business but his: a tight crop of the
        plate, the whole invoice, the same invoice he sent a moment ago —
        the engine looks for the code by its shape, so all three work.
        """

        await state.update_data(
            vin_photo_file_id=file_id,
            vin_photo_unique_id=unique_id,
        )
        processing = await message.answer(t(lang, "ocr_processing"))
        try:
            result, report, second_opinion = await read_and_report(bot, file_id, lang)
        except OCRUnavailableError:
            logger.exception("Модуль OCR недоступен")
            await state.set_state(CreateCardStates.manual_vin)
            await processing.edit_text(t(lang, "ocr_unavailable"))
            return
        except (ValueError, OSError):
            logger.exception("Не удалось обработать изображение VIN")
            await state.set_state(CreateCardStates.manual_vin)
            await processing.edit_text(t(lang, "ocr_not_found"))
            return

        with contextlib.suppress(TelegramBadRequest):
            await processing.delete()

        if second_opinion:
            await message.answer(second_opinion)

        vin, shaky = judged_vin(result)
        if vin and result.suffix6:
            # Characters the camera could not make out are shown as gaps,
            # never filled in. Offering a guessed character as if it had been
            # read is the one thing a VIN reader must not do.
            if report.partial_vin and UNREADABLE in report.partial_vin:
                await show_partial_reading(
                    message,
                    state,
                    lang,
                    report.partial_vin,
                    prefix="vin",
                    manual_state=CreateCardStates.manual_vin,
                )
                return
            # The check digit is reported by show_vin_confirmation itself, so
            # that a code typed in by hand is warned about too.
            if shaky and not vin_check_digit_is_wrong(vin):
                await message.answer(t(lang, "ocr_weak"))
            if report.need_retake and report.retake_instructions:
                await message.answer(
                    t(
                        lang,
                        "ocr_retake",
                        instructions=html.escape(report.retake_instructions),
                    )
                )
            await show_vin_confirmation(
                message,
                state,
                lang,
                vin_full=result.vin,
                suffix6=result.suffix6,
                confidence=result.confidence,
                observations=result.observations,
            )
            return

        await state.set_state(CreateCardStates.manual_vin)
        if report.need_retake and report.retake_instructions:
            await message.answer(
                t(
                    lang,
                    "ocr_retake",
                    instructions=html.escape(report.retake_instructions),
                )
            )
        if (result.raw_text or "").strip():
            await message.answer(t(lang, "ocr_not_found"))
        else:
            await message.answer(t(lang, "ocr_no_text"))

    @router.message(CreateCardStates.vin_photo)
    async def receive_vin_photo(
        message: Message,
        state: FSMContext,
        lang: str,
        bot: Bot,
        role: str,
    ) -> None:
        if not permissions_for(safe_role(role)).can_create:
            await reject_message_for_role(message, state, lang, role)
            return
        if not message.photo:
            await message.answer(t(lang, "vin_photo_required"))
            return

        photo = message.photo[-1]
        validation_error = photo_validation_error(photo, vin_crop=True)
        if validation_error:
            await message.answer(t(lang, validation_error))
            return
        data = await state.get_data()
        # The invoice is allowed here on purpose: he asked to be able to send
        # the invoice as the VIN photograph instead of cutting a piece out of
        # it. Only the vehicle photograph stays refused — it is the car, not
        # the paperwork, and reusing it is always a mistake.
        if photo.file_unique_id == data.get("vehicle_photo_unique_id"):
            await message.answer(t(lang, "photo_reused"))
            return
        await read_vin_off_photo(
            message,
            state,
            lang,
            bot,
            file_id=photo.file_id,
            unique_id=photo.file_unique_id,
        )

    @router.callback_query(F.data == "vin|useinvoice")
    async def use_invoice_as_vin(
        callback: CallbackQuery, state: FSMContext, lang: str, bot: Bot, role: str
    ) -> None:
        """Take the code off the invoice he has already sent."""

        if not permissions_for(safe_role(role)).can_create:
            await state.clear()
            await reject_callback_for_role(callback, lang)
            return
        if await state.get_state() != CreateCardStates.vin_photo.state:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        data = await state.get_data()
        file_id = data.get("invoice_photo_file_id")
        unique_id = data.get("invoice_photo_unique_id")
        if not file_id:
            await callback.answer(t(lang, "invoice_photo_required"), show_alert=True)
            return
        await callback.answer()
        if callback.message:
            await read_vin_off_photo(
                callback.message,
                state,
                lang,
                bot,
                file_id=file_id,
                unique_id=unique_id or file_id,
            )

    @router.message(CreateCardStates.manual_vin)
    async def receive_manual_vin(
        message: Message, state: FSMContext, lang: str, role: str
    ) -> None:
        if not permissions_for(safe_role(role)).can_create:
            await reject_message_for_role(message, state, lang, role)
            return
        if not message.text:
            await message.answer(t(lang, "manual_vin_prompt"))
            return
        if len(message.text) > 64:
            await message.answer(t(lang, "text_too_long"))
            return
        parsed = parse_manual_card_vin(message.text)
        if parsed is None:
            await message.answer(t(lang, "vin_invalid"))
            return
        vin_full, suffix6 = parsed
        await show_vin_confirmation(
            message,
            state,
            lang,
            vin_full=vin_full,
            suffix6=suffix6,
            confidence=None,
        )

    @router.callback_query(F.data == "vin|edit")
    async def edit_vin(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        if not permissions_for(safe_role(role)).can_create:
            await state.clear()
            await reject_callback_for_role(callback, lang)
            return
        if await state.get_state() != CreateCardStates.confirming.state:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        await state.set_state(CreateCardStates.manual_vin)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                t(lang, "manual_vin_prompt"), reply_markup=cancel_menu(lang)
            )

    @router.message(CreateCardStates.confirming)
    async def receive_corrected_vin(
        message: Message, state: FSMContext, lang: str, role: str
    ) -> None:
        """A code pasted back with a character put right in it.

        He asked for exactly this: the bot reads the code, he sees which
        character is wrong, copies the message, fixes that one character and
        sends it back. So a code arriving while a reading is on screen is
        taken as the correction, not as chatter.
        """

        if not permissions_for(safe_role(role)).can_create:
            await reject_message_for_role(message, state, lang, role)
            return
        if not message.text:
            return
        stripped = message.text.strip()
        # Only answer when what came back could have been meant as a code.
        # «спасибо» is seven characters long too, and scolding a man for
        # thanking the bot is worse than saying nothing — the buttons under
        # the reading keep working either way.
        latin = "".join(
            char for char in stripped.upper() if char.isascii() and char.isalnum()
        )
        if len(latin) < 6 or len(latin) > 64:
            return
        parsed = parse_manual_card_vin(stripped)
        if parsed is None:
            await message.answer(t(lang, "vin_invalid"))
            return
        vin_full, suffix6 = parsed
        await show_vin_confirmation(
            message,
            state,
            lang,
            vin_full=vin_full,
            suffix6=suffix6,
            confidence=None,
        )

    @router.callback_query(F.data == "vin|fix")
    async def fix_vin_character(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        """Ask which of the seventeen characters is the wrong one."""

        if not permissions_for(safe_role(role)).can_create:
            await state.clear()
            await reject_callback_for_role(callback, lang)
            return
        if await state.get_state() != CreateCardStates.confirming.state:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        await callback.answer()
        if callback.message:
            await offer_fix_board(callback.message, state, lang, prefix="vin")

    @router.callback_query(F.data.startswith("vin|fixpos|"))
    async def fix_vin_position(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        """Ask what the chosen character should be instead."""

        if not permissions_for(safe_role(role)).can_create:
            await state.clear()
            await reject_callback_for_role(callback, lang)
            return
        try:
            index = int(callback.data.rsplit("|", 1)[-1])
        except (TypeError, ValueError):
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        await callback.answer()
        if callback.message:
            await offer_replacements(
                callback.message, state, lang, prefix="vin", index=index
            )

    @router.callback_query(F.data.startswith("vin|fixset|"))
    async def set_vin_character(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        """Put the chosen character in place and show the code again."""

        if not permissions_for(safe_role(role)).can_create:
            await state.clear()
            await reject_callback_for_role(callback, lang)
            return
        try:
            _prefix, index_text, char = callback.data.split("|")[1:]
            index = int(index_text)
        except (TypeError, ValueError):
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        if len(char) != 1 or char not in VIN_ALPHABET:
            await callback.answer(t(lang, "vin_invalid"), show_alert=True)
            return
        await callback.answer()
        if callback.message:
            await apply_character_fix(
                callback.message,
                state,
                lang,
                index=index,
                char=char,
                confirming_state=CreateCardStates.confirming,
                manual_state=CreateCardStates.manual_vin,
                show_confirmation=show_vin_confirmation,
                prefix="vin",
            )

    @router.callback_query(F.data == "vin|fixback")
    async def fix_vin_back(callback: CallbackQuery, lang: str) -> None:
        """Close the correction board."""

        await callback.answer()
        with contextlib.suppress(TelegramBadRequest):
            if callback.message:
                await callback.message.delete()

    @router.callback_query(F.data == "vin|retake")
    async def retake_vin(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        if not permissions_for(safe_role(role)).can_create:
            await state.clear()
            await reject_callback_for_role(callback, lang)
            return
        if await state.get_state() != CreateCardStates.confirming.state:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        await state.set_state(CreateCardStates.vin_photo)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                t(lang, "create_vin_photo"),
                reply_markup=(
                    vin_source_keyboard(lang)
                    if (await state.get_data()).get("invoice_photo_file_id")
                    else cancel_menu(lang)
                ),
            )

    @router.callback_query(F.data == "vin|ok")
    async def save_card(
        callback: CallbackQuery,
        state: FSMContext,
        lang: str,
        role: str,
        display_name: str,
    ) -> None:
        if not permissions_for(safe_role(role)).can_create:
            await state.clear()
            await reject_callback_for_role(callback, lang)
            return
        if await state.get_state() != CreateCardStates.confirming.state:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        data = await state.get_data()
        required = {
            "vehicle_photo_file_id",
            "vehicle_photo_unique_id",
            "invoice_photo_file_id",
            "invoice_photo_unique_id",
            "vin_photo_file_id",
            "vin_photo_unique_id",
            "vin_suffix6",
        }
        # Three photographs used to be demanded, and the card was refused
        # without them. It cannot be any more: he asked to be able to send the
        # invoice as the VIN photograph, and when he does, the invoice and the
        # VIN photograph are one and the same picture. What still has to hold
        # is that the car itself is not one of the documents — a photograph of
        # the car cannot be its paperwork.
        paperwork = {
            data.get("invoice_photo_unique_id"),
            data.get("vin_photo_unique_id"),
        }
        vehicle_unique = data.get("vehicle_photo_unique_id")
        if (
            not required.issubset(data)
            or None in paperwork
            or vehicle_unique is None
            or vehicle_unique in paperwork
        ):
            await state.clear()
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return

        vin_full = data.get("vin_full")
        # A code is never saved with a «?» in it. The gap means the camera did
        # not read that character, and storing a guess of our own would be
        # inventing a VIN — the one thing he asked us never to do.
        if vin_full and UNREADABLE in vin_full:
            await callback.answer(t(lang, "vin_has_gaps"), show_alert=True)
            return
        if vin_full:
            duplicate = await repository.find_active_by_full_vin(vin_full)
            if duplicate is not None:
                await state.clear()
                await callback.answer()
                if callback.message:
                    with contextlib.suppress(TelegramBadRequest):
                        await callback.message.edit_reply_markup(reply_markup=None)
                    await callback.message.answer(
                        t(lang, "duplicate", card_id=duplicate.id),
                        reply_markup=main_menu(lang, role=safe_role(role)),
                    )
                    if can_open_card(duplicate, callback.from_user.id, role):
                        await send_card(
                            callback.message,
                            duplicate,
                            lang,
                            mode="o",
                            query="-",
                            offset=0,
                            total=1,
                            viewer_role=role,
                        )
                return

        card = await repository.create_card(
            owner_id=callback.from_user.id,
            owner_name=display_name,
            vehicle_photo_file_id=data["vehicle_photo_file_id"],
            invoice_photo_file_id=data["invoice_photo_file_id"],
            vin_photo_file_id=data["vin_photo_file_id"],
            vin_full=vin_full,
            vin_suffix6=data["vin_suffix6"],
            ocr_confidence=data.get("ocr_confidence"),
        )
        await state.clear()
        await remember_creation(
            callback.bot, card, kind=ARCHIVE_KIND_CARD, owner=display_name
        )
        await callback.answer()
        if callback.message:
            with contextlib.suppress(TelegramBadRequest):
                await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(
                t(lang, "card_saved", card_id=card.id),
                reply_markup=main_menu(lang, role=safe_role(role)),
            )
            await send_card(
                callback.message,
                card,
                lang,
                mode="o",
                query="-",
                offset=0,
                total=1,
                viewer_role=role,
            )

    @router.message(SearchStates.query)
    async def receive_search_query(
        message: Message,
        state: FSMContext,
        lang: str,
        bot: Bot,
        role: str,
    ) -> None:
        if not permissions_for(safe_role(role)).can_search:
            await reject_message_for_role(message, state, lang, role)
            return
        query: str | None = None
        if message.photo:
            validation_error = photo_validation_error(message.photo[-1], vin_crop=True)
            if validation_error:
                await message.answer(t(lang, validation_error))
                return
            processing = await message.answer(t(lang, "ocr_processing"))
            try:
                result = await recognize_photo(bot, message.photo[-1].file_id)
                query = result.suffix6
            except (OCRUnavailableError, ValueError, OSError):
                logger.exception("Не удалось распознать VIN на фотографии для поиска")
            with contextlib.suppress(TelegramBadRequest):
                await processing.delete()
            if not query:
                await message.answer(t(lang, "search_photo_failed"))
                return
        elif message.text:
            if len(message.text) > 64:
                await message.answer(t(lang, "text_too_long"))
                return
            query = parse_search_query(message.text)
        if not query:
            await message.answer(t(lang, "search_invalid"))
            return

        await state.clear()
        found = await show_first_page(
            message,
            language=lang,
            query=query,
            viewer_role=role,
        )
        if found:
            await message.answer(
                t(lang, "main_menu"),
                reply_markup=main_menu(lang, role=safe_role(role)),
            )

    @router.callback_query(F.data.startswith("media|"))
    async def switch_card_media(callback: CallbackQuery, lang: str, role: str) -> None:
        try:
            _, target, card_id_raw, mode, raw_query, raw_offset = (
                callback.data or ""
            ).split("|", 5)
            card_id = int(card_id_raw)
            parsed_offset = int(raw_offset)
            if card_id <= 0 or parsed_offset < 0:
                raise ValueError
        except (ValueError, TypeError):
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        if target not in {"i", "v"} or mode not in {"o", "s", "a"}:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        if mode == "s" and parse_search_query(raw_query) is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        permissions = permissions_for(safe_role(role))
        if mode in {"s", "a"} and not permissions.can_view_cards:
            await reject_callback_for_role(callback, lang)
            return
        if mode == "s" and not permissions.can_search:
            await reject_callback_for_role(callback, lang)
            return

        if mode == "o":
            card = await repository.get_card(card_id)
            offset, total = 0, 1
            if card is not None and card.is_deleted:
                card = None
        else:
            query = raw_query if mode == "s" else None
            card, offset, total = await repository.get_card_position(
                card_id, query=query
            )
        if card is None or callback.message is None or not card.invoice_photo_file_id:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        if not can_open_card(card, callback.from_user.id, role):
            await reject_callback_for_role(callback, lang)
            return

        showing_invoice = target == "i"
        if showing_invoice:
            photo_file_id = card.invoice_photo_file_id
            caption = t(lang, "card_invoice_view", card_id=card.id)
        else:
            photo_file_id = card.vehicle_photo_file_id
            caption = card_caption(card, lang, position=offset + 1, total=total)
        media = InputMediaPhoto(
            media=photo_file_id,
            caption=caption,
            parse_mode=ParseMode.HTML,
        )
        markup = card_keyboard(
            lang,
            mode=mode,
            query=raw_query,
            offset=offset,
            total=total,
            card_id=card.id,
            can_delete=can_delete(role),
            has_invoice=True,
            showing_invoice=showing_invoice,
        )
        try:
            await callback.message.edit_media(media=media, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                logger.warning("Не удалось переключить фотографию карточки: %s", exc)
        await callback.answer()

    @router.callback_query(F.data.startswith("page|"))
    async def change_page(callback: CallbackQuery, lang: str, role: str) -> None:
        try:
            _, mode, raw_query, raw_offset = (callback.data or "").split(
                "|", maxsplit=3
            )
            requested_offset = int(raw_offset)
            if requested_offset < 0:
                raise ValueError
        except (ValueError, TypeError):
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        query = raw_query if mode == "s" else None
        if mode not in {"s", "a"} or (
            mode == "s" and parse_search_query(raw_query) is None
        ):
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        permissions = permissions_for(safe_role(role))
        if not permissions.can_view_cards or (
            mode == "s" and not permissions.can_search
        ):
            await reject_callback_for_role(callback, lang)
            return

        card, total = await repository.get_page(query=query, offset=requested_offset)
        if card is None or callback.message is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        offset = min(requested_offset, total - 1)
        media = InputMediaPhoto(
            media=card.vehicle_photo_file_id,
            caption=card_caption(card, lang, position=offset + 1, total=total),
            parse_mode=ParseMode.HTML,
        )
        markup = card_keyboard(
            lang,
            mode=mode,
            query=raw_query,
            offset=offset,
            total=total,
            card_id=card.id,
            can_delete=can_delete(role),
            has_invoice=bool(card.invoice_photo_file_id),
        )
        try:
            await callback.message.edit_media(media=media, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                logger.warning("Не удалось изменить страницу карточки: %s", exc)
        await callback.answer()

    @router.callback_query(F.data.startswith("delask|"))
    async def ask_delete(callback: CallbackQuery, lang: str, role: str) -> None:
        if not can_delete(role):
            await callback.answer(t(lang, "delete_forbidden"), show_alert=True)
            return
        try:
            _, card_id_raw, mode, query, offset_raw = (callback.data or "").split(
                "|", 4
            )
            card_id, offset = int(card_id_raw), int(offset_raw)
            if (
                card_id <= 0
                or offset < 0
                or mode not in {"o", "s", "a"}
                or (mode == "s" and parse_search_query(query) is None)
            ):
                raise ValueError
        except (ValueError, TypeError):
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        card = await repository.get_card(card_id)
        if card is None or card.is_deleted:
            await callback.answer(t(lang, "already_deleted"), show_alert=True)
            return
        if callback.message:
            caption = f"{card_caption(card, lang)}\n\n<b>{t(lang, 'delete_question', card_id=card.id)}</b>"
            await callback.message.edit_caption(
                caption=caption,
                reply_markup=delete_confirmation_keyboard(
                    lang,
                    card_id=card.id,
                    mode=mode,
                    query=query,
                    offset=offset,
                ),
            )
        await callback.answer()

    @router.callback_query(F.data.startswith("delno|"))
    async def cancel_delete(callback: CallbackQuery, lang: str, role: str) -> None:
        if not can_delete(role):
            await callback.answer(t(lang, "delete_forbidden"), show_alert=True)
            return
        try:
            _, card_id_raw, mode, raw_query, offset_raw = (callback.data or "").split(
                "|", 4
            )
            card_id, requested_offset = int(card_id_raw), int(offset_raw)
            if (
                card_id <= 0
                or requested_offset < 0
                or mode not in {"o", "s", "a"}
                or (mode == "s" and parse_search_query(raw_query) is None)
            ):
                raise ValueError
        except (ValueError, TypeError):
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return

        if mode == "o":
            card = await repository.get_card(card_id)
            total, offset = 1, 0
        else:
            query = raw_query if mode == "s" else None
            card, total = await repository.get_page(
                query=query, offset=requested_offset
            )
            offset = min(requested_offset, max(total - 1, 0))
        if card is None or card.is_deleted or callback.message is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        await callback.message.edit_caption(
            caption=card_caption(card, lang, position=offset + 1, total=total),
            reply_markup=card_keyboard(
                lang,
                mode=mode,
                query=raw_query,
                offset=offset,
                total=total,
                card_id=card.id,
                can_delete=can_delete(role),
                has_invoice=bool(card.invoice_photo_file_id),
            ),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("delyes|"))
    async def confirm_delete(
        callback: CallbackQuery, lang: str, role: str, display_name: str
    ) -> None:
        if not can_delete(role):
            await callback.answer(t(lang, "delete_forbidden"), show_alert=True)
            return
        try:
            _, card_id_raw, mode, query, offset_raw = (callback.data or "").split(
                "|", 4
            )
            card_id, offset = int(card_id_raw), int(offset_raw)
            if (
                card_id <= 0
                or offset < 0
                or mode not in {"o", "s", "a"}
                or (mode == "s" and parse_search_query(query) is None)
            ):
                raise ValueError
        except (ValueError, TypeError):
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        card = await repository.get_card(card_id)
        if card is None or card.is_deleted:
            await callback.answer(t(lang, "already_deleted"), show_alert=True)
            return
        deleted = await repository.soft_delete_card(card_id, callback.from_user.id)
        if not deleted:
            await callback.answer(t(lang, "already_deleted"), show_alert=True)
            return
        who = (display_name or "").strip() or str(callback.from_user.id)
        with contextlib.suppress(Exception):
            await repository.add_audit(
                actor_id=callback.from_user.id,
                actor_name=who,
                action=AuditAction.CARD_DELETED,
                details=f"#{card_id} {card.vin_full or card.vin_suffix6}",
            )
            await archive.note_deletion(callback.bot, card, who)
        if callback.message:
            await callback.message.edit_caption(
                caption=t(lang, "deleted", card_id=card_id), reply_markup=None
            )
        await callback.answer(t(lang, "deleted", card_id=card_id))

    @router.callback_query(F.data == "card|close")
    async def close_card(callback: CallbackQuery) -> None:
        if callback.message:
            try:
                await callback.message.delete()
            except TelegramBadRequest:
                await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer()

    # ------------------------------------------------------------- painting

    paint_scopes = frozenset({"in", "done", "s", "o"})
    paint_empty_keys = {
        "in": "paint_empty",
        "done": "paint_done_empty",
        "s": "paint_no_results",
        "o": "paint_empty",
    }

    def can_view_paint_catalog(role: str | Role) -> bool:
        return permissions_for(safe_role(role)).can_view_paint

    def can_complete_paint(role: str | Role) -> bool:
        return permissions_for(safe_role(role)).can_complete_paint

    def can_search_paint(role: str | Role) -> bool:
        return permissions_for(safe_role(role)).can_search_paint

    def can_browse_paint(role: str | Role, scope: str) -> bool:
        """Search results inside the painting section need the search right."""

        return can_view_paint_catalog(role) and (scope != "s" or can_search_paint(role))

    def paint_scope_status(scope: str) -> str | None:
        if scope == "in":
            return PaintStatus.IN_PROGRESS.value
        if scope == "done":
            return PaintStatus.DONE.value
        return None

    def parse_paint_ref(raw: str) -> tuple[int, str, str, int] | None:
        """Validate a ``card_id|scope|query|offset`` reference from a callback."""

        parts = (raw or "").split("|")
        if len(parts) != 4:
            return None
        card_id_raw, scope, query, offset_raw = parts
        if scope not in paint_scopes:
            return None
        try:
            card_id, offset = int(card_id_raw), int(offset_raw)
        except (TypeError, ValueError):
            return None
        if card_id <= 0 or offset < 0:
            return None
        if scope == "s":
            if parse_search_query(query) is None:
                return None
        elif query != "-":
            return None
        return card_id, scope, query, offset

    def paint_card_caption(
        card: PaintCard,
        language: str,
        *,
        position: int | None = None,
        total: int | None = None,
    ) -> str:
        created_at = card.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        local_date = created_at.astimezone(config.timezone).strftime("%d.%m.%Y %H:%M")
        owner = html.escape(card.owner_name or str(card.owner_id))
        masked = mask_vin(card.vin_full, card.vin_suffix6)
        completed = normalize_paint_status(card.status) is PaintStatus.DONE
        lines = [
            t(language, "paint_card_title", card_id=card.id),
            t(language, "card_vin", masked_vin=masked),
            t(
                language,
                "card_search_keys",
                suffix6=card.vin_suffix6,
                suffix4=card.vin_suffix6[-4:],
            ),
            t(language, "paint_status_done" if completed else "paint_status_in"),
            t(language, "paint_card_sent", owner=owner),
            t(language, "card_date", date=local_date),
        ]
        if completed:
            taken_by = card.completed_by_name or card.completed_by
            lines.append(
                t(
                    language,
                    "paint_card_taken",
                    owner=html.escape(str(taken_by)) if taken_by else "—",
                )
            )
            if card.completed_at is not None:
                completed_at = card.completed_at
                if completed_at.tzinfo is None:
                    completed_at = completed_at.replace(tzinfo=UTC)
                lines.append(
                    t(
                        language,
                        "paint_card_taken_date",
                        date=completed_at.astimezone(config.timezone).strftime(
                            "%d.%m.%Y %H:%M"
                        ),
                    )
                )
        if position is not None and total is not None:
            lines.append(t(language, "card_position", position=position, total=total))
        return "\n".join(lines)

    def paint_markup(
        language: str,
        card: PaintCard,
        *,
        scope: str,
        query: str,
        offset: int,
        total: int,
        viewer_role: str | Role,
        showing_vin: bool = False,
    ) -> InlineKeyboardMarkup:
        completed = normalize_paint_status(card.status) is PaintStatus.DONE
        return paint_card_keyboard(
            language,
            scope=scope,
            query=query,
            offset=offset,
            total=total,
            card_id=card.id,
            can_complete=can_complete_paint(viewer_role) and not completed,
            showing_vin=showing_vin,
        )

    async def send_paint_card(
        message: Message,
        card: PaintCard,
        language: str,
        *,
        scope: str,
        query: str,
        offset: int,
        total: int,
        viewer_role: str | Role,
    ) -> None:
        await message.answer_photo(
            photo=card.vehicle_photo_file_id,
            caption=paint_card_caption(
                card, language, position=offset + 1, total=total
            ),
            reply_markup=paint_markup(
                language,
                card,
                scope=scope,
                query=query,
                offset=offset,
                total=total,
                viewer_role=viewer_role,
            ),
        )

    async def edit_paint_card(
        message: Message,
        card: PaintCard,
        language: str,
        *,
        scope: str,
        query: str,
        offset: int,
        total: int,
        viewer_role: str | Role,
        showing_vin: bool = False,
    ) -> None:
        if showing_vin:
            photo_file_id = card.vin_photo_file_id
            caption = t(language, "paint_card_vin_view", card_id=card.id)
        else:
            photo_file_id = card.vehicle_photo_file_id
            caption = paint_card_caption(
                card, language, position=offset + 1, total=total
            )
        media = InputMediaPhoto(
            media=photo_file_id, caption=caption, parse_mode=ParseMode.HTML
        )
        markup = paint_markup(
            language,
            card,
            scope=scope,
            query=query,
            offset=offset,
            total=total,
            viewer_role=viewer_role,
            showing_vin=showing_vin,
        )
        try:
            await message.edit_media(media=media, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                logger.warning("Не удалось обновить карточку покраски: %s", exc)

    async def show_paint_page(
        message: Message,
        *,
        language: str,
        scope: str,
        query: str | None,
        offset: int,
        viewer_role: str | Role,
    ) -> bool:
        status = paint_scope_status(scope)
        card, total = await repository.get_paint_page(
            status=status, query=query, offset=offset
        )
        if card is None:
            key = paint_empty_keys[scope]
            kwargs = {"query": query} if scope == "s" else {}
            await message.answer(
                t(language, key, **kwargs),
                reply_markup=main_menu(language, role=safe_role(viewer_role)),
            )
            return False
        await send_paint_card(
            message,
            card,
            language,
            scope=scope,
            query=query or "-",
            offset=offset,
            total=total,
            viewer_role=viewer_role,
        )
        return True

    async def show_paint_first_page(
        message: Message,
        *,
        language: str,
        query: str | None,
        viewer_role: str | Role,
    ) -> bool:
        scope = "s" if query else "in"
        return await show_paint_page(
            message,
            language=language,
            scope=scope,
            query=query,
            offset=0,
            viewer_role=viewer_role,
        )

    async def refresh_after_paint_take(
        callback: CallbackQuery,
        language: str,
        *,
        card_id: int,
        scope: str,
        query: str,
        offset: int,
        viewer_role: str | Role,
    ) -> None:
        status = paint_scope_status(scope)
        search_query = query if scope == "s" else None
        card, position, total = await repository.get_paint_card_position(
            card_id, status=status, query=search_query
        )
        if card is not None:
            offset = position
        else:
            card, total = await repository.get_paint_page(
                status=status, query=search_query, offset=offset
            )
            offset = min(offset, max(total - 1, 0))
        if card is None or callback.message is None:
            key = paint_empty_keys[scope]
            kwargs = {"query": query} if scope == "s" else {}
            if callback.message is not None:
                with contextlib.suppress(TelegramBadRequest):
                    await callback.message.edit_caption(
                        caption=t(language, key, **kwargs), reply_markup=None
                    )
            return
        await edit_paint_card(
            callback.message,
            card,
            language,
            scope=scope,
            query=query,
            offset=offset,
            total=total,
            viewer_role=viewer_role,
        )

    async def show_paint_vin_confirmation(
        message: Message,
        state: FSMContext,
        language: str,
        *,
        vin_full: str | None,
        suffix6: str,
        confidence: float | None,
        observations: tuple[tuple[str, float], ...] = (),
    ) -> None:
        if (
            not is_valid_vin_fragment(suffix6, {6})
            or (vin_full is not None and not is_valid_vin(vin_full))
            or (vin_full is not None and not vin_full.endswith(suffix6))
            or (confidence is not None and not 0 <= confidence <= 100)
        ):
            await state.set_state(PaintCreateStates.manual_vin)
            await message.answer(t(language, "vin_invalid"))
            return
        await state.update_data(
            vin_full=vin_full,
            vin_suffix6=suffix6,
            ocr_confidence=confidence,
            vin_observations=remembered_observations(observations),
        )
        await state.set_state(PaintCreateStates.confirming)
        if vin_full and vin_check_digit_is_wrong(vin_full):
            await message.answer(t(language, "ocr_check_digit"))
        await message.answer(
            t(
                language,
                "ocr_found",
                vin_display=vin_full or mask_vin(None, suffix6),
                suffix=suffix6,
            ),
            reply_markup=paint_vin_confirmation_keyboard(language),
        )

    @router.message(F.text.in_(all_labels("btn_paint")))
    async def open_paint_menu(
        message: Message, state: FSMContext, lang: str, role: str
    ) -> None:
        await state.clear()
        await message.answer(
            t(lang, "paint_menu"),
            reply_markup=paint_menu_keyboard(lang, role=safe_role(role)),
        )

    @router.callback_query(F.data == "paint|menu")
    async def repaint_menu(callback: CallbackQuery, lang: str, role: str) -> None:
        """Re-open the painting menu.

        Telegram cannot turn a photo message into a text message, therefore the
        old message is removed and the menu is sent again.
        """

        if callback.message is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        await callback.answer()
        with contextlib.suppress(TelegramBadRequest):
            await callback.message.delete()
        await callback.message.answer(
            t(lang, "paint_menu"),
            reply_markup=paint_menu_keyboard(lang, role=safe_role(role)),
        )

    @router.callback_query(F.data == "paint|close")
    async def close_paint(callback: CallbackQuery) -> None:
        if callback.message:
            try:
                await callback.message.delete()
            except TelegramBadRequest:
                await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer()

    @router.callback_query(F.data == "paint|new")
    async def paint_new(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        if not permissions_for(safe_role(role)).can_create:
            await state.clear()
            await reject_callback_for_role(callback, lang)
            return
        await state.clear()
        await state.set_state(PaintCreateStates.vehicle_photo)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                t(lang, "paint_create_vehicle_photo"), reply_markup=cancel_menu(lang)
            )

    @router.callback_query(F.data == "paint|search")
    async def paint_search_start(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        if not can_search_paint(role):
            await state.clear()
            await reject_callback_for_role(callback, lang)
            return
        await state.clear()
        await state.set_state(PaintSearchStates.query)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                t(lang, "paint_search_prompt"), reply_markup=cancel_menu(lang)
            )

    @router.callback_query(F.data.startswith("paint|list|"))
    async def paint_list(callback: CallbackQuery, lang: str, role: str) -> None:
        if not can_view_paint_catalog(role):
            await reject_callback_for_role(callback, lang)
            return
        parts = (callback.data or "").split("|")
        if len(parts) != 4 or parts[2] not in {"in", "done"}:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        try:
            offset = int(parts[3])
            if offset < 0:
                raise ValueError
        except (TypeError, ValueError):
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        scope = parts[2]
        status = paint_scope_status(scope)
        card, total = await repository.get_paint_page(
            status=status, query=None, offset=offset
        )
        if callback.message is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        if card is None:
            await callback.answer(t(lang, paint_empty_keys[scope]), show_alert=True)
            with contextlib.suppress(TelegramBadRequest):
                await callback.message.edit_text(
                    f"{t(lang, 'paint_menu')}\n\n{t(lang, paint_empty_keys[scope])}",
                    reply_markup=paint_menu_keyboard(lang, role=safe_role(role)),
                )
            return
        await callback.answer()
        # The painting menu is a text message, and Telegram cannot convert a
        # text message into a photo, so the catalogue is sent as a new message.
        with contextlib.suppress(TelegramBadRequest):
            await callback.message.delete()
        await send_paint_card(
            callback.message,
            card,
            lang,
            scope=scope,
            query="-",
            offset=min(offset, max(total - 1, 0)),
            total=total,
            viewer_role=role,
        )

    @router.callback_query(F.data.startswith("ppage|"))
    async def paint_change_page(callback: CallbackQuery, lang: str, role: str) -> None:
        if not can_view_paint_catalog(role):
            await reject_callback_for_role(callback, lang)
            return
        parts = (callback.data or "").split("|", 3)
        if len(parts) != 4:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        _, scope, query, offset_raw = parts
        try:
            requested_offset = int(offset_raw)
            if requested_offset < 0:
                raise ValueError
        except (TypeError, ValueError):
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        if scope not in {"in", "done", "s"}:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        search_query = query if scope == "s" else None
        if scope == "s" and parse_search_query(query) is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        if not can_browse_paint(role, scope):
            await reject_callback_for_role(callback, lang)
            return
        card, total = await repository.get_paint_page(
            status=paint_scope_status(scope),
            query=search_query,
            offset=requested_offset,
        )
        if card is None or callback.message is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        offset = min(requested_offset, total - 1)
        await edit_paint_card(
            callback.message,
            card,
            lang,
            scope=scope,
            query=query,
            offset=offset,
            total=total,
            viewer_role=role,
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("pmedia|"))
    async def paint_switch_media(callback: CallbackQuery, lang: str, role: str) -> None:
        if not can_view_paint_catalog(role):
            await reject_callback_for_role(callback, lang)
            return
        parts = (callback.data or "").split("|", 5)
        if len(parts) != 6 or parts[1] not in {"i", "v"}:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        reference = parse_paint_ref("|".join(parts[2:]))
        if reference is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        card_id, scope, query, offset = reference
        if not can_browse_paint(role, scope):
            await reject_callback_for_role(callback, lang)
            return
        status = paint_scope_status(scope)
        search_query = query if scope == "s" else None
        card, offset, total = await repository.get_paint_card_position(
            card_id, status=status, query=search_query
        )
        if card is None or callback.message is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        await edit_paint_card(
            callback.message,
            card,
            lang,
            scope=scope,
            query=query,
            offset=offset,
            total=total,
            viewer_role=role,
            showing_vin=parts[1] == "i",
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("paint|takeask|"))
    async def paint_ask_take(callback: CallbackQuery, lang: str, role: str) -> None:
        if not can_complete_paint(role):
            await callback.answer(t(lang, "role_forbidden"), show_alert=True)
            return
        reference = parse_paint_ref((callback.data or "").split("|", 2)[-1])
        if reference is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        card_id, scope, query, offset = reference
        card = await repository.get_paint_card(card_id)
        if card is None or callback.message is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        if normalize_paint_status(card.status) is PaintStatus.DONE:
            await callback.answer(t(lang, "paint_already_taken"), show_alert=True)
            return
        caption = (
            f"{paint_card_caption(card, lang)}\n\n"
            f"<b>{t(lang, 'paint_take_question', card_id=card.id)}</b>"
        )
        await callback.message.edit_caption(
            caption=caption,
            reply_markup=paint_take_keyboard(
                lang, card_id=card.id, scope=scope, query=query, offset=offset
            ),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("paint|takeno|"))
    async def paint_cancel_take(callback: CallbackQuery, lang: str, role: str) -> None:
        if not can_complete_paint(role):
            await callback.answer(t(lang, "role_forbidden"), show_alert=True)
            return
        reference = parse_paint_ref((callback.data or "").split("|", 2)[-1])
        if reference is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        card_id, scope, query, offset = reference
        status = paint_scope_status(scope)
        card, total = await repository.get_paint_page(
            status=status, query=query if scope == "s" else None, offset=offset
        )
        if card is None or card.id != card_id or callback.message is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        await edit_paint_card(
            callback.message,
            card,
            lang,
            scope=scope,
            query=query,
            offset=offset,
            total=total,
            viewer_role=role,
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("paint|takeyes|"))
    async def paint_confirm_take(
        callback: CallbackQuery, lang: str, role: str, display_name: str
    ) -> None:
        if not can_complete_paint(role):
            await callback.answer(t(lang, "role_forbidden"), show_alert=True)
            return
        reference = parse_paint_ref((callback.data or "").split("|", 2)[-1])
        if reference is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        card_id, scope, query, offset = reference
        card = await repository.get_paint_card(card_id)
        if card is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        if normalize_paint_status(card.status) is PaintStatus.DONE:
            await callback.answer(t(lang, "paint_already_taken"), show_alert=True)
            return
        moved = await repository.complete_paint_card(
            card_id, callback.from_user.id, display_name
        )
        if not moved:
            await callback.answer(t(lang, "paint_already_taken"), show_alert=True)
            return
        await callback.answer(t(lang, "paint_taken", card_id=card_id))
        await refresh_after_paint_take(
            callback,
            lang,
            card_id=card_id,
            scope=scope,
            query=query,
            offset=offset,
            viewer_role=role,
        )

    @router.message(PaintCreateStates.vehicle_photo)
    async def receive_paint_vehicle_photo(
        message: Message, state: FSMContext, lang: str, role: str
    ) -> None:
        if not permissions_for(safe_role(role)).can_create:
            await reject_message_for_role(message, state, lang, role)
            return
        if not message.photo:
            await message.answer(t(lang, "paint_vehicle_photo_required"))
            return
        photo = message.photo[-1]
        validation_error = photo_validation_error(photo)
        if validation_error:
            await message.answer(t(lang, validation_error))
            return
        await state.update_data(
            paint_vehicle_photo_file_id=photo.file_id,
            paint_vehicle_photo_unique_id=photo.file_unique_id,
        )
        await state.set_state(PaintCreateStates.vin_photo)
        await message.answer(
            t(lang, "paint_create_vin_photo"), reply_markup=cancel_menu(lang)
        )

    @router.message(PaintCreateStates.vin_photo)
    async def receive_paint_vin_photo(
        message: Message,
        state: FSMContext,
        lang: str,
        bot: Bot,
        role: str,
    ) -> None:
        if not permissions_for(safe_role(role)).can_create:
            await reject_message_for_role(message, state, lang, role)
            return
        if not message.photo:
            await message.answer(t(lang, "paint_vin_photo_required"))
            return
        photo = message.photo[-1]
        validation_error = photo_validation_error(photo, vin_crop=True)
        if validation_error:
            await message.answer(t(lang, validation_error))
            return
        data = await state.get_data()
        if photo.file_unique_id == data.get("paint_vehicle_photo_unique_id"):
            await message.answer(t(lang, "photo_reused"))
            return
        file_id = photo.file_id
        await state.update_data(
            paint_vin_photo_file_id=file_id,
            paint_vin_photo_unique_id=photo.file_unique_id,
        )
        processing = await message.answer(t(lang, "ocr_processing"))
        try:
            result, report, second_opinion = await read_and_report(bot, file_id, lang)
        except OCRUnavailableError:
            logger.exception("Модуль OCR недоступен")
            await state.set_state(PaintCreateStates.manual_vin)
            await processing.edit_text(t(lang, "ocr_unavailable"))
            return
        except (ValueError, OSError):
            logger.exception("Не удалось обработать изображение VIN для покраски")
            await state.set_state(PaintCreateStates.manual_vin)
            await processing.edit_text(t(lang, "ocr_not_found"))
            return

        with contextlib.suppress(TelegramBadRequest):
            await processing.delete()

        if second_opinion:
            await message.answer(second_opinion)

        vin, shaky = judged_vin(result)
        if vin and result.suffix6:
            if report.partial_vin and UNREADABLE in report.partial_vin:
                await show_partial_reading(
                    message,
                    state,
                    lang,
                    report.partial_vin,
                    prefix="pvin",
                    manual_state=PaintCreateStates.manual_vin,
                )
                return
            if shaky and not vin_check_digit_is_wrong(vin):
                await message.answer(t(lang, "ocr_weak"))
            if report.need_retake and report.retake_instructions:
                await message.answer(
                    t(
                        lang,
                        "ocr_retake",
                        instructions=html.escape(report.retake_instructions),
                    )
                )
            await show_paint_vin_confirmation(
                message,
                state,
                lang,
                vin_full=result.vin,
                suffix6=result.suffix6,
                confidence=result.confidence,
                observations=result.observations,
            )
            return

        await state.set_state(PaintCreateStates.manual_vin)
        if report.need_retake and report.retake_instructions:
            await message.answer(
                t(
                    lang,
                    "ocr_retake",
                    instructions=html.escape(report.retake_instructions),
                )
            )
        if (result.raw_text or "").strip():
            await message.answer(t(lang, "ocr_not_found"))
        else:
            await message.answer(t(lang, "ocr_no_text"))

    @router.message(PaintCreateStates.manual_vin)
    async def receive_paint_manual_vin(
        message: Message, state: FSMContext, lang: str, role: str
    ) -> None:
        if not permissions_for(safe_role(role)).can_create:
            await reject_message_for_role(message, state, lang, role)
            return
        if not message.text:
            await message.answer(t(lang, "manual_vin_prompt"))
            return
        if len(message.text) > 64:
            await message.answer(t(lang, "text_too_long"))
            return
        parsed = parse_manual_card_vin(message.text)
        if parsed is None:
            await message.answer(t(lang, "vin_invalid"))
            return
        vin_full, suffix6 = parsed
        await show_paint_vin_confirmation(
            message,
            state,
            lang,
            vin_full=vin_full,
            suffix6=suffix6,
            confidence=None,
        )

    @router.callback_query(F.data == "pvin|edit")
    async def paint_edit_vin(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        if not permissions_for(safe_role(role)).can_create:
            await state.clear()
            await reject_callback_for_role(callback, lang)
            return
        if await state.get_state() != PaintCreateStates.confirming.state:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        await state.set_state(PaintCreateStates.manual_vin)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                t(lang, "manual_vin_prompt"), reply_markup=cancel_menu(lang)
            )

    @router.message(PaintCreateStates.confirming)
    async def receive_corrected_paint_vin(
        message: Message, state: FSMContext, lang: str, role: str
    ) -> None:
        """A code pasted back with a character put right in it."""

        if not permissions_for(safe_role(role)).can_create:
            await reject_message_for_role(message, state, lang, role)
            return
        if not message.text:
            return
        stripped = message.text.strip()
        latin = "".join(
            char for char in stripped.upper() if char.isascii() and char.isalnum()
        )
        if len(latin) < 6 or len(latin) > 64:
            return
        parsed = parse_manual_card_vin(stripped)
        if parsed is None:
            await message.answer(t(lang, "vin_invalid"))
            return
        vin_full, suffix6 = parsed
        await show_paint_vin_confirmation(
            message,
            state,
            lang,
            vin_full=vin_full,
            suffix6=suffix6,
            confidence=None,
        )

    @router.callback_query(F.data == "pvin|fix")
    async def fix_paint_character(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        """Ask which of the seventeen characters is the wrong one."""

        if not permissions_for(safe_role(role)).can_create:
            await state.clear()
            await reject_callback_for_role(callback, lang)
            return
        if await state.get_state() != PaintCreateStates.confirming.state:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        await callback.answer()
        if callback.message:
            await offer_fix_board(callback.message, state, lang, prefix="pvin")

    @router.callback_query(F.data.startswith("pvin|fixpos|"))
    async def fix_paint_position(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        """Ask what the chosen character should be instead."""

        if not permissions_for(safe_role(role)).can_create:
            await state.clear()
            await reject_callback_for_role(callback, lang)
            return
        try:
            index = int(callback.data.rsplit("|", 1)[-1])
        except (TypeError, ValueError):
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        await callback.answer()
        if callback.message:
            await offer_replacements(
                callback.message, state, lang, prefix="pvin", index=index
            )

    @router.callback_query(F.data.startswith("pvin|fixset|"))
    async def set_paint_character(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        """Put the chosen character in place and show the code again."""

        if not permissions_for(safe_role(role)).can_create:
            await state.clear()
            await reject_callback_for_role(callback, lang)
            return
        try:
            _prefix, index_text, char = callback.data.split("|")[1:]
            index = int(index_text)
        except (TypeError, ValueError):
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        if len(char) != 1 or char not in VIN_ALPHABET:
            await callback.answer(t(lang, "vin_invalid"), show_alert=True)
            return
        await callback.answer()
        if callback.message:
            await apply_character_fix(
                callback.message,
                state,
                lang,
                index=index,
                char=char,
                confirming_state=PaintCreateStates.confirming,
                manual_state=PaintCreateStates.manual_vin,
                show_confirmation=show_paint_vin_confirmation,
                prefix="pvin",
            )

    @router.callback_query(F.data == "pvin|fixback")
    async def fix_paint_back(callback: CallbackQuery, lang: str) -> None:
        """Close the correction board."""

        await callback.answer()
        with contextlib.suppress(TelegramBadRequest):
            if callback.message:
                await callback.message.delete()

    @router.callback_query(F.data == "pvin|retake")
    async def paint_retake_vin(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        if not permissions_for(safe_role(role)).can_create:
            await state.clear()
            await reject_callback_for_role(callback, lang)
            return
        if await state.get_state() != PaintCreateStates.confirming.state:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        await state.set_state(PaintCreateStates.vin_photo)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                t(lang, "paint_create_vin_photo"), reply_markup=cancel_menu(lang)
            )

    @router.callback_query(F.data == "pflow|cancel")
    async def paint_cancel_flow(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        await state.clear()
        await callback.answer()
        if callback.message:
            with contextlib.suppress(TelegramBadRequest):
                await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(
                t(lang, "cancelled"),
                reply_markup=main_menu(lang, role=safe_role(role)),
            )

    @router.callback_query(F.data == "pvin|ok")
    async def save_paint_card(
        callback: CallbackQuery,
        state: FSMContext,
        lang: str,
        role: str,
        display_name: str,
    ) -> None:
        if not permissions_for(safe_role(role)).can_create:
            await state.clear()
            await reject_callback_for_role(callback, lang)
            return
        if await state.get_state() != PaintCreateStates.confirming.state:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        data = await state.get_data()
        required = {
            "paint_vehicle_photo_file_id",
            "paint_vehicle_photo_unique_id",
            "paint_vin_photo_file_id",
            "paint_vin_photo_unique_id",
            "vin_suffix6",
        }
        unique_photo_ids = {
            data.get("paint_vehicle_photo_unique_id"),
            data.get("paint_vin_photo_unique_id"),
        }
        if (
            not required.issubset(data)
            or None in unique_photo_ids
            or len(unique_photo_ids) != 2
        ):
            await state.clear()
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return

        vin_full = data.get("vin_full")
        if vin_full and UNREADABLE in vin_full:
            await callback.answer(t(lang, "vin_has_gaps"), show_alert=True)
            return
        if vin_full:
            duplicate = await repository.find_active_paint_by_full_vin(vin_full)
            if duplicate is not None:
                await state.clear()
                await callback.answer()
                if callback.message:
                    with contextlib.suppress(TelegramBadRequest):
                        await callback.message.edit_reply_markup(reply_markup=None)
                    await callback.message.answer(
                        t(lang, "paint_duplicate", card_id=duplicate.id),
                        reply_markup=main_menu(lang, role=safe_role(role)),
                    )
                return

        try:
            card = await repository.create_paint_card(
                owner_id=callback.from_user.id,
                owner_name=display_name,
                vehicle_photo_file_id=data["paint_vehicle_photo_file_id"],
                vin_photo_file_id=data["paint_vin_photo_file_id"],
                vin_full=vin_full,
                vin_suffix6=data["vin_suffix6"],
                ocr_confidence=data.get("ocr_confidence"),
            )
            await remember_creation(
                callback.bot, card, kind=ARCHIVE_KIND_PAINT, owner=display_name
            )
        except ValueError:
            logger.exception("Не удалось сохранить карточку покраски")
            await state.clear()
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return

        await state.clear()
        await callback.answer()
        if callback.message:
            with contextlib.suppress(TelegramBadRequest):
                await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(
                t(lang, "paint_saved", card_id=card.id),
                reply_markup=main_menu(lang, role=safe_role(role)),
            )
            if can_view_paint_catalog(role):
                await send_paint_card(
                    callback.message,
                    card,
                    lang,
                    scope="o",
                    query="-",
                    offset=0,
                    total=1,
                    viewer_role=role,
                )

    @router.message(PaintSearchStates.query)
    async def receive_paint_search_query(
        message: Message,
        state: FSMContext,
        lang: str,
        bot: Bot,
        role: str,
    ) -> None:
        if not can_search_paint(role):
            await reject_message_for_role(message, state, lang, role)
            return
        query: str | None = None
        if message.photo:
            validation_error = photo_validation_error(message.photo[-1], vin_crop=True)
            if validation_error:
                await message.answer(t(lang, validation_error))
                return
            processing = await message.answer(t(lang, "ocr_processing"))
            try:
                result = await recognize_photo(bot, message.photo[-1].file_id)
                query = result.suffix6
            except (OCRUnavailableError, ValueError, OSError):
                logger.exception(
                    "Не удалось распознать VIN на фотографии для поиска в покраске"
                )
            with contextlib.suppress(TelegramBadRequest):
                await processing.delete()
            if not query:
                await message.answer(t(lang, "search_photo_failed"))
                return
        elif message.text:
            if len(message.text) > 64:
                await message.answer(t(lang, "text_too_long"))
                return
            query = parse_search_query(message.text)
        if not query:
            await message.answer(t(lang, "search_invalid"))
            return

        await state.clear()
        await show_paint_first_page(
            message,
            language=lang,
            query=query,
            viewer_role=role,
        )
        await message.answer(
            t(lang, "main_menu"),
            reply_markup=main_menu(lang, role=safe_role(role)),
        )

    # ------------------------------------------------------------- backups

    BACKUP_PAGE_SIZE = 5
    TRASH_KEEP_DAYS = 30
    JOURNAL_PAGE_SIZE = 12
    AUDIT_ICONS = {
        AuditAction.CARD_CREATED: ("➕", "audit_card_created"),
        AuditAction.CARD_DELETED: ("🗑", "audit_card_deleted"),
        AuditAction.CARD_RESTORED: ("♻️", "audit_card_restored"),
        AuditAction.CARD_PURGED: ("🔥", "audit_card_purged"),
        AuditAction.BACKUP_CREATED: ("💾", "audit_backup_created"),
        AuditAction.BACKUP_EXPORTED: ("📤", "audit_backup_exported"),
        AuditAction.BACKUP_UPLOADED: ("📥", "audit_backup_uploaded"),
        AuditAction.BACKUP_RESTORED: ("🕘", "audit_backup_restored"),
        AuditAction.ROLE_CHANGED: ("🔑", "audit_role_changed"),
        AuditAction.USER_RENAMED: ("✏️", "audit_user_renamed"),
    }

    def can_manage_backups(role: str | Role) -> bool:
        """Backups belong to administrators and to the main administrator."""

        return permissions_for(safe_role(role)).can_view_statistics

    def is_main_admin(user_id: int) -> bool:
        return user_id in set(config.admin_user_ids)

    async def build_backup_text(lang: str) -> str:
        snapshots = await asyncio.to_thread(list_snapshots, config.backup_dir)
        database_path = config.sqlite_path
        size = (
            format_size(database_path.stat().st_size)
            if database_path is not None and database_path.exists()
            else "—"
        )
        last = snapshots[0].label(lang) if snapshots else t(lang, "backup_last_never")
        _, trash_total = await repository.list_deleted_cards(offset=0, limit=1)
        return t(
            lang,
            "backup_title",
            snapshots=len(snapshots),
            last=last,
            size=size,
            trash=trash_total,
        )

    async def load_snapshot(name: str):
        """Return the snapshot with this exact file name, or None."""

        snapshots = await asyncio.to_thread(list_snapshots, config.backup_dir)
        return next((item for item in snapshots if item.path.name == name), None)

    @router.callback_query(F.data == "bkp|menu")
    async def open_backups(callback: CallbackQuery, lang: str, role: str) -> None:
        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        text = await build_backup_text(lang)
        try:
            await callback.message.edit_text(
                text, reply_markup=backup_menu_keyboard(lang)
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
        await callback.answer()

    @router.callback_query(F.data == "bkp|export")
    async def export_backup(
        callback: CallbackQuery, lang: str, role: str, display_name: str
    ) -> None:
        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        database_path = config.sqlite_path
        if database_path is None or not database_path.exists():
            await callback.answer(t(lang, "backup_no_sqlite"), show_alert=True)
            return
        try:
            snapshot = await asyncio.to_thread(
                create_snapshot, database_path, config.backup_dir
            )
            await asyncio.to_thread(rotate_snapshots, config.backup_dir)
        except Exception:
            logger.exception("Не удалось создать резервную копию")
            await callback.answer(t(lang, "backup_export_failed"), show_alert=True)
            return

        data = await asyncio.to_thread(snapshot.path.read_bytes)
        parts = split_for_telegram(data)
        with contextlib.suppress(Exception):
            await repository.add_audit(
                actor_id=callback.from_user.id,
                actor_name=display_name,
                action=AuditAction.BACKUP_EXPORTED,
                details=snapshot.path.name,
            )
        await callback.answer()
        stamp = snapshot.created_at.astimezone(config.timezone).strftime(
            "%d.%m.%Y %H:%M"
        )
        for index, part in enumerate(parts, start=1):
            name = (
                snapshot.path.name
                if len(parts) == 1
                else f"{snapshot.path.name}.part{index}"
            )
            await callback.message.answer_document(
                BufferedInputFile(part, filename=name),
                caption=t(
                    lang,
                    "backup_export_caption",
                    date=stamp,
                    size=format_size(len(part)),
                ),
            )

    @router.callback_query(F.data == "bkp|import")
    async def import_backup(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        if config.sqlite_path is None:
            await callback.answer(t(lang, "backup_no_sqlite"), show_alert=True)
            return
        await state.set_state(BackupStates.waiting_file)
        await callback.message.edit_text(
            t(lang, "backup_import_prompt"),
            reply_markup=backup_import_keyboard(lang),
        )
        await callback.answer()

    @router.message(BackupStates.waiting_file)
    async def receive_backup_file(
        message: Message,
        state: FSMContext,
        lang: str,
        role: str,
        bot: Bot,
        display_name: str,
    ) -> None:
        if not can_manage_backups(role):
            await state.clear()
            await message.answer(
                t(lang, "backup_forbidden"),
                reply_markup=main_menu(lang, role=safe_role(role)),
            )
            return
        document = message.document
        if document is None:
            await message.answer(
                t(
                    lang,
                    "backup_import_bad",
                    reason=t(lang, "backup_import_need_file"),
                    cancel=t(lang, "btn_cancel"),
                ),
                reply_markup=backup_import_keyboard(lang),
            )
            return
        try:
            file = await bot.get_file(document.file_id)
            buffer = await bot.download(file)
            raw = buffer.read() if hasattr(buffer, "read") else bytes(buffer)
            plain = await asyncio.to_thread(decompress, raw)
            await asyncio.to_thread(validate_sqlite, plain)
            counts = await asyncio.to_thread(table_counts, plain)
        except BackupError as exc:
            await message.answer(
                t(
                    lang,
                    "backup_import_bad",
                    reason=html.escape(str(exc)),
                    cancel=t(lang, "btn_cancel"),
                ),
                reply_markup=backup_import_keyboard(lang),
            )
            return
        except Exception:
            logger.exception("Не удалось прочитать файл базы")
            await message.answer(
                t(
                    lang,
                    "backup_import_bad",
                    reason=t(lang, "backup_import_error"),
                    cancel=t(lang, "btn_cancel"),
                ),
                reply_markup=backup_import_keyboard(lang),
            )
            return

        descriptor, temporary_path = tempfile.mkstemp(
            prefix="vinbot-import-", suffix=".db"
        )
        os.close(descriptor)
        await asyncio.to_thread(Path(temporary_path).write_bytes, plain)
        await state.update_data(import_path=temporary_path)
        await state.set_state(BackupStates.confirming)
        stats = await repository.get_admin_stats(config.admin_user_ids)
        await message.answer(
            t(
                lang,
                "backup_import_received",
                cards=counts.get("vehicle_cards", 0),
                users=counts.get("users", 0),
                size=format_size(len(plain)),
                current_cards=stats.active_cards,
            ),
            reply_markup=backup_apply_keyboard(lang),
        )

    @router.callback_query(F.data == "bkp|cancel")
    async def cancel_backup(
        callback: CallbackQuery, state: FSMContext, lang: str
    ) -> None:
        data = await state.get_data()
        temporary_path = data.get("import_path")
        await state.clear()
        if temporary_path:
            with contextlib.suppress(OSError):
                Path(temporary_path).unlink()
        await callback.answer(t(lang, "operation_cancelled"), show_alert=True)
        if callback.message is None:
            return
        try:
            await callback.message.edit_text(
                await build_backup_text(lang),
                reply_markup=backup_menu_keyboard(lang),
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    @router.callback_query(F.data == "bkp|apply")
    async def apply_backup(
        callback: CallbackQuery,
        state: FSMContext,
        lang: str,
        role: str,
        display_name: str,
    ) -> None:
        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        if await state.get_state() != BackupStates.confirming.state:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        data = await state.get_data()
        temporary_path = data.get("import_path")
        if not temporary_path or not Path(temporary_path).exists():
            await state.clear()
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        database_path = config.sqlite_path
        if database_path is None:
            await state.clear()
            await callback.answer(t(lang, "backup_no_sqlite"), show_alert=True)
            return

        plain = await asyncio.to_thread(Path(temporary_path).read_bytes)
        safety = None
        try:
            if database_path.exists():
                # The current database is always preserved before a swap.
                safety = await asyncio.to_thread(
                    create_snapshot, database_path, config.backup_dir
                )
            counts = await asyncio.to_thread(restore_snapshot, database_path, plain)
        except Exception:
            logger.exception("Не удалось загрузить базу данных")
            await callback.answer(t(lang, "backup_import_failed"), show_alert=True)
            return
        finally:
            with contextlib.suppress(OSError):
                Path(temporary_path).unlink()
        await state.clear()

        with contextlib.suppress(Exception):
            await repository.add_audit(
                actor_id=callback.from_user.id,
                actor_name=display_name,
                action=AuditAction.BACKUP_UPLOADED,
                details=f"карточек {counts.get('vehicle_cards', 0)}",
            )
        await callback.answer()
        await callback.message.answer(
            t(
                lang,
                "backup_import_done",
                cards=counts.get("vehicle_cards", 0),
                users=counts.get("users", 0),
                snapshot=safety.path.name if safety else "—",
            ),
            reply_markup=backup_menu_keyboard(lang),
        )

    @router.callback_query(F.data.startswith("bkp|list|"))
    async def list_backups(callback: CallbackQuery, lang: str, role: str) -> None:
        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        raw_offset = (callback.data or "").rsplit("|", 1)[-1]
        offset = int(raw_offset) if raw_offset.isdigit() else 0
        snapshots = await asyncio.to_thread(list_snapshots, config.backup_dir)
        if not snapshots:
            await callback.message.edit_text(
                t(lang, "backup_list_empty"),
                reply_markup=snapshot_keyboard(
                    lang, snapshots=[], offset=0, page_size=BACKUP_PAGE_SIZE
                ),
            )
            await callback.answer()
            return
        pages = max(1, math.ceil(len(snapshots) / BACKUP_PAGE_SIZE))
        page = min(offset // BACKUP_PAGE_SIZE + 1, pages)
        await callback.message.edit_text(
            t(lang, "backup_list_title", page=page, pages=pages),
            reply_markup=snapshot_keyboard(
                lang,
                snapshots=snapshots,
                offset=offset,
                page_size=BACKUP_PAGE_SIZE,
            ),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("bkp|pick|"))
    async def pick_backup(callback: CallbackQuery, lang: str, role: str) -> None:
        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        name = (callback.data or "").split("|", 2)[-1]
        snapshot = await load_snapshot(name)
        if snapshot is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        await callback.message.edit_text(
            t(lang, "backup_confirm", label=snapshot.label(lang)),
            reply_markup=snapshot_confirm_keyboard(lang, snapshot.path.name),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("bkp|restore|"))
    async def restore_backup(
        callback: CallbackQuery, lang: str, role: str, display_name: str
    ) -> None:
        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        name = (callback.data or "").split("|", 2)[-1]
        snapshot = await load_snapshot(name)
        database_path = config.sqlite_path
        if snapshot is None or database_path is None:
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        try:
            plain = await asyncio.to_thread(decompress, snapshot.path.read_bytes())
            if database_path.exists():
                await asyncio.to_thread(
                    create_snapshot, database_path, config.backup_dir
                )
            counts = await asyncio.to_thread(restore_snapshot, database_path, plain)
        except Exception:
            logger.exception("Не удалось откатить базу данных")
            await callback.answer(t(lang, "backup_import_failed"), show_alert=True)
            return
        with contextlib.suppress(Exception):
            await repository.add_audit(
                actor_id=callback.from_user.id,
                actor_name=display_name,
                action=AuditAction.BACKUP_RESTORED,
                details=f"{snapshot.path.name} → карточек {counts.get('vehicle_cards', 0)}",
            )
        await callback.answer()
        await callback.message.answer(
            t(
                lang,
                "backup_restored",
                label=snapshot.label(lang),
                cards=counts.get("vehicle_cards", 0),
                users=counts.get("users", 0),
            ),
            reply_markup=backup_menu_keyboard(lang),
        )

    # ----------------------------------------------------------- trash bin

    TRASH_PAGE_SIZE = 8

    async def trash_query_of(state: FSMContext) -> str | None:
        data = await state.get_data()
        raw = data.get("trash_query")
        return raw.strip() if isinstance(raw, str) and raw.strip() else None

    async def show_trash_list(
        target,
        lang: str,
        offset: int,
        *,
        query: str | None,
        replace: bool,
    ) -> None:
        """Show a page of deleted cards; each card opens from its own button."""

        total = await repository.count_deleted_cards(query=query)
        page: list[tuple[int, str]] = []
        safe_offset = 0
        if total == 0:
            text = t(
                lang,
                "trash_nothing_found" if query else "trash_empty",
                days=TRASH_KEEP_DAYS,
                query=html.escape(query or ""),
            )
        else:
            last_page = ((total - 1) // TRASH_PAGE_SIZE) * TRASH_PAGE_SIZE
            safe_offset = max(0, min(offset, last_page))
            cards, _ = await repository.list_deleted_cards(
                offset=safe_offset, limit=TRASH_PAGE_SIZE, query=query
            )
            lines: list[str] = []
            for index, card in enumerate(cards, safe_offset + 1):
                moment = card.deleted_at or card.created_at
                local = moment.astimezone(config.timezone)
                owner = html.escape(card.owner_name or str(card.owner_id))
                masked = mask_vin(card.vin_full, card.vin_suffix6)
                lines.append(
                    t(
                        lang,
                        "trash_list_line",
                        index=index,
                        card_id=card.id,
                        vin=masked,
                        date=local.strftime("%d.%m.%Y"),
                        owner=owner,
                    )
                )
                page.append(
                    (
                        card.id,
                        t(
                            lang,
                            "trash_list_button",
                            card_id=card.id,
                            vin=masked[-6:],
                            date=local.strftime("%d.%m"),
                            owner=owner[:14],
                        ),
                    )
                )
            filter_line = ""
            if query:
                filter_line = (
                    t(lang, "trash_filter_active", query=html.escape(query)) + "\n"
                )
            headline = t(
                lang,
                "trash_list_found" if query else "trash_list_total",
                total=total,
            )
            text = t(
                lang,
                "trash_list_title",
                total=total,
                headline=headline,
                filter=filter_line,
                lines="\n".join(lines),
                page=safe_offset // TRASH_PAGE_SIZE + 1,
                pages=math.ceil(total / TRASH_PAGE_SIZE),
                days=TRASH_KEEP_DAYS,
            )
        keyboard = trash_list_keyboard(
            lang,
            offset=safe_offset,
            total=total,
            page_size=TRASH_PAGE_SIZE,
            page=page,
            query=query,
        )
        if replace and not target.photo:
            await target.edit_text(text, reply_markup=keyboard)
            return
        if replace:
            with contextlib.suppress(TelegramBadRequest):
                await target.delete()
        await target.answer(text, reply_markup=keyboard)

    async def render_trash_card(
        target,
        lang: str,
        card_id: int,
        *,
        offset: int,
        can_purge: bool,
    ) -> None:
        """Show one deleted card with the buttons that bring it back."""

        card = await repository.get_deleted_card(card_id)
        if card is None:
            await show_trash_list(target, lang, offset, query=None, replace=False)
            return
        deleter = t(lang, "trash_deleter_unknown")
        if card.deleted_by:
            deleter_user = await repository.get_user(card.deleted_by)
            if deleter_user is not None:
                deleter = html.escape(display_name_of(deleter_user))
        moment = card.deleted_at or card.created_at
        date = moment.astimezone(config.timezone).strftime("%d.%m.%Y %H:%M")
        caption = t(
            lang,
            "trash_card",
            card_id=card.id,
            vin=html.escape(card.vin_full or f"…{card.vin_suffix6}"),
            owner=html.escape(card.owner_name or str(card.owner_id)),
            deleter=deleter,
            date=date,
        )
        await target.answer_photo(
            card.vehicle_photo_file_id,
            caption=caption,
            reply_markup=trash_keyboard(
                lang,
                card_id=card.id,
                offset=offset,
                can_purge=can_purge,
                list_offset=(offset // TRASH_PAGE_SIZE) * TRASH_PAGE_SIZE,
            ),
        )

    @router.callback_query(F.data.regexp(r"^trash\|list\|\d+$"))
    async def show_trash(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        raw_offset = (callback.data or "").rsplit("|", 1)[-1]
        offset = int(raw_offset) if raw_offset.isdigit() else 0
        await show_trash_list(
            callback.message,
            lang,
            offset,
            query=await trash_query_of(state),
            replace=True,
        )
        await callback.answer()

    @router.callback_query(F.data.regexp(r"^trash\|\d+$"))
    async def show_trash_card_page(
        callback: CallbackQuery, lang: str, role: str
    ) -> None:
        """Open the bin straight on a card (the old one-by-one paging)."""

        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        raw_offset = (callback.data or "").rsplit("|", 1)[-1]
        offset = int(raw_offset) if raw_offset.isdigit() else 0
        cards, _ = await repository.list_deleted_cards(offset=offset, limit=1)
        with contextlib.suppress(TelegramBadRequest):
            await callback.message.delete()
        if not cards:
            await show_trash_list(callback.message, lang, 0, query=None, replace=False)
        else:
            await render_trash_card(
                callback.message,
                lang,
                cards[0].id,
                offset=offset,
                can_purge=is_main_admin(callback.from_user.id),
            )
        await callback.answer()

    @router.callback_query(F.data.regexp(r"^trash\|open\|\d+\|\d+$"))
    async def open_trash_card(callback: CallbackQuery, lang: str, role: str) -> None:
        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        parts = (callback.data or "").split("|")
        card_id, offset = int(parts[2]), int(parts[3])
        with contextlib.suppress(TelegramBadRequest):
            await callback.message.delete()
        await render_trash_card(
            callback.message,
            lang,
            card_id,
            offset=offset,
            can_purge=is_main_admin(callback.from_user.id),
        )
        await callback.answer()

    @router.callback_query(F.data == "trash|menu")
    async def open_trash_from_menu(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        """Opening the bin from the menu starts without the previous filter."""

        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        await state.set_state(None)
        await state.update_data(trash_query=None)
        await show_trash_list(callback.message, lang, 0, query=None, replace=True)
        await callback.answer()

    @router.callback_query(F.data == "trash|cancel")
    async def trash_cancel_search(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        """Abandon the search prompt and go back to the bin."""

        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        await state.set_state(None)
        await show_trash_list(
            callback.message,
            lang,
            0,
            query=await trash_query_of(state),
            replace=True,
        )
        await callback.answer(t(lang, "operation_cancelled"))

    @router.callback_query(F.data == "trash|find")
    async def trash_find_start(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        await state.set_state(TrashSearchStates.query)
        await callback.message.edit_text(
            t(lang, "trash_find_prompt"),
            reply_markup=trash_search_keyboard(lang, offset=0),
        )
        await callback.answer()

    @router.message(TrashSearchStates.query, F.text)
    async def receive_trash_query(
        message: Message, state: FSMContext, lang: str, role: str
    ) -> None:
        if not can_manage_backups(role):
            await reject_message_for_role(message, state, lang, role)
            return
        raw = (message.text or "").strip()
        if not 3 <= len(raw) <= 64:
            await message.answer(
                t(lang, "trash_find_invalid"),
                reply_markup=trash_search_keyboard(lang, offset=0),
            )
            return
        await state.set_state(None)
        await state.update_data(trash_query=raw)
        await show_trash_list(message, lang, 0, query=raw, replace=False)

    @router.callback_query(F.data == "trash|clear")
    async def trash_clear_search(
        callback: CallbackQuery, state: FSMContext, lang: str, role: str
    ) -> None:
        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        await state.update_data(trash_query=None)
        await show_trash_list(callback.message, lang, 0, query=None, replace=True)
        await callback.answer(t(lang, "trash_search_cleared"))

    @router.callback_query(F.data.startswith("trash|restore|"))
    async def restore_trash_card(
        callback: CallbackQuery,
        state: FSMContext,
        lang: str,
        role: str,
        display_name: str,
    ) -> None:
        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        parts = (callback.data or "").split("|")
        try:
            card_id, offset = int(parts[2]), int(parts[3])
        except (IndexError, ValueError):
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        if not await repository.restore_card(card_id):
            await callback.answer(t(lang, "trash_already"), show_alert=True)
            return
        with contextlib.suppress(Exception):
            await repository.add_audit(
                actor_id=callback.from_user.id,
                actor_name=display_name,
                action=AuditAction.CARD_RESTORED,
                details=f"#{card_id}",
            )
        await callback.answer(
            t(lang, "trash_restored", card_id=card_id), show_alert=True
        )
        with contextlib.suppress(TelegramBadRequest):
            await callback.message.delete()
        await show_trash_list(
            callback.message,
            lang,
            offset,
            query=await trash_query_of(state),
            replace=False,
        )

    @router.callback_query(F.data.startswith("trash|purge|"))
    async def purge_trash_card(
        callback: CallbackQuery,
        state: FSMContext,
        lang: str,
        role: str,
        display_name: str,
    ) -> None:
        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        if not is_main_admin(callback.from_user.id):
            await callback.answer(t(lang, "trash_purge_forbidden"), show_alert=True)
            return
        parts = (callback.data or "").split("|")
        try:
            card_id, offset = int(parts[2]), int(parts[3])
        except (IndexError, ValueError):
            await callback.answer(t(lang, "operation_expired"), show_alert=True)
            return
        if not await repository.purge_card(card_id, min_age_days=TRASH_KEEP_DAYS):
            await callback.answer(
                t(lang, "trash_purge_too_early", days=TRASH_KEEP_DAYS), show_alert=True
            )
            return
        with contextlib.suppress(Exception):
            await repository.add_audit(
                actor_id=callback.from_user.id,
                actor_name=display_name,
                action=AuditAction.CARD_PURGED,
                details=f"#{card_id}",
            )
        await callback.answer(t(lang, "trash_purged", card_id=card_id), show_alert=True)
        with contextlib.suppress(TelegramBadRequest):
            await callback.message.delete()
        await show_trash_list(
            callback.message,
            lang,
            offset,
            query=await trash_query_of(state),
            replace=False,
        )

    # -------------------------------------------------------------- journal

    @router.callback_query(F.data == "bkp|journal")
    async def show_journal(callback: CallbackQuery, lang: str, role: str) -> None:
        if not can_manage_backups(role) or callback.message is None:
            await callback.answer(t(lang, "backup_forbidden"), show_alert=True)
            return
        entries = await repository.list_audit(limit=JOURNAL_PAGE_SIZE)
        if not entries:
            lines = t(lang, "journal_empty")
        else:
            rendered: list[str] = []
            for entry in entries:
                icon, key = AUDIT_ICONS.get(entry.action, ("•", "audit_unknown"))
                rendered.append(
                    t(
                        lang,
                        "journal_entry",
                        icon=icon,
                        action=t(lang, key),
                        actor=html.escape(entry.actor_name or str(entry.actor_id)),
                        date=entry.created_at.astimezone(config.timezone).strftime(
                            "%d.%m.%Y %H:%M"
                        ),
                    )
                )
            lines = "\n\n".join(rendered)
        await callback.message.edit_text(
            t(lang, "journal_title", entries=lines),
            reply_markup=journal_keyboard(lang),
        )
        await callback.answer()

    @router.message()
    async def unknown_message(
        message: Message,
        lang: str,
        user_registered: bool,
        role: str,
    ) -> None:
        if not user_registered:
            await message.answer(
                t(lang, "choose_language"), reply_markup=language_keyboard()
            )
            return
        await message.answer(
            t(lang, "unknown"),
            reply_markup=main_menu(lang, role=safe_role(role)),
        )

    return router
