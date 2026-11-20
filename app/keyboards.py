from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.i18n import t
from app.manual import ADMIN, page_count
from app.ocr import VIN_ALPHABET
from app.roles import Role, assignable_roles_for, permissions_for


def main_menu(language: str, *, role: str | Role = Role.DRIVER) -> ReplyKeyboardMarkup:
    try:
        normalized_role = Role(role)
    except ValueError:
        normalized_role = Role.DRIVER
    permissions = permissions_for(normalized_role)
    rows: list[list[KeyboardButton]] = []
    # Two clear blocks: vehicles first, painting as its own wide section, then
    # the service row. Full-width buttons are easier to hit and to read.
    vehicles = [KeyboardButton(text=t(language, "btn_create"))]
    if permissions.can_search:
        vehicles.append(KeyboardButton(text=t(language, "btn_search")))
    rows.append(vehicles)
    painting = [KeyboardButton(text=t(language, "btn_paint"))]
    if permissions.can_view_cards:
        painting.append(KeyboardButton(text=t(language, "btn_cards")))
    rows.append(painting)
    rows.append(
        [
            KeyboardButton(text=t(language, "btn_manual")),
            KeyboardButton(text=t(language, "btn_settings")),
        ]
    )
    if permissions.can_view_statistics:
        rows.append([KeyboardButton(text=t(language, "btn_admin"))])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=t(language, "menu_placeholder"),
    )


def cancel_menu(language: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(language, "btn_cancel"))]],
        resize_keyboard=True,
        is_persistent=True,
    )


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang|ru"),
                InlineKeyboardButton(text="🇩🇪 Deutsch", callback_data="lang|de"),
            ]
        ]
    )


def admin_panel_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_admin_users"),
                    callback_data="adm|users|0",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_manual_admin"),
                    callback_data="manual|open|admin",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_admin_backup"),
                    callback_data="bkp|menu",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_admin_refresh"),
                    callback_data="adm|panel",
                ),
                InlineKeyboardButton(
                    text=t(language, "btn_close"),
                    callback_data="adm|close",
                ),
            ],
        ]
    )


