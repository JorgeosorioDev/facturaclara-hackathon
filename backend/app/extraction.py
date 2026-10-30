"""Extracción de facturas Día 2 — Muse Spark con esquema JSON fijo.

Pipeline: imagen/PDF normalizado a PNG -> POST Meta Model API (muse-spark-1.3)
-> parser defensivo con 1 reintento -> caché por hash.

La llamada real vive en :func:`_call_extraction_api` (HTTP vía ``requests``).
Los tests no tocan la red: solo ejercitan :func:`parse_extraction_output`
y el caché de :func:`extract_invoice` con ``requests.post`` simulado.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os

EXTRACTION_MODEL = "muse-spark-1.3"
EXTRACTION_ENDPOINT = "https://api.meta.ai/v1/responses"
EXTRACTION_TIMEOUT_S = 60

# Versión del prompt: subirla invalida la caché (la clave incluye modelo + versión).
PROMPT_VERSION = "v2"


def _extraction_cache_digest(image_bytes: bytes) -> str:
    """sha256(imagen + modelo + PROMPT_VERSION)."""
    h = hashlib.sha256()
    h.update(image_bytes)
    h.update(b"\x00")
    h.update(EXTRACTION_MODEL.encode("utf-8"))
    h.update(b"\x00")
    h.update(PROMPT_VERSION.encode("utf-8"))
    return h.hexdigest()

CATEGORIES = [
    "papeleria",
    "transporte",
    "servicios",
    "alimentacion",
    "salud",
    "otros",
]

EXTRACTION_PROMPT = """Eres un extractor de facturas. Responde SOLO con un objeto JSON válido, sin markdown, sin fences, sin texto adicional.
Esquema exacto (nombres de campos en español):
{"proveedor": "string o null", "nit": "string de dígitos o null", "fecha": "YYYY-MM-DD o null", "items": [{"descripcion": "string", "cantidad": 0, "precio_unitario": 0, "total": 0}], "subtotal": 0 o null, "iva": 0 o null, "total": 0 o null, "categoria_sugerida": "papeleria | transporte | servicios | alimentacion | salud | otros", "confianza": 0.0-1.0}
Reglas:
- Si un campo es ilegible o no aparece en la imagen, usa null. Nunca inventes valores.
- Moneda COP: montos como enteros sin separadores.
- NIT: si el DV está impreso en la factura, devuelve el NIT como "base-DV" (p. ej. "900055719-8"); si no hay DV visible, solo los dígitos base.
- categoria_sugerida debe ser uno de: papeleria, transporte, servicios, alimentacion, salud, otros.
- confianza: número entre 0.0 y 1.0 con tu certeza global."""

RETRY_SUFFIX = " Recuerda: responde solo JSON válido, sin markdown."

CONTRACT_FIELDS = (
    "proveedor",
    "nit",
    "fecha",
    "items",
    "subtotal",
    "iva",
    "total",
    "categoria_sugerida",
    "confianza",
)


def _resolve_api_key() -> str:
    """Key canónica ``MODEL_API_KEY`` con fallback legacy ``META_API_KEY``."""
    key = os.environ.get("MODEL_API_KEY", "").strip()
    if key:
        return key
    return os.environ.get("META_API_KEY", "").strip()


def _strip_markdown_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        # Quita la primera línea (```json) y el cierre final ```.
        lines = t.splitlines()
        lines = lines[1:] if len(lines) > 1 else []
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def parse_extraction_output(text: str) -> dict:
    """Parser defensivo: extrae el objeto {...} y hace json.loads.

    Acepta fences markdown y texto alrededor. Lanza ``ValueError`` en
    español si no hay JSON válido.
    """
    cleaned = _strip_markdown_fences(text or "")
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("La respuesta del modelo no contiene un objeto JSON")
    candidate = cleaned[start : end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON de extracción inválido: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("El JSON de extracción debe ser un objeto")
    return data


def _normalize_contract(data: dict) -> dict:
    """Completa campos faltantes del contrato con null y valida categoría."""
    out = {field: data.get(field) for field in CONTRACT_FIELDS}
    if out.get("categoria_sugerida") not in CATEGORIES:
        out["categoria_sugerida"] = "otros"
    if not isinstance(out.get("items"), list):
        out["items"] = []
    return out


def _extract_output_text(payload: dict) -> str:
    """Extrae el texto de una respuesta de la Responses API (varios shapes)."""
    if not isinstance(payload, dict):
        return ""
    for key in ("output_text", "text"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
    output = payload.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            for ck in ("text", "output_text", "content"):
                v = item.get(ck)
                if isinstance(v, str) and v.strip():
                    parts.append(v)
            for sub in item.get("content", []) if isinstance(item.get("content"), list) else []:
                if isinstance(sub, dict):
                    t = sub.get("text")
                    if isinstance(t, str) and t.strip():
                        parts.append(t)
        if parts:
            return "\n".join(parts)
    return ""


def _build_extraction_payload(data_uri: str, prompt: str | None = None) -> dict:
    return {
        "model": EXTRACTION_MODEL,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt or EXTRACTION_PROMPT},
                    {"type": "input_image", "image_url": data_uri},
                ],
            }
        ],
        "stream": False,
    }


def _call_extraction_api(image_bytes: bytes, prompt: str | None = None) -> str:
    """Llama a la API real y devuelve el texto crudo del modelo."""
    import requests

    if not image_bytes:
        raise RuntimeError("image_bytes vacío: no se puede llamar a Muse Spark")
    api_key = _resolve_api_key()
    if not api_key:
        raise RuntimeError(
            "Falta MODEL_API_KEY en el entorno (se acepta META_API_KEY como "
            "fallback legacy): define la variable antes de llamar a Muse Spark"
        )
    data_uri = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    payload = _build_extraction_payload(data_uri, prompt)
    headers = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}
    try:
        resp = requests.post(
            EXTRACTION_ENDPOINT, json=payload, headers=headers, timeout=EXTRACTION_TIMEOUT_S
        )
    except requests.Timeout as exc:
        raise RuntimeError(
            f"Muse Spark no respondió a tiempo (timeout {EXTRACTION_TIMEOUT_S}s)"
        ) from exc
    except requests.RequestException as exc:
        raise RuntimeError("Error de red llamando a Muse Spark: " + str(exc)[:300]) from exc
    if resp.status_code < 200 or resp.status_code >= 300:
        raise RuntimeError(
            f"Muse Spark devolvió HTTP {resp.status_code}: {(resp.text or '')[:500]}"
        )
    try:
        body = resp.json()
    except Exception:
        # Si no es JSON, usar el texto crudo como salida del modelo.
        return resp.text or ""
    text = _extract_output_text(body)
    return text or resp.text or ""


def _cache_paths(digest: str) -> str:
    from app import segmentation as seg

    os.makedirs(seg.CACHE_DIR, exist_ok=True)
    return os.path.join(seg.CACHE_DIR, f"ext_{digest}.json")


def extract_invoice(image_bytes, invoice_id: str) -> dict:
    """Extrae el JSON del contrato desde imagen/PDF con caché y 1 reintento.

    1. Normaliza PDF -> PNG pág. 1 (como segmentation) antes del hash.
    2. sha256(imagen + modelo + PROMPT_VERSION) -> ``cache/ext_<sha>.json``;
       si existe, ``cache_hit=True``.
    3. Sin caché: verifica cuota diaria compartida con segmentation
       (mismo ``daily_count``), incrementa ANTES de llamar y hace POST
       a la Responses API con ``stream=False``.
    4. Parser defensivo: si falla, 1 reintento con instrucción de
       "solo JSON válido"; si sigue fallando, ``RuntimeError`` en español.
    """
    from app import segmentation as seg

    if isinstance(image_bytes, (str, os.PathLike)):
        image_bytes = seg.load_image_bytes(image_bytes)
    elif isinstance(image_bytes, (bytes, bytearray)) and seg._is_pdf_bytes(bytes(image_bytes)):
        image_bytes = seg.load_image_bytes(bytes(image_bytes))
    else:
        image_bytes = bytes(image_bytes) if image_bytes is not None else b""
    if not image_bytes:
        raise RuntimeError("image_bytes vacío: no se puede extraer la factura")
    if not invoice_id:
        raise RuntimeError("invoice_id vacío")

    digest = _extraction_cache_digest(image_bytes)
    cache_path = _cache_paths(digest)
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as fh:
            cached = json.load(fh)
        cached["cache_hit"] = True
        return cached

    seg._check_daily_quota()
    seg._increment_daily_count()
    raw = _call_extraction_api(image_bytes)
    try:
        data = parse_extraction_output(raw)
    except ValueError:
        raw_retry = _call_extraction_api(image_bytes, prompt=EXTRACTION_PROMPT + RETRY_SUFFIX)
        try:
            data = parse_extraction_output(raw_retry)
        except ValueError as exc:
            raise RuntimeError(
                "No se pudo obtener un JSON válido de Muse Spark tras 1 reintento: "
                f"{exc}"
            ) from exc
    result = _normalize_contract(data)
    result["cache_hit"] = False
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False)
    return result
