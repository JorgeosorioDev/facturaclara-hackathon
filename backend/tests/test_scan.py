"""Tests POST /scan punta a punta con modelo mockeado, sin red ni API real."""
import base64

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import extraction as ext
from app import main as mainmod
from app import segmentation as seg
from app.segmentation import SegmentationResult


def _png(color=200, w=60, h=40):
    img = np.full((h, w, 3), color, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return bytes(buf.tobytes()), img


@pytest.fixture()
def client():
    with TestClient(mainmod.app) as c:
        yield c


def _extraccion_con_alertas():
    return {
        "proveedor": "Tienda X",
        "nit": "123",  # DV inválido -> alerta de NIT
        "fecha": "2026-10-01",
        "items": [
            {"descripcion": "a", "cantidad": 1, "precio_unitario": 1000, "total": 1000},
        ],
        "subtotal": 1000,
        "iva": 190,
        "total": 5000,  # no cuadra -> alerta de total
        "categoria_sugerida": "otros",
        "confianza": 0.8,
        "cache_hit": False,
    }


def _mock_ok(monkeypatch, png_bytes, img, fallback=False, confianza=0.9):
    mask = np.zeros((img.shape[0], img.shape[1]), dtype=bool)
    if not fallback:
        mask[5:30, 5:50] = True
    monkeypatch.setattr(
        seg,
        "segment_document",
        lambda _b, _i: SegmentationResult(
            mask=mask,
            confidence=0.0 if fallback else confianza,
            fallback=fallback,
            cropped=img.copy(),
            cache_hit=False,
        ),
    )
    monkeypatch.setattr(ext, "extract_invoice", lambda _b, _i: _extraccion_con_alertas())


def test_scan_feliz_con_alertas(client, monkeypatch):
    png_bytes, img = _png()
    _mock_ok(monkeypatch, png_bytes, img)
    r = client.post(
        "/scan",
        files={"file": ("factura.jpg", png_bytes, "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["factura"]["proveedor"] == "Tienda X"
    assert body["factura"]["id"]
    assert body["fallback"] is False
    assert body["confianza_segmentacion"] == 0.9
    assert any(a["mensaje"] == "Los valores no cuadran" for a in body["alertas"])
    crop = base64.b64decode(body["crop_base64"])
    assert crop[:8] == b"\x89PNG\r\n\x1a\n"


def test_scan_fallback_mask_vacia_usa_original(client, monkeypatch):
    png_bytes, img = _png(color=128)
    _mock_ok(monkeypatch, png_bytes, img, fallback=True)
    r = client.post(
        "/scan", files={"file": ("factura.png", png_bytes, "image/png")}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fallback"] is True
    assert body["confianza_segmentacion"] == 0.0
    crop = base64.b64decode(body["crop_base64"])
    dec = cv2.imdecode(np.frombuffer(crop, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert dec.shape == img.shape
    assert np.array_equal(dec, img)


def test_scan_cuota_alcanzada_429(client, monkeypatch):
    png_bytes, _ = _png()
    monkeypatch.setattr(
        seg,
        "segment_document",
        lambda _b, _i: (_ for _ in ()).throw(
            RuntimeError("Cuota diaria de segmentación alcanzada (60/60 llamadas)")
        ),
    )
    r = client.post(
        "/scan", files={"file": ("f.jpg", png_bytes, "image/jpeg")}
    )
    assert r.status_code == 429
    assert "Cuota" in r.json()["detail"]


def test_scan_pdf_aceptado(client, monkeypatch):
    png_bytes, img = _png()
    _mock_ok(monkeypatch, png_bytes, img)
    r = client.post(
        "/scan", files={"file": ("f.pdf", b"%PDF-1.4 fake", "application/pdf")}
    )
    assert r.status_code == 200, r.text
    assert r.json()["factura"]["id"]


def test_scan_archivo_invalido_400(client):
    r = client.post(
        "/scan", files={"file": ("notas.txt", b"hola mundo", "text/plain")}
    )
    assert r.status_code == 400
    assert "no válido" in r.json()["detail"]


def test_scan_marcador_indecodificable_200_fallback(client, monkeypatch, tmp_path):
    """SAM 200 con marcador data=W,H corrupto -> 200 + fallback:true, sin red."""
    import requests

    monkeypatch.setattr(seg, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(seg, "DEBUG_ROOT", str(tmp_path / "debug"))
    monkeypatch.setenv("MODEL_API_KEY", "test-key-sin-red")
    rng = np.random.default_rng(3)
    img = rng.integers(0, 256, size=(40, 50, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    png_bytes = bytes(buf.tobytes())

    sse_marker = "<|mask;x=0;y=0;c=0.9219;data=663,1024,~!!3_7#...|>"

    class _FakeResp:
        status_code = 200
        text = sse_marker

        def iter_lines(self, decode_unicode=True):
            return iter([f"data: {sse_marker}", "data: [DONE]"])

        def close(self):
            pass

    monkeypatch.setattr(requests, "post", lambda *a, **k: _FakeResp())
    monkeypatch.setattr(ext, "extract_invoice", lambda _b, _i: _extraccion_con_alertas())
    r = client.post(
        "/scan", files={"file": ("factura.png", png_bytes, "image/png")}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fallback"] is True
    assert body["confianza_segmentacion"] == 0.0
