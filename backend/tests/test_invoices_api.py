"""Tests Día 3 — endpoints /invoices con SQLite en memoria, sin red."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as mainmod
from app.models import Base


@pytest.fixture()
def client():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    TestingSession = sessionmaker(bind=eng, expire_on_commit=False)

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


def _payload(**kw):
    d = {
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
        "categoria": "papeleria",
        "confianza": 0.9,
    }
    d.update(kw)
    return d


def test_post_valida_guarda_y_devuelve_alertas(client):
    r = client.post("/invoices", json=_payload())
    assert r.status_code in (200, 201)
    body = r.json()
    assert body["factura"]["id"]
    assert body["alertas"] == []


def test_post_con_alerta_no_bloquea(client):
    r = client.post("/invoices", json=_payload(nit="900055719-7"))
    assert r.status_code in (200, 201)
    body = r.json()
    assert body["factura"]["id"]
    assert any(a["mensaje"] == "NIT no reconocido, revísalo" for a in body["alertas"])


def test_get_list_y_detalle(client):
    rid = client.post("/invoices", json=_payload()).json()["factura"]["id"]
    lst = client.get("/invoices").json()
    assert any(f["id"] == rid for f in lst["facturas"])
    det = client.get(f"/invoices/{rid}").json()
    assert det["factura"]["id"] == rid
    assert "alertas" in det


def test_put_reedita_y_revalida(client):
    rid = client.post("/invoices", json=_payload()).json()["factura"]["id"]
    r = client.put(
        "/invoices/{rid}".format(rid=rid),
        json=_payload(proveedor="Otro", total=1),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["factura"]["proveedor"] == "Otro"
    assert any(a["mensaje"] == "Los valores no cuadran" for a in body["alertas"])


def test_get_404(client):
    assert client.get("/invoices/999999").status_code == 404
