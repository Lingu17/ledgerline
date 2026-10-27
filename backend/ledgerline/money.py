"""Integer minor-unit money helpers. Floats never touch an amount."""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, ROUND_UP, Decimal, InvalidOperation

# Supported scenario currencies and their minor-unit exponent.
CURRENCY_EXPONENT: dict[str, int] = {"USD": 2, "EUR": 2, "GBP": 2}


class MoneyError(ValueError):
    pass


def validate_currency(ccy: str) -> str:
    if not isinstance(ccy, str) or ccy.upper() != ccy or ccy not in CURRENCY_EXPONENT:
        raise MoneyError(f"unsupported currency: {ccy!r}")
    return ccy


def validate_minor(amount: int, *, allow_zero: bool = False) -> int:
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise MoneyError("amount must be an integer number of minor units")
    if amount < 0 or (amount == 0 and not allow_zero):
        raise MoneyError("amount must be positive")
    return amount


def to_major(amount_minor: int, ccy: str) -> Decimal:
    """Minor units -> Decimal major units (e.g. 497000 USD -> Decimal('4970.00'))."""
    exp = CURRENCY_EXPONENT[validate_currency(ccy)]
    return (Decimal(amount_minor) / (Decimal(10) ** exp)).quantize(Decimal(1).scaleb(-exp))


def to_minor(amount_major: str | int | float | Decimal, ccy: str) -> int:
    """Major units (as returned by APIs) -> exact minor units.

    Floats are converted through repr() so 4970.1 becomes Decimal('4970.1'),
    and anything with more precision than the currency allows is rejected
    rather than silently rounded.
    """
    exp = CURRENCY_EXPONENT[validate_currency(ccy)]
    if isinstance(amount_major, bool) or not isinstance(amount_major, (str, int, float, Decimal)):
        raise MoneyError(f"invalid amount {amount_major!r}")
    text = repr(amount_major) if isinstance(amount_major, float) else str(amount_major).strip()
    if isinstance(amount_major, str) and not re.fullmatch(r"\d+(\.\d+)?", text):
        raise MoneyError(f"amount must be a plain non-negative decimal like 1250.00, got {amount_major!r}")
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise MoneyError(f"invalid amount {amount_major!r}") from exc
    if not value.is_finite():
        raise MoneyError("amount must be finite")
    if value < 0:
        raise MoneyError("amount must not be negative")
    if value > Decimal("1000000000"):
        raise MoneyError("amount exceeds the supported maximum")
    scaled = value * (Decimal(10) ** exp)
    if scaled != scaled.to_integral_value():
        raise MoneyError(f"{amount_major!r} has more precision than {ccy} allows")
    return int(scaled)


def fmt(amount_minor: int, ccy: str) -> str:
    return f"{ccy} {to_major(amount_minor, ccy):,}"


def convert_ceil(amount_minor: int, from_ccy: str, to_ccy: str, rate_to_per_from: Decimal) -> int:
    """How much `from_ccy` buys at least `amount_minor` of `to_ccy` (rounded up)."""
    from_exp = CURRENCY_EXPONENT[from_ccy]
    to_exp = CURRENCY_EXPONENT[to_ccy]
    target_major = Decimal(amount_minor) / (Decimal(10) ** to_exp)
    needed = (target_major / rate_to_per_from).quantize(Decimal(1).scaleb(-from_exp), rounding=ROUND_UP)
    return int(needed * (Decimal(10) ** from_exp))


def convert_round(amount_minor: int, from_ccy: str, to_ccy: str, rate_to_per_from: Decimal) -> int:
    from_exp = CURRENCY_EXPONENT[from_ccy]
    to_exp = CURRENCY_EXPONENT[to_ccy]
    major = Decimal(amount_minor) / (Decimal(10) ** from_exp)
    out = (major * rate_to_per_from).quantize(Decimal(1).scaleb(-to_exp), rounding=ROUND_HALF_UP)
    return int(out * (Decimal(10) ** to_exp))
