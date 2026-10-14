"""Money is stored as integer cents (RMB fen) and only formatted at the edges."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from edba.errors import DomainError


def to_cents(value: str | float | int | Decimal) -> int:
    try:
        d = Decimal(str(value).strip() or "0")
    except InvalidOperation as e:
        raise DomainError(f"Not a valid amount: {value!r}") from e
    if d < 0:
        raise DomainError("Amounts cannot be negative.")
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fmt(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}¥{cents // 100:,}.{cents % 100:02d}"


def plain(cents: int) -> str:
    """Amount without currency symbol, for form inputs and the bank API."""
    return f"{cents / 100:.2f}"