def manual_keyboard(language: str, *, which: str, index: int) -> InlineKeyboardMarkup:
    """Page navigation for the in-bot manuals."""

    rows: list[list[InlineKeyboardButton]] = []
    navigation: list[InlineKeyboardButton] = []
    if index > 0:
        navigation.append(
            InlineKeyboardButton(
                text=t(language, "btn_back"),
                callback_data=f"manual|{which}|{index - 1}",
            )
        )
    if index + 1 < page_count(which):
        navigation.append(
            InlineKeyboardButton(
                text=t(language, "btn_forward"),
                callback_data=f"manual|{which}|{index + 1}",
            )
        )
    if navigation:
        rows.append(navigation)
    # The administrator guide returns to the panel, the worker guide to the menu.
    exit_button = (
        InlineKeyboardButton(
            text=t(language, "btn_admin_back"), callback_data="adm|panel"
        )
        if which == ADMIN
        else InlineKeyboardButton(
            text=t(language, "btn_home"), callback_data="nav|home"
        )
    )
    rows.append(
        [
            exit_button,
            InlineKeyboardButton(
                text=t(language, "btn_close"), callback_data="manual|close"
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_users_keyboard(
    language: str,
    *,
    roles: list[tuple[int, str]],
    offset: int,
    total: int,
    page_size: int,
    actor_role: str | Role,
    renamable_ids: frozenset[int] | set[int] = frozenset(),
    deletable_ids: frozenset[int] | set[int] = frozenset(),
    labels: dict[int, str] | None = None,
) -> InlineKeyboardMarkup:
    """Buttons name the person.

    ``labels`` maps a Telegram id to a short name. A number alone says nothing
    to an administrator who is looking for «Иван», so every button carries the
    name; two people called the same get a two-digit suffix to stay apart.
    """

    named = labels or {}
    rows: list[list[InlineKeyboardButton]] = []
    role_button_keys = {
        Role.ADMIN: "btn_set_admin",
        Role.WORKER: "btn_set_worker",
        Role.DRIVER: "btn_set_driver",
    }
    for user_id, target_role in roles:
        allowed_roles = assignable_roles_for(actor_role, target_role)
        who = named.get(user_id) or t(language, "admin_user_unnamed")
        buttons: list[InlineKeyboardButton] = [
            InlineKeyboardButton(
                text=f"{t(language, role_button_keys[new_role])} · {who}",
                callback_data=(f"adm|role|{user_id}|{new_role.value}|{offset}"),
            )
            for new_role in allowed_roles
        ]
        if user_id in set(renamable_ids):
            # Renaming is cosmetic, so every listed user gets the button.
            buttons.append(
                InlineKeyboardButton(
                    text=f"{t(language, 'btn_rename')} · {who}",
                    callback_data=f"adm|rename|{user_id}|{offset}",
                )
            )
        if user_id in set(deletable_ids):
            # Deleting is not cosmetic, so it always opens a confirmation.
            buttons.append(
                InlineKeyboardButton(
                    text=f"{t(language, 'btn_delete_user')} · {who}",
                    callback_data=f"adm|del|{user_id}|{offset}",
                )
            )
        if not buttons:
            continue
        # Main administrators get three compact role choices; split them so the
        # Telegram keyboard remains readable on narrow phone screens.
        rows.extend([buttons[index : index + 2] for index in range(0, len(buttons), 2)])

    navigation: list[InlineKeyboardButton] = []
    if offset > 0:
        navigation.append(
            InlineKeyboardButton(
                text=t(language, "btn_prev"),
                callback_data=f"adm|users|{max(offset - page_size, 0)}",
            )
        )
    if offset + page_size < total:
        navigation.append(
            InlineKeyboardButton(
                text=t(language, "btn_next"),
                callback_data=f"adm|users|{offset + page_size}",
            )
        )
    if navigation:
        rows.append(navigation)
    rows.append(
        [
            InlineKeyboardButton(
                text=t(language, "btn_admin_back"),
                callback_data="adm|panel",
            ),
            InlineKeyboardButton(
                text=t(language, "btn_close"),
                callback_data="adm|close",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def archive_status_keyboard(language: str) -> InlineKeyboardMarkup:
    """Test button and manual export next to the archive status."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_archive_test"),
                    callback_data="arch|test",
                ),
                InlineKeyboardButton(
                    text=t(language, "btn_archive_digest"),
                    callback_data="arch|digest",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_archive_retry"),
                    callback_data="arch|retry",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_admin_back"),
                    callback_data="bkp|menu",
                ),
                InlineKeyboardButton(
                    text=t(language, "btn_close"),
                    callback_data="adm|close",
                ),
            ],
        ]
    )


def second_reader_keyboard(language: str) -> InlineKeyboardMarkup:
    """Check key and back, under the second-reader status."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_second_reader_test"),
                    callback_data="gem|test",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_admin_back"),
                    callback_data="bkp|menu",
                ),
                InlineKeyboardButton(
                    text=t(language, "btn_close"),
                    callback_data="adm|close",
                ),
            ],
        ]
    )


def admin_delete_confirm_keyboard(
    language: str, *, user_id: int, offset: int
) -> InlineKeyboardMarkup:
    """Yes/no panel shown before a user is removed from the bot."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_yes_delete"),
                    callback_data=f"adm|delgo|{user_id}|{offset}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_no"),
                    callback_data=f"adm|users|{offset}",
                )
            ],
        ]
    )


def backup_menu_keyboard(language: str) -> InlineKeyboardMarkup:
    """Administrator entry point for exports, imports and rollbacks."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_backup_export"),
                    callback_data="bkp|export",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_backup_import"),
                    callback_data="bkp|import",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_backup_rollback"),
                    callback_data="bkp|list|0",
                ),
                InlineKeyboardButton(
                    text=t(language, "btn_backup_trash"),
                    callback_data="trash|menu",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_backup_journal"), callback_data="bkp|journal"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_archive_channel"),
                    callback_data="arch|menu",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_second_reader"),
                    callback_data="gem|menu",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_admin_back"),
                    callback_data="adm|panel",
                ),
                InlineKeyboardButton(
                    text=t(language, "btn_close"),
                    callback_data="adm|close",
                ),
            ],
        ]
    )


