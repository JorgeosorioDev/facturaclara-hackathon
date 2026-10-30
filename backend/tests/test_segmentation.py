"""Tests Día 1: crop_document y parser SSE, sin red ni modelo."""

import numpy as np
import pytest

from app.segmentation import (
    SAM_PROMPT_DEFAULT,
    _build_sam_payload,
    _decode_mask_payload,
    _encode_mask_payload_for_tests,
    _extract_markers,
    _get_sam_prompt,
    _select_best_mask,
    crop_document,
    load_image_bytes,
    segment_document,
)


def test_load_image_bytes_detects_pdf_magic():
    pytest = __import__("pytest")
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        try:
            from pdf2image import convert_from_bytes  # noqa: F401
        except ImportError:
            pytest.skip("sin lib PDF (pymupdf/pdf2image)")
    fake_pdf = b"%PDF-1.4 fake"
    try:
        out = load_image_bytes(fake_pdf)
    except RuntimeError:
        pass  # PDF inválido: basta con que intente conversión y falle en español
    else:
        assert out[:4] != fake_pdf[:4], "magic %PDF debe disparar conversión, no passthrough"


def _synthetic_rect(width=200, height=200, x0=40, y0=50, x1=160, y1=150):
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[y0:y1, x0:x1] = (200, 200, 200)
    mask = np.zeros((height, width), dtype=bool)
    mask[y0:y1, x0:x1] = True
    return image, mask


def test_crop_document_rect_mask_returns_reasonable_crop():
    image, mask = _synthetic_rect()
    cropped = crop_document(image, mask)
    assert cropped is not None
    assert cropped.size > 0
    h, w = cropped.shape[:2]
    # Rect 120x100: el crop debe acercarse a esas dims con tolerancia de warp.
    assert 60 <= w <= 160
    assert 60 <= h <= 160
    assert np.mean(cropped) > 50  # mayormente el rectangulo claro, no fondo negro


def test_crop_document_empty_mask_returns_original():
    image, _ = _synthetic_rect()
    empty = np.zeros((200, 200), dtype=bool)
    cropped = crop_document(image, empty)
    assert cropped.shape == image.shape
    assert np.array_equal(cropped, image)


def _synthetic_sse(mask_payload: str) -> str:
    return (
        "event: message\n"
        'data: {"text": "segmentando"}\n'
        "\n"
        f"data: resultado <|mask;{mask_payload}|> fin\n"
        "\n"
        "data: [DONE]\n"
    )


def test_extract_markers_finds_mask():
    sse = _synthetic_sse("~ABC123")
    markers = _extract_markers(sse)
    assert markers == [("mask", "~ABC123")]


def test_decode_mask_payload_roundtrip():
    rng_mask = np.zeros((16, 16), dtype=bool)
    rng_mask[2:10, 3:12] = True
    payload = _encode_mask_payload_for_tests(rng_mask)
    assert payload.startswith("~")
    decoded = _decode_mask_payload(payload, (16, 16))
    assert decoded.shape == (16, 16)
    assert np.array_equal(decoded, rng_mask)


def test_select_best_mask_picks_largest_area():
    small = np.zeros((16, 16), dtype=bool)
    small[0:4, 0:4] = True
    big = np.zeros((16, 16), dtype=bool)
    big[0:12, 0:12] = True
    sse = (
        f"<|mask;{_encode_mask_payload_for_tests(small)}|> "
        f"<|mask;{_encode_mask_payload_for_tests(big)}|>"
    )
    mask, _ = _select_best_mask(sse, (16, 16))
    assert int(np.count_nonzero(mask)) == int(np.count_nonzero(big))


def test_decode_mask_payload_invalid_raises_spanish():
    with pytest.raises(RuntimeError, match="decodific"):
        _decode_mask_payload('~"""no-es-base85-válido\\\'', (8, 8))


def test_sam_prompt_default_is_invoice():
    assert SAM_PROMPT_DEFAULT == "receipt"
    assert _get_sam_prompt() == "receipt"


def test_build_sam_payload_verified_contract():
    payload = _build_sam_payload("data:image/png;base64,AAA")
    assert payload["model"] == "sam-3.1"
    assert payload["stream"] is True
    # "type": "message" a nivel item es OBLIGATORIO.
    item = payload["input"][0]
    assert item["type"] == "message"
    assert item["role"] == "user"
    content = item["content"]
    assert content[0] == {"type": "input_text", "text": "receipt"}
    assert content[1] == {"type": "input_image", "image_url": "data:image/png;base64,AAA"}
    # metadata.include_confidence es STRING, no boolean.
    assert payload["metadata"] == {"include_confidence": "true"}
    # mask_encoding NO se envía (default lossless ~).
    assert "mask_encoding" not in payload


