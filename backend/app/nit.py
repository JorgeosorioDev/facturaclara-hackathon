"""NIT check digit (DIAN)."""

from __future__ import annotations

_WEIGHTS = (3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71)


def _dv_for_base(base: str) -> int:
    total = sum(int(d) * w for d, w in zip(reversed(base), _WEIGHTS))
    r = total % 11
    return 11 - r if r > 1 else r


def verificar_dv_nit(nit: str, dv: int | str | None = None) -> bool:
    """True si el DV cuadra. Acepta "base-DV", "baseDV" o (base, dv)."""
    if dv is None:
        digits = "".join(c for c in str(nit) if c.isdigit())
        if len(digits) < 2:
            return False
        base, given = digits[:-1], int(digits[-1:])
    else:
        base = "".join(c for c in str(nit) if c.isdigit())
        given = int(str(dv).strip())
    if not base or not base.isdigit():
        return False
    if not (6 <= len(base) <= 15):
        return False
    return _dv_for_base(base) == given