def backup_import_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_cancel"),
                    callback_data="bkp|cancel",
                )
            ]
        ]
    )


def backup_apply_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_backup_apply"),
                    callback_data="bkp|apply",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_no"),
                    callback_data="bkp|cancel",
                )
            ],
        ]
    )


def snapshot_keyboard(
    language: str,
    *,
    snapshots: list,
    offset: int,
    page_size: int,
) -> InlineKeyboardMarkup:
    """One button per snapshot plus pagination."""

    rows: list[list[InlineKeyboardButton]] = []
    page = snapshots[offset : offset + page_size]
    for position, snapshot in enumerate(page):
        rows.append(
            [
                InlineKeyboardButton(
                    text=snapshot.label(language),
                    callback_data=f"bkp|pick|{snapshot.path.name}",
                )
            ]
        )
    navigation: list[InlineKeyboardButton] = []
    if offset > 0:
        navigation.append(
            InlineKeyboardButton(
                text=t(language, "btn_prev"),
                callback_data=f"bkp|list|{max(offset - page_size, 0)}",
            )
        )
    if offset + page_size < len(snapshots):
        navigation.append(
            InlineKeyboardButton(
                text=t(language, "btn_next"),
                callback_data=f"bkp|list|{offset + page_size}",
            )
        )
    if navigation:
        rows.append(navigation)
    rows.append(
        [
            InlineKeyboardButton(
                text=t(language, "btn_admin_back"),
                callback_data="bkp|menu",
            ),
            InlineKeyboardButton(
                text=t(language, "btn_close"),
                callback_data="adm|close",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def snapshot_confirm_keyboard(language: str, key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_yes_rollback"),
                    callback_data=f"bkp|restore|{key}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_no"),
                    callback_data="bkp|list|0",
                )
            ],
        ]
    )


def trash_keyboard(
    language: str,
    *,
    card_id: int,
    offset: int,
    can_purge: bool,
    list_offset: int = 0,
) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=t(language, "btn_restore"),
            callback_data=f"trash|restore|{card_id}|{offset}",
        )
    ]
    if can_purge:
        buttons.append(
            InlineKeyboardButton(
                text=t(language, "btn_purge"),
                callback_data=f"trash|purge|{card_id}|{offset}",
            )
        )
    rows = [buttons]
    rows.append(
        [
            InlineKeyboardButton(
                text=t(language, "btn_trash_back_list"),
                callback_data=f"trash|list|{max(0, list_offset)}",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=t(language, "btn_admin_back"),
                callback_data="bkp|menu",
            ),
            InlineKeyboardButton(
                text=t(language, "btn_close"),
                callback_data="adm|close",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def trash_list_keyboard(
    language: str,
    *,
    offset: int,
    total: int,
    page_size: int,
    page: list[tuple[int, str]] | None = None,
    query: str | None = None,
) -> InlineKeyboardMarkup:
    """Buttons for a page of deleted cards: one row per card, then paging."""

    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=label,
                callback_data=f"trash|open|{card_id}|{offset}",
            )
        ]
        for card_id, label in page or []
    ]
    navigation: list[InlineKeyboardButton] = []
    if offset > 0:
        navigation.append(
            InlineKeyboardButton(
                text=t(language, "btn_prev"),
                callback_data=f"trash|list|{max(offset - page_size, 0)}",
            )
        )
    navigation.append(
        InlineKeyboardButton(
            text=t(language, "btn_trash_clear" if query else "btn_trash_find"),
            callback_data="trash|clear" if query else "trash|find",
        )
    )
    if offset + page_size < total:
        navigation.append(
            InlineKeyboardButton(
                text=t(language, "btn_next"),
                callback_data=f"trash|list|{offset + page_size}",
            )
        )
    rows.append(navigation)
    rows.append(
        [
            InlineKeyboardButton(
                text=t(language, "btn_admin_back"),
                callback_data="bkp|menu",
            ),
            InlineKeyboardButton(
                text=t(language, "btn_close"),
                callback_data="adm|close",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def trash_search_keyboard(language: str, *, offset: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_cancel"),
                    callback_data="trash|cancel",
                )
            ]
        ]
    )


