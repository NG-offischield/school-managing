"""Money on the desktop: the API sends amounts as STRINGS ("60000.00"); they
are read as Decimal and shown formatted. A float never carries an amount."""

from decimal import Decimal, InvalidOperation

ZERO = Decimal("0")


def to_decimal(value):
    """'60000.00' -> Decimal('60000.00'); None / '' / garbage -> None."""
    if value is None or value == "":
        return None
    if isinstance(value, float):  # never: an amount must not have been a float
        raise TypeError("Amounts are never floats.")
    try:
        return Decimal(str(value).strip().replace(" ", "").replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return None


def format_money(amount, currency=""):
    """'1250000.00', 'XAF' -> '1 250 000 XAF' (narrow no-break spaces)."""
    value = amount if isinstance(amount, Decimal) else to_decimal(amount)
    if value is None:
        return f"{amount or '—'} {currency}".strip()
    text = f"{value:,.0f}" if value == value.to_integral() else f"{value:,.2f}"
    text = text.replace(",", " ").replace(".", ",")  # narrow no-break space
    return f"{text} {currency}".strip()


def parse_amount(text):
    """What the user typed ('15 000', '15000,50') -> Decimal, or None when it
    is not a number. Whether the amount is acceptable is the server's call."""
    value = to_decimal(text)
    if value is None or not value.is_finite():
        return None
    return value


def amount_text(value):
    """Decimal -> the string sent to the API ('15000.50')."""
    return format(value, "f")
