"""Asistente Día 6 — intención cerrada, cifra solo de SQL.

Flujo: normaliza texto -> si no hay pista de mes/categoría/proveedor/
últimas, devuelve ayuda SIN llamar al modelo. Con intención clara:
1 llamada a muse-spark-1.3 que devuelve SOLO JSON
{"intencion": ..., "parametros": {...}}. La cifra sale de queries.py;
el modelo nunca escribe números. Respuesta final compuesta en código.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

from app import queries as qmod
from app.extraction import _extract_output_text
from app.models import CATEGORIAS_FIJAS

ASSISTANT_MODEL = "muse-spark-1.3"
ASSISTANT_ENDPOINT = "https://api.meta.ai/v1/responses"
ASSISTANT_TIMEOUT_S = 30
CLASSIFIER_CACHE_VERSION = "v4"
CLASSIFIER_MAX_OUTPUT_TOKENS = 1024

AYUDA_TEXTO = (
    "Puedo decirte totales por mes, categoría o proveedor. "
    "Ejemplos: «¿cuánto gasté en octubre?», "
    "«¿cuánto llevo en transporte?», "
    "«¿cuánto le compré al proveedor X?» o «muéstrame las últimas facturas»."
)

CLASSIFY_PROMPT = """Clasifica la pregunta en UNA intención. Responde SOLO con un objeto JSON válido, sin markdown ni texto adicional.
Intenciones: total_mes | total_categoria | total_proveedor | ultimas_facturas.
Esquema: {"intencion": "<una de las 4>", "parametros": {"mes": "YYYY-MM o null", "categoria": "papeleria|transporte|servicios|alimentacion|salud|otros o null", "proveedor": "string o null", "n": 5 o null}}
Si el mes viene sin año (ej. "en octubre"), asume 2026. total_categoria y total_proveedor aceptan mes opcional para filtro doble; la cifra final siempre sale de SQL, nunca la escribas tú.
Ejemplos:
- "¿cuánto gasté en octubre de 2026?" -> {"intencion": "total_mes", "parametros": {"mes": "2026-10", "categoria": null, "proveedor": null, "n": null}}
- "¿cuánto llevo en transporte?" -> {"intencion": "total_categoria", "parametros": {"mes": null, "categoria": "transporte", "proveedor": null, "n": null}}
- "¿cuánto gasté en transporte en octubre de 2026?" -> {"intencion": "total_categoria", "parametros": {"mes": "2026-10", "categoria": "transporte", "proveedor": null, "n": null}}
- "¿cuánto le compré a Proveedor A?" -> {"intencion": "total_proveedor", "parametros": {"mes": null, "categoria": null, "proveedor": "Proveedor A", "n": null}}
- "¿cuánto le compré al Proveedor A en octubre de 2026?" -> {"intencion": "total_proveedor", "parametros": {"mes": "2026-10", "categoria": null, "proveedor": "Proveedor A", "n": null}}
- "muéstrame las últimas 3 facturas" -> {"intencion": "ultimas_facturas", "parametros": {"mes": null, "categoria": null, "proveedor": null, "n": 3}}
Pregunta: """

INTENCIONES_VALIDAS = (
    "total_mes",
    "total_categoria",
    "total_proveedor",
    "ultimas_facturas",
)

_MESES = (
    "enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    "septiembre|setiembre|octubre|noviembre|diciembre"
)
_PISTA_RE = re.compile(
    r"mes|total|gasto|gast|cu[aá]nto|"
    + _MESES
    + r"|20\d{2}[-/]\d{1,2}|categor[ií]a|"
    + "|".join(CATEGORIAS_FIJAS)
    + r"|proveedor|factura|facturas|[uú]ltimas?|recientes?|historial",
)


def _get_api_key() -> str:
    key = os.environ.get("MODEL_API_KEY", "").strip()
    if key:
        return key
    return os.environ.get("META_API_KEY", "").strip()


def _repo_root() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )


def _fail_dir() -> str:
    path = os.path.join(_repo_root(), "debug", "clasificador_fallos")
    os.makedirs(path, exist_ok=True)
    return path


def _cache_dir() -> str:
    from app import segmentation as seg

    os.makedirs(seg.CACHE_DIR, exist_ok=True)
    return seg.CACHE_DIR


def _cache_path(texto_norm: str) -> str:
    digest = hashlib.sha256(
        (CLASSIFIER_CACHE_VERSION + "\x00" + texto_norm).encode("utf-8")
    ).hexdigest()
    return os.path.join(_cache_dir(), f"ask_{CLASSIFIER_CACHE_VERSION}_{digest}.json")


def normalizar(texto: str) -> str:
    norm = (texto or "").strip().lower()
    return re.sub(r"\s+", " ", norm)


def tiene_intencion_clara(texto_norm: str) -> bool:
    return _PISTA_RE.search(texto_norm) is not None


def _extraer_json_modelo(texto: str) -> dict:
    start = texto.find("{")
    end = texto.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("El clasificador no devolvió un objeto JSON")
    try:
        data = json.loads(texto[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON de intención inválido: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("El JSON de intención debe ser un objeto")
    return data


def _build_classify_payload(pregunta: str) -> dict:
    return {
        "model": ASSISTANT_MODEL,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": CLASSIFY_PROMPT + pregunta}
                ],
            }
        ],
        "reasoning": {"effort": "minimal"},
        "max_output_tokens": CLASSIFIER_MAX_OUTPUT_TOKENS,
        "stream": False,
    }


def _usage_row(usage: dict) -> tuple:
    def _entero(v) -> str:
        try:
            return str(int(v))
        except (TypeError, ValueError):
            return ""

    reasoning = usage.get("reasoning_tokens")
    if reasoning is None:
        detalles = usage.get("output_tokens_details")
        if isinstance(detalles, dict):
            reasoning = detalles.get("reasoning_tokens")
    return (
        _entero(usage.get("input_tokens")),
        _entero(usage.get("output_tokens")),
        _entero(reasoning),
    )


def _log_classifier_usage(pregunta: str, usage: dict) -> None:
    """Anexa una fila a reports/usage.csv con tokens in/out/reasoning."""
    import csv

    try:
        tokens_in, tokens_out, reasoning = _usage_row(usage or {})
        path = os.path.join(_repo_root(), "reports", "usage.csv")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        header = [
            "fecha", "modelo", "prompt", "imagen", "bytes_enviados",
            "eventos", "n_matches", "tokens_in", "tokens_out",
            "reasoning_tokens", "costo_usd",
        ]
        rows: list[list[str]] = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8", newline="") as fh:
                rows = [r for r in csv.reader(fh)]
        if not rows:
            rows = [header]
        elif "reasoning_tokens" not in rows[0]:
            idx = rows[0].index("costo_usd") if "costo_usd" in rows[0] else len(rows[0])
            rows[0].insert(idx, "reasoning_tokens")
            for r in rows[1:]:
                r.insert(idx, "")
        fecha = __import__("datetime").date.today().isoformat()
        rows.append([
            fecha, ASSISTANT_MODEL, f"classify: {pregunta[:80]}", "",
            str(len((CLASSIFY_PROMPT + pregunta).encode("utf-8"))),
            "1", "n/a", tokens_in, tokens_out, reasoning, "pendiente Billing",
        ])
        with open(path, "w", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerows(rows)
    except Exception:
        pass


def _guardar_fallo_clasificador(cuerpo: str) -> str:
    digest = hashlib.sha256(cuerpo.encode("utf-8")).hexdigest()[:16]
    path = os.path.join(_fail_dir(), f"{digest}.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(cuerpo[:500])
    return path


def _llamar_modelo(pregunta: str) -> dict:
    """Una llamada a la Responses API; devuelve el dict de intención."""
    import requests

    from app import segmentation as seg

    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError(
            "Falta MODEL_API_KEY en el entorno (se acepta META_API_KEY): "
            "define la variable antes de clasificar"
        )
    seg._check_daily_quota()
    seg._increment_daily_count()
    payload = _build_classify_payload(pregunta)
    headers = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}
    try:
        resp = requests.post(
            ASSISTANT_ENDPOINT, json=payload, headers=headers, timeout=ASSISTANT_TIMEOUT_S
        )
    except Exception as exc:
        raise RuntimeError("Error de red clasificando la intención: " + str(exc)[:200]) from exc
    if resp.status_code < 200 or resp.status_code >= 300:
        raise RuntimeError(f"Clasificador devolvió HTTP {resp.status_code}")
    try:
        body = resp.json()
    except Exception:
        body = {}
    texto = _extract_output_text(body) if isinstance(body, dict) else ""
    if not (texto or "").strip():
        texto = resp.text or ""
    if isinstance(body, dict) and isinstance(body.get("usage"), dict):
        _log_classifier_usage(pregunta, body["usage"])
    try:
        data = _extraer_json_modelo(texto)
    except ValueError:
        _guardar_fallo_clasificador(texto)
        raise
    intenc = data.get("intencion")
    if intenc not in INTENCIONES_VALIDAS:
        raise ValueError(f"Intención desconocida: {intenc!r}")
    params = data.get("parametros")
    if not isinstance(params, dict):
        params = {}
    return {"intencion": intenc, "parametros": params}


def _mes_param(params: dict) -> str | None:
    mes = params.get("mes")
    if mes is None:
        return None
    texto = str(mes).strip()
    if not texto or texto.lower() == "null":
        return None
    if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", texto):
        return None
    return texto


def _componer(clasif: dict, session) -> dict:
    intenc = clasif["intencion"]
    params = clasif.get("parametros") or {}
    if intenc == "total_mes":
        mes = str(params.get("mes") or "").strip() or "?"
        filas = {r["mes"]: r["total"] for r in qmod.total_por_mes(session)}
        cifra = int(filas.get(mes, 0))
        return {
            "respuesta": f"Total de {mes}: ${cifra:,} (dato de tu base).",
            "cifra": cifra,
            "fuente": "sql",
        }
    if intenc == "total_categoria":
        cat = str(params.get("categoria") or "").strip().lower() or "otros"
        if cat not in CATEGORIAS_FIJAS:
            cat = "otros"
        mes = _mes_param(params)
        filas = {
            r["categoria"]: r["total"]
            for r in qmod.total_por_categoria(session, mes=mes)
        }
        cifra = int(filas.get(cat, 0))
        detalle = f" en {cat} en {mes}" if mes else f" en {cat}"
        return {
            "respuesta": f"Total{detalle}: ${cifra:,} (dato de tu base).",
            "cifra": cifra,
            "fuente": "sql",
        }
    if intenc == "total_proveedor":
        prov = str(params.get("proveedor") or "").strip()
        mes = _mes_param(params)
        cifra = int(qmod.total_por_proveedor(session, prov, mes=mes)) if prov else 0
        detalle = f" en {mes}" if mes else ""
        return {
            "respuesta": f"Total con {prov or '?'}{detalle}: ${cifra:,} (dato de tu base).",
            "cifra": cifra,
            "fuente": "sql",
        }
    n = params.get("n", 5)
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 5
    filas = qmod.ultimas(session, n=n)
    if not filas:
        texto = "No hay facturas guardadas (dato de tu base)."
    else:
        partes = [
            f"#{f.id} {f.proveedor or '?'} ${int(f.total or 0):,}" for f in filas
        ]
        texto = "Últimas facturas (dato de tu base): " + "; ".join(partes) + "."
    return {"respuesta": texto, "cifra": None, "fuente": "sql"}


def responder(pregunta: str, session) -> dict:
    """Responde con cifra de SQL o ayuda. Solo llama al modelo con intención clara."""
    norm = normalizar(pregunta)
    if not norm:
        return {"respuesta": AYUDA_TEXTO, "cifra": None, "fuente": "ayuda"}
    path = _cache_path(norm)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    if not tiene_intencion_clara(norm):
        out = {"respuesta": AYUDA_TEXTO, "cifra": None, "fuente": "ayuda"}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False)
        return out
    clasif = _llamar_modelo(pregunta)
    out = _componer(clasif, session)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    return out