def journal_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_admin_back"),
                    callback_data="bkp|menu",
                ),
                InlineKeyboardButton(
                    text=t(language, "btn_close"),
                    callback_data="adm|close",
                ),
            ]
        ]
    )


def vin_confirmation_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_confirm"), callback_data="vin|ok"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_fix_char"), callback_data="vin|fix"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_edit"), callback_data="vin|edit"
                ),
                InlineKeyboardButton(
                    text=t(language, "btn_retake"), callback_data="vin|retake"
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_cancel"), callback_data="flow|cancel"
                )
            ],
        ]
    )


def card_keyboard(
    language: str,
    *,
    mode: str,
    query: str,
    offset: int,
    total: int,
    card_id: int,
    can_delete: bool,
    has_invoice: bool = False,
    showing_invoice: bool = False,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_invoice:
        target = "v" if showing_invoice else "i"
        label = "btn_vehicle_photo" if showing_invoice else "btn_invoice"
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(language, label),
                    callback_data=(f"media|{target}|{card_id}|{mode}|{query}|{offset}"),
                )
            ]
        )
    if showing_invoice:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(language, "btn_close"), callback_data="card|close"
                )
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    navigation: list[InlineKeyboardButton] = []
    if offset > 0:
        navigation.append(
            InlineKeyboardButton(
                text=t(language, "btn_prev"),
                callback_data=f"page|{mode}|{query}|{offset - 1}",
            )
        )
    if offset + 1 < total:
        navigation.append(
            InlineKeyboardButton(
                text=t(language, "btn_next"),
                callback_data=f"page|{mode}|{query}|{offset + 1}",
            )
        )
    if navigation:
        rows.append(navigation)
    if can_delete:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(language, "btn_delete"),
                    callback_data=f"delask|{card_id}|{mode}|{query}|{offset}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t(language, "btn_home"), callback_data="nav|home"
            ),
            InlineKeyboardButton(
                text=t(language, "btn_close"), callback_data="card|close"
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def paint_menu_keyboard(
    language: str, *, role: str | Role = Role.DRIVER
) -> InlineKeyboardMarkup:
    """Section menu for the painting workflow.

    Every role may hand a vehicle over for painting, browse the two painting
    catalogues, search them and confirm a pickup; drivers included.
    """

    try:
        normalized_role = Role(role)
    except ValueError:
        normalized_role = Role.DRIVER
    permissions = permissions_for(normalized_role)
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=t(language, "btn_paint_new"), callback_data="paint|new"
            )
        ]
    ]
    if permissions.can_view_paint:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(language, "btn_paint_list"),
                    callback_data="paint|list|in|0",
                ),
                InlineKeyboardButton(
                    text=t(language, "btn_paint_done"),
                    callback_data="paint|list|done|0",
                ),
            ]
        )
        if permissions.can_search_paint:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=t(language, "btn_paint_search"),
                        callback_data="paint|search",
                    )
                ]
            )
    rows.append(
        [
            InlineKeyboardButton(
                text=t(language, "btn_home"), callback_data="nav|home"
            ),
            InlineKeyboardButton(
                text=t(language, "btn_close"), callback_data="paint|close"
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def paint_card_keyboard(
    language: str,
    *,
    scope: str,
    query: str,
    offset: int,
    total: int,
    card_id: int,
    can_complete: bool,
    showing_vin: bool = False,
) -> InlineKeyboardMarkup:
    suffix = f"{card_id}|{scope}|{query}|{offset}"
    rows: list[list[InlineKeyboardButton]] = []
    if showing_vin:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(language, "btn_vehicle_photo"),
                    callback_data=f"pmedia|v|{suffix}",
                ),
                InlineKeyboardButton(
                    text=t(language, "btn_close"), callback_data="paint|close"
                ),
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    rows.append(
        [
            InlineKeyboardButton(
                text=t(language, "btn_paint_vin_photo"),
                callback_data=f"pmedia|i|{suffix}",
            )
        ]
    )
    navigation: list[InlineKeyboardButton] = []
    if offset > 0:
        navigation.append(
            InlineKeyboardButton(
                text=t(language, "btn_prev"),
                callback_data=f"ppage|{scope}|{query}|{offset - 1}",
            )
        )
    if offset + 1 < total:
        navigation.append(
            InlineKeyboardButton(
                text=t(language, "btn_next"),
                callback_data=f"ppage|{scope}|{query}|{offset + 1}",
            )
        )
    if navigation:
        rows.append(navigation)
    if can_complete:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(language, "btn_take_from_paint"),
                    callback_data=f"paint|takeask|{suffix}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t(language, "btn_paint_menu"), callback_data="paint|menu"
            ),
            InlineKeyboardButton(
                text=t(language, "btn_close"), callback_data="paint|close"
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def paint_take_keyboard(
    language: str,
    *,
    card_id: int,
    scope: str,
    query: str,
    offset: int,
) -> InlineKeyboardMarkup:
    suffix = f"{card_id}|{scope}|{query}|{offset}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_yes_take"),
                    callback_data=f"paint|takeyes|{suffix}",
                ),
                InlineKeyboardButton(
                    text=t(language, "btn_no"), callback_data=f"paint|takeno|{suffix}"
                ),
            ]
        ]
    )


