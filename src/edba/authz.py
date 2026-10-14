"""Who may do what, in one place.

Access levels nest (3 ⊃ 2 ⊃ 1). Inside their own organization a data user acts
at their own level; in any other organization's workspace they are clamped to
level 1, which only exposes public data (course information and theses).
"""

from __future__ import annotations

from edba.errors import Forbidden
from edba.models import SERVICES, Organization, Role, ServiceKind, User


def effective_level(user: User, org: Organization) -> int:
    """0 = no access to this workspace's services."""
    if user.role is not Role.MEMBER or not user.is_active:
        return 0
    return user.access_level if user.org_id == org.id else 1


def is_home(user: User, org: Organization) -> bool:
    return user.org_id == org.id


def may_use(user: User, org: Organization, kind: ServiceKind) -> bool:
    return effective_level(user, org) >= SERVICES[kind].min_level


def require_use(user: User, org: Organization, kind: ServiceKind) -> None:
    if not may_use(user, org, kind):
        raise Forbidden(f"Your access level does not include {SERVICES[kind].title}.")


def require_provider(user: User, org: Organization) -> None:
    """Level-3 data providers configure courses and connectors of their own organization."""
    if not (is_home(user, org) and effective_level(user, org) >= 3):
        raise Forbidden("Only level-3 data providers of this organization can do that.")


def require_role(user: User, *roles: Role) -> None:
    if user.role not in roles:
        raise Forbidden("You do not have permission to do that.")


def require_convener(user: User) -> Organization:
    if user.role is not Role.CONVENER or user.organization is None:
        raise Forbidden("Only the organization's O-Convener can do that.")
    return user.organization
