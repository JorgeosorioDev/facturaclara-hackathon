"""Consultas Día 4 — SQL parametrizado, montos enteros, sin Text-to-SQL."""
from __future__ import annotations

import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Factura

_MES_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def _a_entero(v) -> int:
    return int(v) if v is not None else 0


def _anio_mes(mes: str | None) -> tuple[int, int] | None:
    """Valida YYYY-MM y devuelve (anio, mes). None si no viene; error si mal formato."""
    if mes is None:
        return None
    texto = str(mes).strip()
    if not texto:
        return None
    match = _MES_RE.match(texto)
    if not match:
        raise ValueError(f"Mes inválido (esperado YYYY-MM): {mes!r}")
    return int(match.group(1)), int(match.group(2))


def total_por_mes(session: Session) -> list[dict]:
    """Suma de totales agrupada por mes YYYY-MM. Portable SQLite/PostgreSQL."""
    filas = (
        session.query(
            func.extract("year", Factura.fecha).label("anio"),
            func.extract("month", Factura.fecha).label("mes"),
            func.sum(func.coalesce(Factura.total, 0)).label("total"),
        )
        .filter(Factura.fecha.is_not(None))
        .group_by(
            func.extract("year", Factura.fecha),
            func.extract("month", Factura.fecha),
        )
        .order_by(
            func.extract("year", Factura.fecha),
            func.extract("month", Factura.fecha),
        )
        .all()
    )
    return [
        {"mes": f"{int(r.anio):04d}-{int(r.mes):02d}", "total": _a_entero(r.total)}
        for r in filas
    ]


def total_por_categoria(session: Session, mes: str | None = None) -> list[dict]:
    """Suma por categoría; con mes YYYY-MM agrega AND de mes (parámetro ligado)."""
    consulta = session.query(
        func.coalesce(Factura.categoria, "otros").label("categoria"),
        func.sum(func.coalesce(Factura.total, 0)).label("total"),
    )
    ym = _anio_mes(mes)
    if ym is not None:
        anio, num = ym
        consulta = consulta.filter(
            func.extract("year", Factura.fecha) == anio,
            func.extract("month", Factura.fecha) == num,
        )
    filas = (
        consulta.group_by(func.coalesce(Factura.categoria, "otros"))
        .order_by(func.coalesce(Factura.categoria, "otros"))
        .all()
    )
    return [{"categoria": r.categoria, "total": _a_entero(r.total)} for r in filas]


def total_por_proveedor(
    session: Session, proveedor: str, mes: str | None = None
) -> int:
    """Suma para un proveedor exacto; con mes YYYY-MM agrega AND de mes. Todo ligado."""
    ym = _anio_mes(mes)
    consulta = session.query(func.sum(func.coalesce(Factura.total, 0))).filter(
        Factura.proveedor == proveedor
    )
    if ym is not None:
        anio, num = ym
        consulta = consulta.filter(
            func.extract("year", Factura.fecha) == anio,
            func.extract("month", Factura.fecha) == num,
        )
    return _a_entero(consulta.scalar())


def ultimas(session: Session, n: int = 5) -> list[Factura]:
    """Últimas n facturas por id descendente. n saneado a entero >= 1."""
    try:
        limite = int(n)
    except (TypeError, ValueError):
        limite = 5
    if limite < 1:
        limite = 1
    if limite > 100:
        limite = 100
    return (
        session.query(Factura).order_by(Factura.id.desc()).limit(limite).all()
    )
