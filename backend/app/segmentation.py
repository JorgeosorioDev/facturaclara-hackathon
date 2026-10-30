"""Segmentación de documentos Día 1 — SAM 3.1 (llamada real vía Meta Model API).

Pipeline: FastAPI -> SAM 3.1 mask+crop -> OpenCV perspective -> cache por hash.
La llamada real a la API vive en :func:`_call_sam_api` (HTTP vía ``requests``).
Los tests no tocan la red: solo ejercitan :func:`crop_document` con máscaras
sintéticas y el parser SSE (:func:`_extract_markers`,
:func:`_decode_mask_payload`) con fixtures sintéticos.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date

import cv2
import numpy as np

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "cache")
CACHE_DIR = os.path.normpath(CACHE_DIR)
DEBUG_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "debug")
DEBUG_ROOT = os.path.normpath(DEBUG_ROOT)

CONFIDENCE_THRESHOLD = 0.5

PDF_MAGIC = b"%PDF"
PDF_RENDER_DPI = 200


def _is_pdf_bytes(data: bytes) -> bool:
    """True si los magic bytes indican PDF (%PDF)."""
    return bytes(data[:5]).startswith(PDF_MAGIC)


def _render_pdf_first_page(pdf_bytes: bytes) -> bytes:
    """Renderiza la primera página de un PDF a PNG (bytes).

    Usa PyMuPDF (``pymupdf``/``fitz``); si no está disponible prueba
    ``pdf2image`` como fallback. Lanza ``RuntimeError`` en español si
    falta la dependencia o el PDF no tiene páginas.
    """
    if not pdf_bytes:
        raise RuntimeError("PDF vacío: no se puede renderizar")
    try:
        import pymupdf  # type: ignore

        with pymupdf.open(stream=bytes(pdf_bytes), filetype="pdf") as doc:
            if len(doc) == 0:
                raise RuntimeError("El PDF no tiene páginas para renderizar")
            pix = doc[0].get_pixmap(dpi=PDF_RENDER_DPI)
            return bytes(pix.tobytes("png"))
    except ImportError:
        pass
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"No se pudo renderizar el PDF con pymupdf: {exc}"[:300]) from exc

    try:
        import fitz  # type: ignore  # fallback API legacy de PyMuPDF

        doc = fitz.open(stream=bytes(pdf_bytes), filetype="pdf")
        try:
            if len(doc) == 0:
                raise RuntimeError("El PDF no tiene páginas para renderizar")
            pix = doc[0].get_pixmap(dpi=PDF_RENDER_DPI)
            return bytes(pix.tobytes("png"))
        finally:
            doc.close()
    except ImportError:
        pass
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"No se pudo renderizar el PDF con fitz: {exc}"[:300]) from exc

    try:
        from pdf2image import convert_from_bytes  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Falta dependencia PDF: instala pymupdf (pip install pymupdf) "
            "o pdf2image para renderizar PDFs"
        ) from exc
    try:
        import io

        from PIL import Image

        pages = convert_from_bytes(bytes(pdf_bytes), dpi=PDF_RENDER_DPI, first_page=1, last_page=1)
        if not pages:
            raise RuntimeError("El PDF no tiene páginas para renderizar")
        buf = io.BytesIO()
        page = pages[0].convert("RGB") if pages[0].mode != "RGB" else pages[0]
        page.save(buf, format="PNG")
        return buf.getvalue()
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"No se pudo renderizar el PDF con pdf2image: {exc}"[:300]) from exc


def load_image_bytes(path_or_bytes) -> bytes:
    """Normaliza entrada imagen/PDF a bytes PNG/JPG.

    Acepta ruta (``str``/``os.PathLike``) o bytes. Si detecta PDF
    (magic bytes ``%PDF`` o extensión ``.pdf``) renderiza la primera
    página a PNG con :func:`_render_pdf_first_page`; en otro caso
    devuelve los bytes tal cual (imagen).
    """
    if isinstance(path_or_bytes, (str, os.PathLike)):
        path = os.fspath(path_or_bytes)
        with open(path, "rb") as fh:
            data = fh.read()
        if path.lower().endswith(".pdf") or _is_pdf_bytes(data):
            return _render_pdf_first_page(data)
        return data
    data = bytes(path_or_bytes)
    if _is_pdf_bytes(data):
        return _render_pdf_first_page(data)
    return data


@dataclass
class SegmentationResult:
    mask: np.ndarray  # bool
    confidence: float
    fallback: bool
    cropped: np.ndarray  # BGR
    cache_hit: bool


def _get_max_daily_calls() -> int:
    try:
        return int(os.environ.get("MAX_DAILY_CALLS", "60"))
    except Exception:
        return 60


def _daily_count_path() -> str:
    return os.path.join(CACHE_DIR, "daily_count.json")


def _read_daily_count() -> int:
    path = _daily_count_path()
    today = date.today().isoformat()
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError:
        return 0
    if data.get("date") != today:
        return 0
    try:
        return int(data.get("count", 0))
    except Exception:
        return 0


def _increment_daily_count() -> int:
    os.makedirs(CACHE_DIR, exist_ok=True)
    count = _read_daily_count() + 1
    payload = {"date": date.today().isoformat(), "count": count}
    with open(_daily_count_path(), "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return count


def _check_daily_quota() -> None:
    limit = _get_max_daily_calls()
    used = _read_daily_count()
    if used >= limit:
        raise RuntimeError(
            f"Cuota diaria de segmentación alcanzada ({used}/{limit} llamadas). "
            "Aumenta MAX_DAILY_CALLS o espera al día siguiente."
        )


SAM_ENDPOINT_DEFAULT = "https://api.meta.ai/v1/responses"
SAM_MODEL = "sam-3.1"
SAM_TIMEOUT_S = 60

# Prompt de segmentación (contrato verificado dev.meta.ai/docs/sam/segmenting).
# Default "receipt": probado en foto real con fondo (5 boxes + 5 masks, c=0.92);
# "invoice"/"paper document" devuelven cero matches. Configurable vía env
# SAM_PROMPT sin cambiar código.
SAM_PROMPT_DEFAULT = "receipt"


def _sam_cache_digest(image_bytes: bytes, concept: str) -> str:
    """sha256(imagen + concepto): cambiar el concepto invalida la caché."""
    h = hashlib.sha256()
    h.update(image_bytes)
    h.update(b"\x00")
    h.update(concept.encode("utf-8"))
    return h.hexdigest()


def _get_sam_prompt() -> str:
    """Prompt SAM 3.1 configurable (default "receipt")."""
    return os.environ.get("SAM_PROMPT", SAM_PROMPT_DEFAULT).strip() or SAM_PROMPT_DEFAULT


def _build_sam_payload(data_uri: str, prompt: str | None = None) -> dict:
    """Construye el body verificado del contrato SAM segmenting.

    Body exacto::
        {"model": "sam-3.1",
         "input": [{"type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": PROMPT},
                                {"type": "input_image", "image_url": DATA_URI}]}],
         "stream": True,
         "metadata": {"include_confidence": "true"}}

    Notas verificadas:
      - ``"type": "message"`` a nivel item es OBLIGATORIO (omitirlo causa
        200 sin marcadores).
      - ``metadata.include_confidence`` es STRING ``"true"``, no boolean.
      - ``mask_encoding`` NO se envía (default lossless ``~``); ``one_bit``
        (``!``) es opt-in posterior.
    """
    return {
        "model": SAM_MODEL,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt or _get_sam_prompt()},
                    {"type": "input_image", "image_url": data_uri},
                ],
            }
        ],
        "stream": True,
        "metadata": {"include_confidence": "true"},
    }

# Alfabeto base85 documentado:
#  - Prefijo ``~``: base85 estilo RFC 1924 (alfabeto de ``base64.b85decode``:
#    ``0-9A-Za-z!#$%&()*+-;<=>?@^_`{|}~``).
#  - Prefijo ``!``: ASCII85/Adobe (alfabeto ``!-u`` más ``z`` de
#    ``base64.a85decode(adobe=False)``).
# El payload del marcador ``<|mask;...|>`` es ``<prefijo><datos>`` donde el
# primer char (``~`` o ``!``) indica la codificación; el resto son los datos
# base85 que, decodificados, forman un bitstream (bit=1 píxel de documento)
# en orden row-major HxW. Si el bitmap decodificado no coincide con HxW se
# reescala con OpenCV (vecino más cercano).


def _extract_markers(sse_text: str) -> list[tuple[str, str]]:
    """Extrae marcadores ``<|box;...|>`` y ``<|mask;...|>`` del texto SSE."""
    import re

    pattern = re.compile(r"<\|(box|mask);(.*?)\|>", re.DOTALL)
    return [(m.group(1), m.group(2)) for m in pattern.finditer(sse_text or "")]


def _mask_score_from_payload(payload: str) -> float:
    """Score opcional embebido (``score=0.9`` / ``s:0.9`` / ``c=0.9``); 0.0 si ausente."""
    import re

    m = re.search(
        r"(?:score|confidence|conf|[sc])\s*[:=]\s*([0-9]*\.?[0-9]+)",
        payload or "",
        re.IGNORECASE,
    )
    if not m:
        return 0.0
    try:
        return float(m.group(1))
    except Exception:
        return 0.0


def _decode_mask_payload(payload: str, shape: tuple[int, int]) -> np.ndarray:
    """Decodifica el payload de un marcador ``mask`` a bitmap bool HxW.

    Detecta el prefijo ``~`` (RFC 1924) o ``!`` (ASCII85), decodifica base85
    y convierte a bitmap bool del tamaño de la imagen de entrada (resize con
    OpenCV si difiere). Soporta además el formato con dims explícitas
    ``data=<W>,<H>,<payload-base85>`` (típico ``x=..;y=..;c=..;data=..``):
    decodifica a (H,W) declarados y reescala a HxW. Lanza ``RuntimeError``
    en español si el formato no se puede decodificar (incluye el marcador
    truncado a 200 chars, nunca keys).
    """
    import base64 as _b64

    import re as _re

    h, w = shape
    if h <= 0 or w <= 0:
        raise RuntimeError("Dimensiones de imagen inválidas para decodificar la máscara")
    text = (payload or "").strip()
    if not text:
        raise RuntimeError("Marcador mask vacío: no se puede decodificar")
    # Formato SAM 3.1 con dims explícitas:
    #   ``x=..;y=..;c=0.92;data=<W>,<H>,<payload-base85>``.
    # <W>,<H> es la resolución del bitmap; <payload-base85> usa los mismos
    # prefijos ``~`` (RFC 1924) / ``!`` (ASCII85). Se decodifica a (H0,W0)
    # y se reescala a (H,W) con vecino más cercano.
    m_data = _re.search(r"data\s*=\s*(\d+)\s*,\s*(\d+)\s*,\s*(\S.*)", text)
    if m_data:
        try:
            w0, h0 = int(m_data.group(1)), int(m_data.group(2))
        except ValueError:
            w0, h0 = 0, 0
        if w0 <= 0 or h0 <= 0:
            raise RuntimeError(
                "Marcador mask con dimensiones data=W,H inválidas: "
                f"{text[:200]!r}"
            )
        inner = m_data.group(3).strip().rsplit(";", 1)[-1].strip()
        if not inner:
            raise RuntimeError(
                "Marcador mask sin datos decodificables: "
                f"{text[:200]!r}"
            )
        prefix0 = inner[0]
        body0 = inner[1:] if prefix0 in ("~", "!") else inner
        body0 = "".join(body0.split())
        if not body0:
            raise RuntimeError(
                "Marcador mask sin datos decodificables: "
                f"{text[:200]!r}"
            )
        try:
            if prefix0 == "!":
                raw0 = _b64.a85decode(body0, adobe=False)
            else:
                raw0 = _b64.b85decode(body0)
        except Exception as exc:
            raise RuntimeError(
                "No se pudo decodificar la máscara base85 de SAM 3.1 "
                f"(marcador: {text[:200]!r})"
            ) from exc
        if not raw0:
            raise RuntimeError(
                "Máscara base85 vacía tras decodificar "
                f"(marcador: {text[:200]!r})"
            )
        n0 = h0 * w0
        bits0 = np.unpackbits(np.frombuffer(raw0, dtype=np.uint8))
        if bits0.size >= n0:
            small = bits0[:n0].reshape(h0, w0).astype(np.uint8) * 255
        else:
            side0 = int(np.sqrt(bits0.size))
            if side0 * side0 == bits0.size and side0 > 0:
                small = (
                    bits0.reshape(side0, side0).astype(np.uint8) * 255
                )
                small = cv2.resize(
                    small, (w0, h0), interpolation=cv2.INTER_NEAREST
                )
            else:
                raise RuntimeError(
                    "La máscara decodificada no alcanza WxH "
                    f"({bits0.size} bits para {w0}x{h0}, marcador: {text[:200]!r})"
                )
        if (h0, w0) == (h, w):
            return (small > 127).astype(bool)
        resized0 = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
        return (resized0 > 127).astype(bool)
    # El score opcional puede venir como prefijo "score=0.9;DATOS": usar solo
    # el último segmento como datos.
    data = text.rsplit(";", 1)[-1].strip() if ";" in text else text
    if not data:
        raise RuntimeError(
            "Marcador mask sin datos decodificables: "
            f"{text[:200]!r}"
        )
    prefix = data[0]
    body = data[1:] if prefix in ("~", "!") else data
    body = "".join(body.split())
    if not body:
        raise RuntimeError(
            "Marcador mask sin datos decodificables: "
            f"{text[:200]!r}"
        )
    try:
        if prefix == "!":
            raw = _b64.a85decode(body, adobe=False)
        else:
            # "~" o sin prefijo: RFC 1924 (b85decode).
            raw = _b64.b85decode(body)
    except Exception as exc:
        raise RuntimeError(
            "No se pudo decodificar la máscara base85 de SAM 3.1 "
            f"(marcador: {text[:200]!r})"
        ) from exc
    if not raw:
        raise RuntimeError(
            "Máscara base85 vacía tras decodificar "
            f"(marcador: {text[:200]!r})"
        )
    n = h * w
    bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))
    if bits.size >= n:
        return bits[:n].reshape(h, w).astype(bool)
    # Bitstream cuadrado de otra resolución: reescalar con OpenCV.
    side = int(np.sqrt(bits.size))
    if side * side == bits.size and side > 0:
        small = bits.reshape(side, side).astype(np.uint8) * 255
        resized = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
        return (resized > 127).astype(bool)
    # Bytes como píxeles en escala de grises (umbral 127).
    byts = np.frombuffer(raw, dtype=np.uint8)
    if byts.size >= n:
        return (byts[:n].reshape(h, w).astype(np.int16) > 127).astype(bool)
    raise RuntimeError(
        "La máscara decodificada no alcanza HxW "
        f"({bits.size} bits para {h}x{w}, marcador: {text[:200]!r})"
    )


def _encode_mask_payload_for_tests(mask: np.ndarray) -> str:
    """Codifica un bitmap bool como payload ``~``+base85 (solo tests/fixtures)."""
    import base64 as _b64

    bits = np.asarray(mask, dtype=bool).ravel().astype(np.uint8)
    pad = (-len(bits)) % 8
    if pad:
        bits = np.concatenate([bits, np.zeros(pad, dtype=np.uint8)])
    raw = np.packbits(bits).tobytes()
    return "~" + _b64.b85encode(raw).decode("ascii")


def _parse_box_to_mask(payload: str, shape: tuple[int, int]) -> np.ndarray | None:
    """Convierte un marcador ``box`` (coords normalizadas o píxeles) a mask."""
    import re

    h, w = shape
    nums = [float(x) for x in re.findall(r"-?[0-9]*\.?[0-9]+", payload or "")]
    if len(nums) < 4:
        return None
    x0, y0, x1, y1 = nums[0], nums[1], nums[2], nums[3]
    # Coordenadas normalizadas 0..1 -> píxeles.
    if max(abs(x0), abs(y0), abs(x1), abs(y1)) <= 1.5:
        x0, x1 = x0 * w, x1 * w
        y0, y1 = y0 * h, y1 * h
    xa, xb = sorted((int(x0), int(x1)))
    ya, yb = sorted((int(y0), int(y1)))
    xa, ya = max(xa, 0), max(ya, 0)
    xb, yb = min(xb, w), min(yb, h)
    if xb <= xa or yb <= ya:
        return None
    mask = np.zeros((h, w), dtype=bool)
    mask[ya:yb, xa:xb] = True
    return mask


def _select_best_mask(sse_text: str, shape: tuple[int, int]) -> tuple[np.ndarray, float]:
    """Elige el mejor marcador (mayor área/score) y lo decodifica a mask HxW.

    Prioriza ``mask`` (score embebido o área del bitmap); si ningún ``mask``
    decodifica, recurre al ``box`` de mayor área. Un concepto ausente devuelve
    cero matches: el stream completa con ``output_text`` vacío y sin
    marcadores — es un resultado normal, no un error: devuelve una máscara
    vacía HxW con confidence 0.0 para que el llamante aplique fallback.

    Decisión: formato desconocido = concepto no utilizable, no error fatal.
    Si hay marcadores pero ninguno decodifica (p. ej. un ``data=W,H,payload``
    con payload corrupto o un esquema nuevo de SAM), se devuelve máscara
    vacía + 0.0 en vez de lanzar, para que :func:`segment_document`
    aplique fallback (imagen completa) y ``/scan`` responda 200 con
    ``fallback:true`` en vez de 502.
    """
    markers = _extract_markers(sse_text or "")
    if not markers:
        return np.zeros(shape, dtype=bool), 0.0
    best: np.ndarray | None = None
    best_key = -1.0
    best_score = 0.0
    for kind, payload in markers:
        if kind != "mask":
            continue
        try:
            mask = _decode_mask_payload(payload, shape)
        except RuntimeError:
            continue
        score = _mask_score_from_payload(payload)
        area = float(np.count_nonzero(mask))
        key = area + (score * 1e9 if score > 0 else 0.0)
        if best is None or key > best_key:
            best, best_key, best_score = mask, key, score
    if best is not None:
        return best, best_score
    # Fallback: mejor box por área.
    best_box: np.ndarray | None = None
    best_area = -1.0
    for kind, payload in markers:
        if kind != "box":
            continue
        m = _parse_box_to_mask(payload, shape)
        if m is None:
            continue
        area = float(np.count_nonzero(m))
        if best_box is None or area > best_area:
            best_box, best_area = m, area
    if best_box is not None:
        return best_box, 0.0
    # Formato no reconocido o marcadores inutilizables: concepto no
    # utilizable, no error fatal (ver docstring). Vacía + 0.0 -> fallback.
    return np.zeros(shape, dtype=bool), 0.0


def _collect_sse_text(resp) -> str:
    """Acumula el texto de un stream SSE (líneas ``data:`` + JSON de eventos)."""
    chunks: list[str] = []
    for line in resp.iter_lines(decode_unicode=True):
        if line is None:
            continue
        text = line if isinstance(line, str) else line.decode("utf-8", "replace")
        if not text.strip():
            continue
        if text.startswith(":"):
            continue  # comentario/heartbeat SSE
        body = text[5:].strip() if text.startswith("data:") else text.strip()
        if not body or body == "[DONE]":
            continue
        chunks.append(body)
        # Eventos JSON tipo Responses API: extraer deltas de texto si existen.
        if body.startswith("{"):
            try:
                obj = json.loads(body)
            except Exception:
                continue
            for key in ("text", "delta", "output_text", "content"):
                val = obj.get(key)
                if isinstance(val, str) and val:
                    chunks.append(val)
    return "\n".join(chunks)


def _resolve_api_key() -> str:
    """Devuelve la key sin imprimirla jamás.

    Canónica: ``MODEL_API_KEY``. Acepta ``META_API_KEY`` como fallback legacy.
    """
    key = os.environ.get("MODEL_API_KEY", "").strip()
    if key:
        return key
    return os.environ.get("META_API_KEY", "").strip()


def _call_sam_api(image_bytes: bytes) -> tuple[np.ndarray, float]:
    """Llama a la API real de Meta SAM 3.1 y devuelve ``(mask bool HxW, confidence)``.

    Contrato verificado (https://dev.meta.ai/docs/sam/segmenting):
      - Endpoint fijo ``POST https://api.meta.ai/v1/responses``.
      - Auth ``Authorization: Bearer <key>``. Env canónico ``MODEL_API_KEY``;
        acepta ``META_API_KEY`` como fallback legacy. Nunca imprime la key.
      - Body ``{"model": "sam-3.1", "input": [{"type": "message",
        "role": "user", "content": [{"type": "input_text", "text": PROMPT},
        {"type": "input_image", "image_url": DATA_URI}]}], "stream": true,
        "metadata": {"include_confidence": "true"}}``. El campo
        ``"type": "message"`` a nivel item es OBLIGATORIO (omitirlo causa
        200 sin marcadores). PROMPT default "receipt"
        (:func:`_get_sam_prompt`, env ``SAM_PROMPT``; alternativas para
        probar después: "receipt" / "paper document").
      - ``metadata.include_confidence`` es STRING ``"true"`` (no boolean).
        ``mask_encoding`` NO se envía (default lossless ``~``); ``one_bit``
        (``!``) es opt-in posterior.
      - Headers ``Accept: text/event-stream`` y
        ``Content-Type: application/json``, timeout 60s, ``stream=True``.
      - Respuesta SSE ``text/event-stream`` con marcadores ``<|box;...|>`` y
        ``<|mask;...|>`` (uno o varios: se queda con el de mayor área/score).
        La máscara va codificada en base85 con marcador de codificación
        ``~`` (RFC 1924, lossless default) o ``!`` (ASCII85/one_bit); ver
        :func:`_decode_mask_payload` para el alfabeto usado.
      - Imagen: por privacidad (NIT/datos de terceros no deben subirse a una
        URL pública) se envía data URI ``data:image/png;base64,...`` por
        defecto (doc: "a public URL or a base64 data URL"). Riesgo: límite
        de tamaño del data URI desconocido en la doc.
      - Cuota: el llamante incrementa ``daily_count`` ANTES de la llamada
        (intento = gasto; las fallidas también consumen). Ante 4xx
        permanente no reintentar (un solo intento, sin bucle de reintentos).

    Errores HTTP 4xx se propagan con mensaje claro que sugiere preguntar en
    #office-hours (posible rechazo de data URI). Nunca loguea ni incluye la
    key en mensajes. No llamar durante tests.

    Concepto ausente (stream completo sin marcadores, ``output_text`` vacío):
    resultado normal, no error — devuelve máscara vacía HxW y confidence 0.0
    para que :func:`segment_document` aplique fallback con imagen completa.
    """
    import requests

    if not image_bytes:
        raise RuntimeError("image_bytes vacío: no se puede llamar a SAM 3.1")
    api_key = _resolve_api_key()
    if not api_key:
        raise RuntimeError(
            "Falta MODEL_API_KEY en el entorno (se acepta META_API_KEY como "
            "fallback legacy): define la variable antes de llamar a SAM 3.1"
        )
    endpoint = SAM_ENDPOINT_DEFAULT

    data_uri = (
        "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    )
    payload = _build_sam_payload(data_uri)
    headers = {
        "Authorization": "Bearer " + api_key,
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(
            endpoint, json=payload, headers=headers, timeout=SAM_TIMEOUT_S, stream=True
        )
    except requests.Timeout as exc:
        raise RuntimeError(
            f"SAM 3.1 no respondió a tiempo (timeout {SAM_TIMEOUT_S}s) en {endpoint}"
        ) from exc
    except requests.RequestException as exc:
        raise RuntimeError(
            "Error de red llamando a SAM 3.1 en " + endpoint + ": "
            + str(exc)[:300]
        ) from exc

    if resp.status_code < 200 or resp.status_code >= 300:
        hint = ""
        if 400 <= resp.status_code < 500:
            hint = (
                " No reintentar ante este 4xx permanente. Si la API rechaza "
                "los data URI, pregunta en #office-hours cómo enviar la "
                "imagen (image_url pública vs data URI)."
            )
        raise RuntimeError(
            f"SAM 3.1 devolvió HTTP {resp.status_code} en {endpoint}: "
            f"{(resp.text or '')[:500]}.{hint}"
        )
    try:
        sse_text = _collect_sse_text(resp)
    except requests.RequestException as exc:
        raise RuntimeError(
            "Error leyendo el stream SSE de SAM 3.1: " + str(exc)[:300]
        ) from exc
    finally:
        try:
            resp.close()
        except Exception:
            pass

    img = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError("no se pudo decodificar image_bytes como imagen")
    shape = (int(img.shape[0]), int(img.shape[1]))
    try:
        mask, confidence = _select_best_mask(sse_text, shape)
    except RuntimeError:
        # Formato de marcador no reconocido (p. ej. esquema nuevo de SAM):
        # concepto no utilizable, no error fatal -> máscara vacía + 0.0
        # para que segment_document aplique fallback en vez de 502 en /scan.
        return np.zeros(shape, dtype=bool), 0.0
    mask = np.asarray(mask).astype(bool)
    if mask.shape != (shape[0], shape[1]):
        resized = cv2.resize(
            mask.astype(np.uint8) * 255,
            (shape[1], shape[0]),
            interpolation=cv2.INTER_NEAREST,
        )
        mask = (resized > 127).astype(bool)
    return mask, float(confidence)


def _order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def crop_document(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Recorta el documento por perspectiva a partir de la máscara.

    Usa el contorno mayor + approxPolyDP a 4 puntos y warpPerspective.
    Si no hay 4 puntos usa la caja envolvente; si la máscara está vacía
    devuelve la imagen original.
    """
    if image is None or image.size == 0:
        raise Exception("imagen vacía para crop_document")
    if mask is None or mask.size == 0 or not np.any(mask):
        return image

    bin_mask = (mask > 0).astype(np.uint8) * 255
    contours, _ = cv2.findContours(bin_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return image
    contour = max(contours, key=cv2.contourArea)
    peri = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, 0.02 * peri, True)

    if approx is not None and len(approx) == 4:
        pts = approx.reshape(4, 2).astype(np.float32)
        rect = _order_points(pts)
        (tl, tr, br, bl) = rect
        width_top = np.linalg.norm(tr - tl)
        width_bottom = np.linalg.norm(br - bl)
        height_left = np.linalg.norm(bl - tl)
        height_right = np.linalg.norm(br - tr)
        max_w = max(int(max(width_top, width_bottom)), 1)
        max_h = max(int(max(height_left, height_right)), 1)
        dst = np.array(
            [[0, 0], [max_w - 1, 0], [max_w - 1, max_h - 1], [0, max_h - 1]],
            dtype=np.float32,
        )
        matrix = cv2.getPerspectiveTransform(rect, dst)
        return cv2.warpPerspective(image, matrix, (max_w, max_h))

    x, y, w, h = cv2.boundingRect(contour)
    h_img, w_img = image.shape[:2]
    x, y = max(x, 0), max(y, 0)
    w, h = min(w, w_img - x), min(h, h_img - y)
    if w <= 0 or h <= 0:
        return image
    return image[y : y + h, x : x + w].copy()


def _is_flat_image(image: np.ndarray) -> bool:
    """True si la imagen es plana (sin fondo útil que segmentar).

    Heurística barata y local (sin red): desviación estándar baja del gris
    + densidad de bordes Canny casi nula. Una factura/foto real siempre
    tiene texto y bordes; un escaneo en blanco o imagen sintética no.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    if float(np.std(gray)) > 12.0:
        return False
    edges = cv2.Canny(gray, 50, 150)
    return float(np.count_nonzero(edges)) / edges.size < 0.005


def _save_debug_artifacts(invoice_id: str, original: np.ndarray, mask: np.ndarray, cropped: np.ndarray) -> None:
    debug_dir = os.path.join(DEBUG_ROOT, invoice_id)
    os.makedirs(debug_dir, exist_ok=True)
    cv2.imwrite(os.path.join(debug_dir, "original.jpg"), original)
    mask_img = (mask.astype(np.uint8) * 255) if mask.size else np.zeros((8, 8), dtype=np.uint8)
    cv2.imwrite(os.path.join(debug_dir, "mask.png"), mask_img)
    cv2.imwrite(os.path.join(debug_dir, "crop.jpg"), cropped)


def segment_document(image_bytes: bytes, invoice_id: str) -> SegmentationResult:
    """Segmenta el documento con cache por hash y cuota diaria.

    1. sha256(imagen + concepto) -> ``cache/{hash}.json`` + ``cache/{hash}.npy``.
       Si existen, devuelve ``cache_hit=True`` sin llamar a la API.
    2. Verifica la cuota diaria (``cache/daily_count.json`` vs ``MAX_DAILY_CALLS``).
    3. Sin cache: incrementa ``daily_count`` ANTES de llamar (intento=gasto,
       las fallidas también consumen) y llama a ``_call_sam_api`` una sola
       vez (ante 4xx permanente no reintentar).
    4. Si mask vacía o confidence < 0.5 -> fallback con imagen completa.
    5. Guarda debug en ``debug/{invoice_id}/``.

    Acepta imagen (PNG/JPG) o PDF: si ``image_bytes`` (o ruta) contiene
    magic bytes ``%PDF`` se renderiza la primera página a PNG con
    :func:`load_image_bytes` antes del sha256/cache/decode.

    Salto SAM: un PDF (página ya renderizada, sin fondo que recortar) o una
    imagen plana (sin fondo útil según :func:`_is_flat_image`) van a
    fallback directo con la imagen completa, SIN llamar a SAM 3.1 y SIN
    consumir cuota diaria.
    """
    was_pdf = False
    if isinstance(image_bytes, (str, os.PathLike)):
        was_pdf = os.fspath(image_bytes).lower().endswith(".pdf")
        image_bytes = load_image_bytes(image_bytes)
    elif isinstance(image_bytes, (bytes, bytearray)) and _is_pdf_bytes(bytes(image_bytes)):
        was_pdf = True
        image_bytes = load_image_bytes(bytes(image_bytes))
    if not image_bytes:
        raise Exception("image_bytes vacío")
    if not invoice_id:
        raise Exception("invoice_id vacío")

    digest = _sam_cache_digest(image_bytes, _get_sam_prompt())
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_json = os.path.join(CACHE_DIR, f"{digest}.json")
    cache_npy = os.path.join(CACHE_DIR, f"{digest}.npy")

    image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise Exception("no se pudo decodificar image_bytes como imagen")

    if os.path.exists(cache_json) and os.path.exists(cache_npy):
        with open(cache_json, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        mask = np.load(cache_npy).astype(bool)
        confidence = float(meta.get("confidence", 0.0))
        fallback = bool(meta.get("fallback", False))
        cropped = crop_document(image, mask)
        if fallback or cropped is image:
            cropped = crop_document(image, mask)
        _save_debug_artifacts(invoice_id, image, mask, cropped)
        return SegmentationResult(
            mask=mask,
            confidence=confidence,
            fallback=fallback,
            cropped=cropped,
            cache_hit=True,
        )

    # Salto SAM: PDF renderizado o imagen plana -> fallback directo con la
    # imagen completa, sin llamar a la API y sin consumir cuota.
    if was_pdf or _is_flat_image(image):
        h, w = image.shape[:2]
        mask = np.zeros((h, w), dtype=bool)
        cropped = image.copy()
        np.save(cache_npy, mask.astype(np.uint8))
        with open(cache_json, "w", encoding="utf-8") as fh:
            json.dump({"confidence": 0.0, "fallback": True}, fh)
        _save_debug_artifacts(invoice_id, image, mask, cropped)
        return SegmentationResult(
            mask=mask,
            confidence=0.0,
            fallback=True,
            cropped=cropped,
            cache_hit=False,
        )

    _check_daily_quota()

    # Intento = gasto: se incrementa ANTES de la llamada (las fallidas
    # también consumen cuota). Sin reintentos ante 4xx permanente.
    _increment_daily_count()
    # Llamada real a SAM 3.1 (HTTP via requests, con cuota y cache).
    mask, confidence = _call_sam_api(image_bytes)

    mask = np.asarray(mask).astype(bool)
    confidence = float(confidence)
    fallback = bool(mask.size == 0 or not np.any(mask) or confidence < CONFIDENCE_THRESHOLD)
    cropped = image.copy() if fallback else crop_document(image, mask)

    np.save(cache_npy, mask.astype(np.uint8))
    with open(cache_json, "w", encoding="utf-8") as fh:
        json.dump({"confidence": confidence, "fallback": fallback}, fh)
    _save_debug_artifacts(invoice_id, image, mask, cropped)

    return SegmentationResult(
        mask=mask,
        confidence=confidence,
        fallback=fallback,
        cropped=cropped,
        cache_hit=False,
    )
