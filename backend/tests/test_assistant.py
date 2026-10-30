"""Tests Día 6 — asistente, sin red ni modelo real."""
import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.assistant as asm
from app import main as mainmod
from app.models import Base, Factura


def _eng():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=eng)
    return eng


@pytest.fixture()
def sess(tmp_path, monkeypatch):
    import app.segmentation as seg

    monkeypatch.setattr(seg, "CACHE_DIR", str(tmp_path / "cache"))
    eng = _eng()
    S = sessionmaker(bind=eng, expire_on_commit=False)
    s = S()
    s.add(Factura(proveedor="Proveedor A", categoria="transporte",
                  fecha=dt.date(2026, 10, 2), subtotal=200000, iva=0, total=200000))
    s.add(Factura(proveedor="Proveedor B", categoria="papeleria",
                  fecha=dt.date(2026, 10, 15), subtotal=50000, iva=0, total=50000))
    s.commit()
    yield s
    s.close()


@pytest.fixture()
def client(sess):
    def _override():
        yield sess

    mainmod.app.dependency_overrides[mainmod._get_db] = _override
    with TestClient(mainmod.app) as c:
        yield c
    mainmod.app.dependency_overrides.clear()


def test_normalizacion_basica():
    assert asm.normalizar("  ¿CUÁNTO  Gasté? ") == "¿cuánto gasté?"


def test_fallback_sin_modelo_no_llama_a_red(sess, monkeypatch):
    def boom(_pregunta):
        raise AssertionError("no debe llamar al modelo sin intención clara")

    monkeypatch.setattr(asm, "_llamar_modelo", boom)
    out = asm.responder("¿cómo exporto a Excel?", sess)
    assert out["fuente"] == "ayuda"
    assert out["cifra"] is None
    assert "mes" in out["respuesta"] and "categoría" in out["respuesta"]


def test_composicion_total_categoria_usa_sql(sess, monkeypatch):
    monkeypatch.setattr(
        asm, "_llamar_modelo",
        lambda _p: {"intencion": "total_categoria", "parametros": {"categoria": "transporte"}},
    )
    out = asm.responder("¿cuánto llevo en transporte?", sess)
    assert out == {
        "respuesta": "Total en transporte: $200,000 (dato de tu base).",
        "cifra": 200000,
        "fuente": "sql",
    }


def test_composicion_total_mes_y_proveedor(sess, monkeypatch):
    monkeypatch.setattr(
        asm, "_llamar_modelo",
        lambda _p: {"intencion": "total_mes", "parametros": {"mes": "2026-10"}},
    )
    out = asm.responder("total de octubre 2026", sess)
    assert out["cifra"] == 250000 and out["fuente"] == "sql"
    monkeypatch.setattr(
        asm, "_llamar_modelo",
        lambda _p: {"intencion": "total_proveedor", "parametros": {"proveedor": "Proveedor A"}},
    )
    # Distinta pregunta -> distinto caché
    out = asm.responder("total con proveedor A", sess)
    assert out["cifra"] == 200000 and "dato de tu base" in out["respuesta"]


def test_cache_evita_segunda_llamada(sess, monkeypatch):
    calls = {"n": 0}

    def fake(_p):
        calls["n"] += 1
        return {"intencion": "total_categoria", "parametros": {"categoria": "transporte"}}

    monkeypatch.setattr(asm, "_llamar_modelo", fake)
    asm.responder("¿cuánto llevo en transporte?", sess)
    asm.responder("¿cuánto llevo en transporte?", sess)
    assert calls["n"] == 1


def test_llamar_modelo_usa_extract_output_text_con_reasoning(sess, monkeypatch):
    import json as _json

    import requests

    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    import app.segmentation as seg

    monkeypatch.setattr(seg, "_check_daily_quota", lambda: None)
    monkeypatch.setattr(seg, "_increment_daily_count", lambda: 1)
    registrado = {}
    monkeypatch.setattr(asm, "_log_classifier_usage",
                        lambda pregunta, usage: registrado.update(usage))
    esperado = {"intencion": "total_mes",
                "parametros": {"mes": "2026-10", "categoria": None,
                               "proveedor": None, "n": None}}
    cuerpo = {
        # Campo text de configuración (dict, NO texto del modelo).
        "text": {"format": {"type": "json_object"}},
        "output": [
            {"type": "reasoning", "summary": "pienso la intención"},
            {"type": "message", "role": "assistant",
             "content": [{"type": "output_text", "text": _json.dumps(esperado)}]},
        ],
        "usage": {"input_tokens": 100, "output_tokens": 20, "reasoning_tokens": 5},
    }

    class _Resp:
        status_code = 200
        text = _json.dumps(esperado)

        def json(self):
            return cuerpo

    capturado = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        capturado["payload"] = json
        return _Resp()

    monkeypatch.setattr(requests, "post", fake_post)
    out = asm._llamar_modelo("¿Cuánto gasté en octubre de 2026?")
    assert out == esperado
    # Payload con reasoning minimal y tope de tokens.
    assert capturado["payload"]["reasoning"] == {"effort": "minimal"}
    assert capturado["payload"]["max_output_tokens"] == 1024
    assert registrado.get("reasoning_tokens") == 5


