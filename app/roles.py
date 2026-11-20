from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    """Roles stored in SQLite, plus the configured protected main administrator."""

    DRIVER = "driver"
    WORKER = "worker"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


ASSIGNABLE_ROLE_ORDER = (Role.ADMIN, Role.WORKER, Role.DRIVER)
STORED_ROLES = frozenset(ASSIGNABLE_ROLE_ORDER)


@dataclass(frozen=True, slots=True)
class RolePermissions:
    can_create: bool
    can_search: bool
    can_view_cards: bool
    can_delete_cards: bool
    can_view_statistics: bool
    # Painting section: handing a vehicle over for painting uses can_create.
    # Every role, including a driver, may browse the painting catalogues, search
    # them and confirm a pickup, so the whole painting workflow stays available
    # to whoever physically delivers and collects the cars.
    can_view_paint: bool
    can_complete_paint: bool
    can_search_paint: bool
    # Administrators and the main administrator may rename users so the list of
    # employees stays readable even when Telegram profile names are unhelpful.
    can_manage_users: bool


_PERMISSIONS = {
    Role.DRIVER: RolePermissions(
        can_create=True,
        can_search=False,
        can_view_cards=False,
        can_delete_cards=False,
        can_view_statistics=False,
        can_view_paint=True,
        can_complete_paint=True,
        can_search_paint=True,
        can_manage_users=False,
    ),
    Role.WORKER: RolePermissions(
        can_create=True,
        can_search=True,
        can_view_cards=True,
        can_delete_cards=False,
        can_view_statistics=False,
        can_view_paint=True,
        can_complete_paint=True,
        can_search_paint=True,
        can_manage_users=False,
    ),
    Role.ADMIN: RolePermissions(
        can_create=True,
        can_search=True,
        can_view_cards=True,
        can_delete_cards=True,
        can_view_statistics=True,
        can_view_paint=True,
        can_complete_paint=True,
        can_search_paint=True,
        can_manage_users=True,
    ),
    Role.SUPERADMIN: RolePermissions(
        can_create=True,
        can_search=True,
        can_view_cards=True,
        can_delete_cards=True,
        can_view_statistics=True,
        can_view_paint=True,
        can_complete_paint=True,
        can_search_paint=True,
        can_manage_users=True,
    ),
}


def normalize_stored_role(value: str | Role | None) -> Role:
    """Return a safe stored role; unknown database values get least privilege."""

    try:
        role = Role(value or Role.DRIVER)
    except ValueError:
        return Role.DRIVER
    return role if role in STORED_ROLES else Role.DRIVER


def effective_role(stored_role: str | Role | None, *, is_superadmin: bool) -> Role:
    if is_superadmin:
        return Role.SUPERADMIN
    return normalize_stored_role(stored_role)


def permissions_for(role: str | Role) -> RolePermissions:
    try:
        normalized = Role(role)
    except ValueError:
        normalized = Role.DRIVER
    return _PERMISSIONS[normalized]


def assignable_roles_for(
    actor_role: str | Role, target_role: str | Role
) -> tuple[Role, ...]:
    """Return roles the actor may assign to this target.

    The protected main administrator can assign all persisted roles. A regular
    administrator can only switch workers and drivers, and therefore cannot
    promote anyone to administrator or alter another administrator.
    """

    try:
        actor = Role(actor_role)
        target = Role(target_role)
    except ValueError:
        return ()

    if target is Role.SUPERADMIN:
        return ()
    if actor is Role.SUPERADMIN:
        return tuple(role for role in ASSIGNABLE_ROLE_ORDER if role is not target)
    if actor is Role.ADMIN and target in {Role.DRIVER, Role.WORKER}:
        other = Role.WORKER if target is Role.DRIVER else Role.DRIVER
        return (other,)
    return ()


def can_assign_role(
    actor_role: str | Role,
    target_role: str | Role,
    requested_role: str | Role,
) -> bool:
    try:
        requested = Role(requested_role)
    except ValueError:
        return False
    return requested in assignable_roles_for(actor_role, target_role)


def can_delete_user(
    actor_role: str | Role,
    target_id: int,
    protected_ids: frozenset[int] | set[int] = frozenset(),
    *,
    actor_id: int = 0,
    target_role: str | Role = Role.DRIVER,
) -> bool:
    """Whether the actor may remove this user from the bot entirely.

    Removing an employee never destroys the history: every card keeps its own
    copy of the owner name, so the cards simply stay in the database. Nobody may
    remove a protected main administrator, and nobody may remove themselves,
    because that would lock the administrator out of the panel they are using.
    """

    try:
        actor = Role(actor_role)
    except ValueError:
        return False
    if not permissions_for(actor).can_manage_users:
        return False
    target = normalize_stored_role(target_role)
    if target is Role.SUPERADMIN:
        return False
    if actor_id and target_id == actor_id:
        return False
    protected = set(protected_ids)
    if actor is Role.SUPERADMIN:
        return target_id not in protected
    # A regular administrator only clears drivers and workers.
    return target_id not in protected and target in {Role.DRIVER, Role.WORKER}


def can_rename_user(
    actor_role: str | Role,
    target_id: int,
    protected_ids: frozenset[int] | set[int] = frozenset(),
) -> bool:
    """Whether the actor may rename this user in the administrator list.

    Administrators and the main administrator may rename everybody except a
    protected main administrator, which only another main administrator renames.
    """

    try:
        actor = Role(actor_role)
    except ValueError:
        return False
    if not permissions_for(actor).can_manage_users:
        return False
    if actor is Role.SUPERADMIN:
        return True
    return target_id not in set(protected_ids)