def _synthetic_empty_sse() -> str:
    """SSE sintético de concepto ausente: 1 llamada, text="" en todo, cero deltas."""
    return (
        "event: response.completed\n"
        'data: {"type": "response.completed", "text": "", "output_text": ""}\n'
        "\n"
        'data: {"text": "", "delta": "", "output_text": "", "content": ""}\n'
        "\n"
        "data: [DONE]\n"
    )


def test_select_best_mask_empty_stream_returns_empty_mask():
    mask, confidence = _select_best_mask(_synthetic_empty_sse(), (16, 16))
    assert mask.shape == (16, 16)
    assert mask.dtype == bool
    assert not np.any(mask)
    assert confidence == 0.0


def test_segment_document_empty_sam_result_uses_fallback(monkeypatch, tmp_path):
    import cv2

    import app.segmentation as seg

    monkeypatch.setattr(seg, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(seg, "DEBUG_ROOT", str(tmp_path / "debug"))
    monkeypatch.setattr(
        seg, "_call_sam_api", lambda _image_bytes: (np.zeros((40, 50), dtype=bool), 0.0)
    )
    image = np.full((40, 50, 3), 128, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", image)
    assert ok
    result = segment_document(bytes(buf.tobytes()), "test-invoice-empty")
    assert result.fallback is True
    assert result.cache_hit is False
    assert not np.any(result.mask)
    assert result.confidence == 0.0
    assert np.array_equal(result.cropped, image)
    debug_dir = tmp_path / "debug" / "test-invoice-empty"
    assert (debug_dir / "original.jpg").exists()
    assert (debug_dir / "mask.png").exists()
    assert (debug_dir / "crop.jpg").exists()
    cache_files = list((tmp_path / "cache").glob("*"))
    assert cache_files, "el camino fallback debe guardar caché"


def test_cache_digest_cambia_con_concepto():
    from app.segmentation import _sam_cache_digest

    img = b"\x89PNGfakeimg"
    assert SAM_PROMPT_DEFAULT == "receipt"
    assert _sam_cache_digest(img, "receipt") != _sam_cache_digest(img, "invoice")
    assert _sam_cache_digest(img, "receipt") != _sam_cache_digest(img, "paper document")


def test_decode_mask_payload_data_dims_format_roundtrip():
    # Formato SAM 3.1 con dims explícitas: x=..;y=..;c=..;data=W,H,payload.
    rng_mask = np.zeros((8, 8), dtype=bool)
    rng_mask[1:6, 2:7] = True
    inner = _encode_mask_payload_for_tests(rng_mask)
    payload = f"x=0;y=0;c=0.9219;data=8,8,{inner}"
    decoded = _decode_mask_payload(payload, (8, 8))
    assert decoded.shape == (8, 8)
    assert np.array_equal(decoded, rng_mask)
    # c= se expone como confidence del marcador.
    assert _select_best_mask(f"<|mask;{payload}|>", (8, 8))[1] == 0.9219


def test_select_best_mask_undecodable_data_format_returns_empty():
    # Evidencia real SAM 3.1 (200 con marcador indecodificable):
    # formato desconocido = concepto no utilizable, no error fatal.
    sse = "<|mask;x=0;y=0;c=0.9219;data=663,1024,~!!3_7#...|>"
    mask, confidence = _select_best_mask(sse, (16, 16))
    assert mask.shape == (16, 16)
    assert mask.dtype == bool
    assert not np.any(mask)
    assert confidence == 0.0


def test_segment_document_undecodable_marker_falls_back(monkeypatch, tmp_path):
    import cv2

    import app.segmentation as seg

    monkeypatch.setattr(seg, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(seg, "DEBUG_ROOT", str(tmp_path / "debug"))
    sse = "<|mask;x=0;y=0;c=0.9219;data=663,1024,~!!3_7#...|>"

    def fake_call(image_bytes):
        img = cv2.imdecode(
            np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE
        )
        shape = (int(img.shape[0]), int(img.shape[1]))
        # Replica _call_sam_api: formato no reconocido -> vacía + 0.0.
        return seg._select_best_mask(sse, shape)

    monkeypatch.setattr(seg, "_call_sam_api", fake_call)
    rng = np.random.default_rng(7)
    image = rng.integers(0, 256, size=(40, 50, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", image)
    assert ok
    result = segment_document(bytes(buf.tobytes()), "test-invoice-bad-marker")
    assert result.fallback is True
    assert result.confidence == 0.0
    assert not np.any(result.mask)
    assert np.array_equal(result.cropped, image)