def test_fallo_parseo_guarda_debug(sess, monkeypatch, tmp_path):
    import requests

    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    import app.segmentation as seg

    monkeypatch.setattr(seg, "_check_daily_quota", lambda: None)
    monkeypatch.setattr(seg, "_increment_daily_count", lambda: 1)
    monkeypatch.setattr(asm, "_fail_dir", lambda: str(tmp_path / "fallos"))
    monkeypatch.setattr(asm, "_log_classifier_usage", lambda *a: None)

    class _Resp:
        status_code = 200
        text = "sin llaves json aquí"

        def json(self):
            return {"output_text": "sin llaves json aquí"}

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp())
    with __import__("pytest").raises(ValueError):
        asm._llamar_modelo("total de octubre 2026")
    archivos = list((tmp_path / "fallos").glob("*.txt"))
    assert len(archivos) == 1
    contenido = archivos[0].read_text(encoding="utf-8")
    assert len(contenido) <= 500 and "sin llaves" in contenido


def test_usage_row_reasoning_anidado():
    assert asm._usage_row({"input_tokens": 339, "output_tokens": 129,
                           "output_tokens_details": {"reasoning_tokens": 83}}) == ("339", "129", "83")
    assert asm._usage_row({"input_tokens": 1, "output_tokens": 2,
                           "reasoning_tokens": 5}) == ("1", "2", "5")


def test_cache_incluye_version(sess, monkeypatch):
    monkeypatch.setattr(
        asm, "_llamar_modelo",
        lambda _p: {"intencion": "total_categoria", "parametros": {"categoria": "transporte"}},
    )
    asm.responder("¿cuánto llevo en transporte?", sess)
    assert asm.CLASSIFIER_CACHE_VERSION in asm._cache_path("¿cuánto llevo en transporte?")


def test_endpoint_assistant_y_validacion(client, monkeypatch):
    monkeypatch.setattr(
        asm, "_llamar_modelo",
        lambda _p: {"intencion": "ultimas_facturas", "parametros": {"n": 5}},
    )
    r = client.post("/assistant", json={"pregunta": "muéstrame las últimas facturas"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["fuente"] == "sql" and cuerpo["cifra"] is None
    assert "dato de tu base" in cuerpo["respuesta"]
    r2 = client.post("/assistant", json={"pregunta": "   "})
    assert r2.status_code == 400


def test_composicion_doble_filtro_categoria(sess, monkeypatch):
    monkeypatch.setattr(
        asm, "_llamar_modelo",
        lambda _p: {"intencion": "total_categoria",
                    "parametros": {"categoria": "transporte", "mes": "2026-10"}},
    )
    out = asm.responder("transporte en octubre de 2026", sess)
    assert out["cifra"] == 200000 and out["fuente"] == "sql"
    assert "2026-10" in out["respuesta"]
    # Sin filas en ese mes -> 0 con fuente sql.
    monkeypatch.setattr(
        asm, "_llamar_modelo",
        lambda _p: {"intencion": "total_categoria",
                    "parametros": {"categoria": "transporte", "mes": "2026-09"}},
    )
    out = asm.responder("transporte en septiembre de 2026", sess)
    assert out["cifra"] == 0 and out["fuente"] == "sql"


def test_composicion_doble_filtro_proveedor(sess, monkeypatch):
    monkeypatch.setattr(
        asm, "_llamar_modelo",
        lambda _p: {"intencion": "total_proveedor",
                    "parametros": {"proveedor": "Proveedor A", "mes": "2026-10"}},
    )
    out = asm.responder("proveedor A en octubre de 2026", sess)
    assert out["cifra"] == 200000 and out["fuente"] == "sql"
    assert "2026-10" in out["respuesta"]


def test_mes_invalido_modelo_se_ignora(sess, monkeypatch):
    monkeypatch.setattr(
        asm, "_llamar_modelo",
        lambda _p: {"intencion": "total_categoria",
                    "parametros": {"categoria": "transporte", "mes": "octubre"}},
    )
    out = asm.responder("transporte en octubre sin formato", sess)
    # Mes no YYYY-MM se ignora -> agregado global de la fixture.
    assert out["cifra"] == 200000 and out["fuente"] == "sql"
