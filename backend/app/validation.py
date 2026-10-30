"""Validación Día 3 — pura, sin red ni DB."""
from __future__ import annotations

from dataclasses import dataclass

from app.nit import verificar_dv_nit


@dataclass
class Alerta:
    campo: str
    regla: str
    mensaje: str
    severidad: str = "advertencia"


def _es_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _nit_valido(nit_raw) -> bool:
    if nit_raw is None:
        return True
    s = str(nit_raw).strip()
    if not s:
        return True
    limpio = s.replace(".", "").replace(" ", "").replace("-", "")
    if not limpio.isdigit() or len(limpio) < 2:
        return False
    try:
        try:
            return bool(verificar_dv_nit(limpio))
        except TypeError:
            base, dv = limpio[:-1], limpio[-1]
            return bool(verificar_dv_nit(base, dv))
    except Exception:
        return False


def validar_factura(factura: dict) -> list[Alerta]:
    """Valida una factura dict y devuelve la lista de alertas (no bloquean)."""
    alertas: list[Alerta] = []
    f = factura or {}

    for campo in ("proveedor", "fecha", "total"):
        v = f.get(campo)
        if v is None or (isinstance(v, str) and not v.strip()):
            alertas.append(
                Alerta(
                    campo=campo,
                    regla="obligatorio",
                    mensaje=f"Falta {campo}",
                )
            )

    nit = f.get("nit")
    if nit is None or str(nit).strip() == "":
        alertas.append(
            Alerta(
                campo="nit",
                regla="nit_ausente",
                mensaje="NIT no leído",
                severidad="aviso",
            )
        )
    elif not _nit_valido(nit):
        alertas.append(
            Alerta(
                campo="nit",
                regla="nit",
                mensaje="NIT no reconocido, revísalo",
            )
        )

    items = f.get("items")
    if not isinstance(items, list):
        items = []
    for i, it in enumerate(items, start=1):
        if not isinstance(it, dict):
            continue
        cant = it.get("cantidad")
        precio = it.get("precio_unitario", it.get("precio"))
        tot = it.get("total")
        if _es_num(cant) and _es_num(precio) and _es_num(tot):
            if abs(cant * precio - tot) > 100:
                alertas.append(
                    Alerta(
                        campo=f"items[{i}].total",
                        regla="item",
                        mensaje=f"El ítem {i} no cuadra: cantidad × precio ≠ total",
                    )
                )

    total = f.get("total")
    iva = f.get("iva")
    if _es_num(total):
        suma_items = sum(
            it.get("total") for it in items
            if isinstance(it, dict) and _es_num(it.get("total"))
        )
        iva_v = iva if _es_num(iva) else 0
        if abs(suma_items + iva_v - total) > 100:
            alertas.append(
                Alerta(
                    campo="total",
                    regla="total",
                    mensaje="Los valores no cuadran",
                )
            )

    return alertas
