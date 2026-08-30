from decimal import Decimal, ROUND_HALF_UP

TWOPLACES = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value):
    if value is None:
        return ZERO
    return Decimal(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
