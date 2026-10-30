"""Tests Día 2: parser defensivo y caché de extracción, sin red."""

import json

import pytest

import app.extraction as ext
from app.extraction import EXTRACTION_PROMPT, parse_extraction_output


def test_prompt_importable_y_pide_solo_json():
    assert isinstance(EXTRACTION_PROMPT, str) and len(EXTRACTION_PROMPT) > 50
    low = EXTRACTION_PROMPT.lower()
    assert "solo" in low and "json" in low
    for field in ("proveedor", "nit", "fecha", "categoria_sugerida", "confianza"):
        assert field in EXTRACTION_PROMPT


def test_parser_acepta_markdown_fences():
    raw = '```json\n{"proveedor": "X", "nit": null}\n```'
    assert parse_extraction_output(raw) == {"proveedor": "X", "nit": None}


def test_parser_extrae_objeto_entre_texto():
    raw = 'Aquí está:\n{"proveedor": "Y", "total": 5}\nListo.'
    assert parse_extraction_output(raw)["proveedor"] == "Y"


def test_parser_json_roto_lanza_valueerror():
    with pytest.raises(ValueError, match="JSON"):
        parse_extraction_output('{"proveedor": "roto",')


def test_parser_nulls_permitidos():
    data = parse_extraction_output('{"proveedor": null, "nit": null, "total": null}')
    assert all(v is None for v in data.values())


def test_reintento_simulado_ante_json_roto(monkeypatch, tmp_path):
    import app.segmentation as seg

    monkeypatch.setattr(seg, "CACHE_DIR", str(tmp_path / "cache"))
    calls = {"n": 0}

    def fake_call(_img, prompt=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return "esto no es json"
        return '{"proveedor": "VEFLAT SAS", "nit": "901475872"}'

    monkeypatch.setattr(ext, "_call_extraction_api", fake_call)
    monkeypatch.setattr(seg, "_check_daily_quota", lambda: None)
    monkeypatch.setattr(seg, "_increment_daily_count", lambda: 1)
    out = ext.extract_invoice(b"\x89PNGfakex", "inv-retry")
    assert out["proveedor"] == "VEFLAT SAS"
    assert calls["n"] == 2
    assert out["cache_hit"] is False


def test_doble_fallo_lanza_runtimeerror_espanol(monkeypatch, tmp_path):
    import app.segmentation as seg

    monkeypatch.setattr(seg, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(ext, "_call_extraction_api", lambda _img, prompt=None: "basura{{{")
    monkeypatch.setattr(seg, "_check_daily_quota", lambda: None)
    monkeypatch.setattr(seg, "_increment_daily_count", lambda: 1)
    with pytest.raises(RuntimeError, match="reintento"):
        ext.extract_invoice(b"\x89PNGfakex", "inv-fail")


def test_cache_hit_sin_red(monkeypatch, tmp_path):
    import app.segmentation as seg

    monkeypatch.setattr(seg, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(seg, "_check_daily_quota", lambda: None)
    monkeypatch.setattr(seg, "_increment_daily_count", lambda: 1)
    monkeypatch.setattr(
        ext, "_call_extraction_api", lambda _img, prompt=None: '{"proveedor": "A"}'
    )
    first = ext.extract_invoice(b"\x89PNGfakex", "inv-cache")
    assert first["cache_hit"] is False

    def boom(*a, **k):
        raise AssertionError("no debe llamar a la red en cache_hit")

    monkeypatch.setattr(ext, "_call_extraction_api", boom)
    second = ext.extract_invoice(b"\x89PNGfakex", "inv-cache")
    assert second["cache_hit"] is True
    assert second["proveedor"] == "A"


def test_cache_digest_incluye_modelo_y_version():
    import hashlib

    assert ext.PROMPT_VERSION == "v2"
    img = b"\x89PNGfakeimg"
    plain = hashlib.sha256(img).hexdigest()
    assert ext._extraction_cache_digest(img) != plain
