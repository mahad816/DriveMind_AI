"""TypeSafe rounding validation, versioned independently from semantic criteria.

JSON numbers lose trailing zero precision. Use a common decimal grid at least
as fine as the empirically observed two-decimal representation, and refine it
when any value reports more significant decimal places. Fifteen significant
 digits discard binary-float serialization noise, not provider-level rounding.
This is a representation assumption, not an official precision guarantee.
"""

from decimal import Decimal

VALIDATION_VERSION = "typesafe-probabilities-2.0"


def intervals(distribution: dict[str, float]) -> dict[str, tuple[Decimal, Decimal]]:
    values = {key: Decimal(format(value, ".15g")) for key, value in distribution.items()}
    exponents = [value.as_tuple().exponent for value in values.values()]
    assert all(isinstance(exponent, int) for exponent in exponents)
    precision = max(2, *(max(0, -int(exponent)) for exponent in exponents))
    half_unit = Decimal(1).scaleb(-precision) / 2
    return {
        key: (max(Decimal(0), value - half_unit), min(Decimal(1), value + half_unit))
        for key, value in values.items()
    }


def validate_distribution(distribution: dict[str, float], selected: str) -> None:
    bounds = intervals(distribution)
    lower = sum(pair[0] for pair in bounds.values())
    upper = sum(pair[1] for pair in bounds.values())
    if not lower <= Decimal(1) <= upper:
        raise ValueError("Distribution is not normalized")
    # Ties are valid; a lower reported choice needs overlapping rounding intervals.
    if bounds[selected][1] < max(pair[0] for pair in bounds.values()):
        raise ValueError("Invalid selected label")
