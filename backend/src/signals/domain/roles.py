"""Normalize free-text officer titles and relationship flags into roles."""

import re
from collections.abc import Iterable

from signals.domain.types import ROLE_PRIORITY, Role

# "Vice President" / "Vice Chairman" are not President / Chair.
_VICE = re.compile(r"vice[\s-]*(president|chair\w*)", re.IGNORECASE)

_OFFICER_RULES: dict[Role, re.Pattern[str]] = {
    Role.CEO: re.compile(r"\b(ceo|chief executive|principal executive)\b", re.IGNORECASE),
    Role.CFO: re.compile(r"\b(cfo|chief financial|principal financial)\b", re.IGNORECASE),
    Role.COO: re.compile(r"\b(coo|chief operating)\b", re.IGNORECASE),
    Role.PRESIDENT: re.compile(r"\bpresident\b", re.IGNORECASE),
    Role.CHAIR: re.compile(r"\bchair(man|woman|person)?\b", re.IGNORECASE),
    Role.GENERAL_COUNSEL: re.compile(r"\b(general counsel|chief legal)\b", re.IGNORECASE),
}


def normalize_roles(
    officer_title: str | None,
    *,
    is_director: bool,
    is_officer: bool,
    is_ten_pct_owner: bool,
    is_other: bool,
) -> list[Role]:
    title = _VICE.sub(" ", officer_title or "")
    officer_roles = [
        role
        for role in ROLE_PRIORITY
        if role in _OFFICER_RULES and _OFFICER_RULES[role].search(title)
    ]
    roles = list(officer_roles)
    if is_officer and not officer_roles:
        roles.append(Role.OTHER_OFFICER)
    if is_director:
        roles.append(Role.DIRECTOR)
    if is_ten_pct_owner:
        roles.append(Role.TEN_PCT_OWNER)
    if is_other:
        roles.append(Role.OTHER)
    return roles


def top_role(roles: Iterable[Role]) -> Role | None:
    present = set(roles)
    return next((role for role in ROLE_PRIORITY if role in present), None)
