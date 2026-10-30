"""Tests Día 3 — validación pura, sin red ni DB."""
from app.validation import validar_factura


def _base(**kw):
    f = {
        "proveedor": "Papelería Central",
        "nit": "900055719-8",
        "fecha": "2026-10-01",
        "items": [
            {"descripcion": "a", "cantidad": 1, "precio_unitario": 324578, "total": 324578},
            {"descripcion": "b", "cantidad": 1, "precio_unitario": 89002, "total": 89002},
        ],
        "subtotal": 413580,
        "iva": None,
        "total": 413580,
    }
    f.update(kw)
    return f


def _mensajes(alertas):
    return [a.mensaje for a in alertas]


def test_nit_valido_con_guion():
    assert "NIT no reconocido, revísalo" not in _mensajes(validar_factura(_base()))


def test_nit_valido_sin_guion():
    assert "NIT no reconocido, revísalo" not in _mensajes(
        validar_factura(_base(nit="9000557198"))
    )


def test_nit_dv_incorrecto():
    assert "NIT no reconocido, revísalo" in _mensajes(
        validar_factura(_base(nit="900055719-7"))
    )


def test_items_cuadran_sin_alertas():
    assert validar_factura(_base()) == []


def test_item_total_alterado_alertas_b_y_d():
    items = [
        {"descripcion": "a", "cantidad": 1, "precio_unitario": 324578, "total": 324578},
        {"descripcion": "b", "cantidad": 1, "precio_unitario": 89002, "total": 413580},
    ]
    msgs = _mensajes(validar_factura(_base(items=items)))
    assert "Los valores no cuadran" in msgs
    assert "El ítem 2 no cuadra: cantidad × precio ≠ total" in msgs


def test_faltan_obligatorios():
    msgs = _mensajes(validar_factura({"items": [], "iva": None}))
    assert "Falta proveedor" in msgs
    assert "Falta fecha" in msgs
    assert "Falta total" in msgs


def test_iva_none_suma_correcta_sin_alerta_b():
    assert "Los valores no cuadran" not in _mensajes(validar_factura(_base(iva=None)))


def test_nit_ausente_es_aviso_no_error():
    for ausencia in (None, "", "   "):
        alertas = validar_factura(_base(nit=ausencia, items=[], iva=None, total=100))
        msgs = _mensajes(alertas)
        assert "NIT no leído" in msgs
        assert "NIT no reconocido, revísalo" not in msgs
        assert not [a for a in alertas if a.severidad == "error"]
        nit_alertas = [a for a in alertas if a.campo == "nit"]
        assert len(nit_alertas) == 1
        assert nit_alertas[0].regla == "nit_ausente"
        assert nit_alertas[0].severidad == "aviso"