def paint_vin_confirmation_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_confirm"), callback_data="pvin|ok"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_fix_char"), callback_data="pvin|fix"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_edit"), callback_data="pvin|edit"
                ),
                InlineKeyboardButton(
                    text=t(language, "btn_retake"), callback_data="pvin|retake"
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_cancel"), callback_data="pflow|cancel"
                )
            ],
        ]
    )


def delete_confirmation_keyboard(
    language: str,
    *,
    card_id: int,
    mode: str,
    query: str,
    offset: int,
) -> InlineKeyboardMarkup:
    suffix = f"{card_id}|{mode}|{query}|{offset}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_yes_delete"),
                    callback_data=f"delyes|{suffix}",
                ),
                InlineKeyboardButton(
                    text=t(language, "btn_no"), callback_data=f"delno|{suffix}"
                ),
            ]
        ]
    )


def vin_fix_keyboard(
    language: str, vin: str, *, prefix: str, unsure: dict[int, list[str]]
) -> InlineKeyboardMarkup:
    """Seventeen buttons, one per character: pick the one that is wrong.

    A position the camera read two different ways is marked with «?» so he
    knows where to look first — the plate says one thing and the camera could
    not make its mind up.
    """

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for index, char in enumerate(vin):
        mark = "?" if index in unsure else ""
        row.append(
            InlineKeyboardButton(
                text=f"{index + 1}{mark} {char}",
                callback_data=f"{prefix}|fixpos|{index}",
            )
        )
        if len(row) == 6:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text=t(language, "btn_back"), callback_data=f"{prefix}|fixback"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def vin_replace_keyboard(
    language: str,
    *,
    prefix: str,
    index: int,
    current: str,
    suggestions: list[str],
) -> InlineKeyboardMarkup:
    """Every character a VIN may use, one tap to put in place of this one.

    Suggested characters — the ones other readings of the same picture saw
    here — come first, so the right answer is usually the first row.
    """

    buttons: list[InlineKeyboardButton] = []
    for char in suggestions:
        buttons.append(
            InlineKeyboardButton(
                text=f"• {char}",
                callback_data=f"{prefix}|fixset|{index}|{char}",
            )
        )
    for char in VIN_ALPHABET:
        if char == current or char in suggestions:
            continue
        buttons.append(
            InlineKeyboardButton(
                text=char, callback_data=f"{prefix}|fixset|{index}|{char}"
            )
        )
    rows = [buttons[offset : offset + 6] for offset in range(0, len(buttons), 6)]
    rows.append(
        [
            InlineKeyboardButton(
                text=t(language, "btn_back"), callback_data=f"{prefix}|fix"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def vin_source_keyboard(language: str) -> InlineKeyboardMarkup:
    """Where the VIN photograph may come from at the third step.

    The invoice is already on the table by then, and the engine finds the
    code by its shape wherever it sits on the page — so cutting a piece out
    of the invoice is a favour to nobody. One tap takes the invoice as it is.
    """

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_use_invoice"),
                    callback_data="vin|useinvoice",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_cancel"), callback_data="flow|cancel"
                )
            ],
        ]
    )
