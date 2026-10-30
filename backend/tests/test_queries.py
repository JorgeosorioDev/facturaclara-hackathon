"""Tests Día 4 — queries + CSV + reports, SQLite memoria, sin red ni modelos."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as mainmod
from app import queries as qmod
from app.models import Base, Factura


def _eng():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    return eng


@pytest.fixture()
def sess():
    eng = _eng()
    S = sessionmaker(bind=eng, expire_on_commit=False)
    s = S()
    datos = [
        ("Proveedor A", "transporte", dt.date(2026, 9, 5), 100000),
        ("Proveedor A", "transporte", dt.date(2026, 10, 2), 200000),
        ("Proveedor B", "papeleria", dt.date(2026, 10, 15), 50000),
        ("Proveedor B", "papeleria", dt.date(2026, 10, 20), 150000),
    ]
    for prov, cat, fecha, total in datos:
        s.add(
            Factura(
                proveedor=prov, categoria=cat, fecha=fecha,
                subtotal=total, iva=0, total=total,
            )
        )
    s.commit()
    yield s
    s.close()


@pytest.fixture()
def client():
    eng = _eng()
    TestingSession = sessionmaker(bind=eng, expire_on_commit=False)
    s0 = TestingSession()
    s0.add(
        Factura(
            proveedor="Proveedor A", categoria="transporte",
            fecha=dt.date(2026, 10, 2), subtotal=200000, iva=0,
            total=200000, nit_normalizado="9000557198",
        )
    )
    s0.add(
        Factura(
            proveedor="Proveedor B", categoria="papeleria",
            fecha=dt.date(2026, 9, 5), subtotal=100000, iva=0,
            total=100000,
        )
    )
    s0.add(
        Factura(
            proveedor="Proveedor A", categoria="transporte",
            fecha=dt.date(2026, 10, 15), subtotal=50000, iva=0,
            total=50000,
        )
    )
    s0.commit()
    s0.close()

    def _override():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    mainmod.app.dependency_overrides[mainmod._get_db] = _override
    with TestClient(mainmod.app) as c:
        yield c
    mainmod.app.dependency_overrides.clear()


def test_total_por_mes_cifras_exactas(sess):
    rows = {r["mes"]: r["total"] for r in qmod.total_por_mes(sess)}
    assert rows == {"2026-09": 100000, "2026-10": 400000}


def test_total_por_categoria_cifras_exactas(sess):
    rows = {r["categoria"]: r["total"] for r in qmod.total_por_categoria(sess)}
    assert rows == {"transporte": 300000, "papeleria": 200000}


def test_total_por_proveedor_parametrizado(sess):
    assert qmod.total_por_proveedor(sess, "Proveedor A") == 300000
    assert qmod.total_por_proveedor(sess, "Proveedor B") == 200000
    assert qmod.total_por_proveedor(sess, "Nadie") == 0
    # Intento de inyección tratado como literal, no rompe ni filtra todo
    assert qmod.total_por_proveedor(sess, "' OR '1'='1") == 0


def test_ultimas_orden_y_limite(sess):
    ult = qmod.ultimas(sess, n=2)
    assert [f.id for f in ult] == sorted([f.id for f in ult], reverse=True)
    assert len(ult) == 2
    assert isinstance(ult[0].total, int)


def test_reports_mes_y_categoria(client):
    r = client.get("/reports/total", params={"group_by": "mes"})
    assert r.status_code == 200
    assert r.json()["group_by"] == "mes"
    r = client.get("/reports/total", params={"group_by": "categoria"})
    assert r.status_code == 200
    assert any(
        row["categoria"] == "transporte" and row["total"] == 250000
        for row in r.json()["rows"]
    )


def test_reports_proveedor_requiere_q(client):
    ok = client.get("/reports/total", params={"group_by": "proveedor", "q": "Proveedor A"})
    assert ok.status_code == 200
    assert ok.json()["total"] == 250000
    faltante = client.get("/reports/total", params={"group_by": "proveedor"})
    assert faltante.status_code == 400


def test_group_by_invalido_400(client):
    r = client.get("/reports/total", params={"group_by": "semana"})
    assert r.status_code == 400
    assert "group_by" in r.json()["detail"].lower() or "inválido" in r.json()["detail"]


def test_csv_header_y_filas(client):
    r = client.get("/invoices/export.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    lineas = r.text.strip().split("\n")
    assert lineas[0] == "id,proveedor,nit,fecha,subtotal,iva,total,categoria"
    assert len(lineas) == 4  # header + 3 facturas
    assert "2026-10-02" in r.text  # fecha ISO
    assert "Proveedor A" in r.text


def test_total_categoria_con_mes(sess):
    rows = {r["categoria"]: r["total"] for r in qmod.total_por_categoria(sess, mes="2026-10")}
    assert rows == {"transporte": 200000, "papeleria": 200000}
    rows_sep = {r["categoria"]: r["total"] for r in qmod.total_por_categoria(sess, mes="2026-09")}
    assert rows_sep == {"transporte": 100000}
    # Sin mes mantiene agregado global (compatibilidad).
    rows_all = {r["categoria"]: r["total"] for r in qmod.total_por_categoria(sess)}
    assert rows_all == {"transporte": 300000, "papeleria": 200000}


def test_total_proveedor_con_mes(sess):
    assert qmod.total_por_proveedor(sess, "Proveedor A", mes="2026-10") == 200000
    assert qmod.total_por_proveedor(sess, "Proveedor A", mes="2026-09") == 100000
    assert qmod.total_por_proveedor(sess, "Proveedor A") == 300000
    assert qmod.total_por_proveedor(sess, "Nadie", mes="2026-10") == 0


def test_mes_invalido_rechazado(sess):
    with __import__("pytest").raises(ValueError):
        qmod.total_por_categoria(sess, mes="2026-13")
    with __import__("pytest").raises(ValueError):
        qmod.total_por_proveedor(sess, "Proveedor A", mes="2026-10' OR '1'='1")


def test_seed_doble_filtro_cifras():
    """Valida las cifras de preguntas.json 11-13 sobre el seed real (9 filas)."""
    import json as _json
    import os as _os

    root = _os.path.normpath(_os.path.join(_os.path.dirname(__file__), "..", ".."))
    seed = _json.load(open(_os.path.join(root, "fixtures", "seed_facturas.json"), encoding="utf-8"))
    assert len(seed) == 9
    eng = _eng()
    S = sessionmaker(bind=eng, expire_on_commit=False)
    s = S()
    for f in seed:
        s.add(Factura(
            proveedor=f["proveedor"], categoria=f["categoria"],
            fecha=dt.date.fromisoformat(f["fecha"]),
            subtotal=f["total"], iva=0, total=f["total"],
        ))
    s.commit()
    cat_oct = {r["categoria"]: r["total"] for r in qmod.total_por_categoria(s, mes="2026-10")}
    assert cat_oct.get("transporte") == 180000
    cat_sep = {r["categoria"]: r["total"] for r in qmod.total_por_categoria(s, mes="2026-09")}
    assert cat_sep.get("transporte") == 75000
    assert qmod.total_por_proveedor(s, "Proveedor A", mes="2026-10") == 220000
    s.close()
