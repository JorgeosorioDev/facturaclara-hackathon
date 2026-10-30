from __future__ import annotations

import base64
import datetime as dt
import uuid
from pathlib import Path
from typing import Any

import cv2
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app import db as dbmod
from app import extraction as extmod
from app import queries as qmod
from app import segmentation as segmod
from app.assistant import responder as responder_asistente
from app.models import Factura, Item
from app.validation import Alerta, validar_factura

app = FastAPI(title="FacturaClara API")

SCAN_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "application/pdf",
}
SCAN_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf"}


def _get_db():
    yield from dbmod.get_db()


def _alerta_dict(a: Alerta) -> dict:
    return {
        "campo": a.campo,
        "regla": a.regla,
        "mensaje": a.mensaje,
        "severidad": a.severidad,
    }


def _parse_fecha(v: Any):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, dt.date) and not isinstance(v, dt.datetime):
        return v
    try:
        return dt.date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        return None


def _num_or_none(v: Any):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    return None


def _norm_nit(v: Any):
    if v is None or str(v).strip() == "":
        return None
    return str(v).strip().replace(".", "").replace(" ", "")


def _factura_dict(f: Factura) -> dict:
    return {
        "id": f.id,
        "proveedor": f.proveedor,
        "nit": f.nit_normalizado,
        "nit_normalizado": f.nit_normalizado,
        "fecha": f.fecha.isoformat() if f.fecha else None,
        "subtotal": f.subtotal,
        "iva": f.iva,
        "total": f.total,
        "categoria": f.categoria,
        "categoria_sugerida": f.categoria,
        "confianza": f.confianza,
        "imagen_hash": f.imagen_hash,
        "items": [
            {
                "id": it.id,
                "descripcion": it.descripcion,
                "cantidad": it.cantidad,
                "precio_unitario": it.precio_unitario,
                "total": it.total,
            }
            for it in (f.items or [])
        ],
    }


def _payload_para_validar(row: dict) -> dict:
    d = dict(row)
    d["nit"] = row.get("nit", row.get("nit_normalizado"))
    return d


def _aplicar_payload(f: Factura, data: dict) -> None:
    f.proveedor = data.get("proveedor")
    f.nit_normalizado = _norm_nit(data.get("nit", data.get("nit_normalizado")))
    f.fecha = _parse_fecha(data.get("fecha"))
    f.subtotal = _num_or_none(data.get("subtotal"))
    f.iva = _num_or_none(data.get("iva"))
    f.total = _num_or_none(data.get("total"))
    cat = data.get("categoria", data.get("categoria_sugerida"))
    f.categoria = cat if isinstance(cat, str) else None
    conf = data.get("confianza")
    f.confianza = float(conf) if isinstance(conf, (int, float)) and not isinstance(conf, bool) else None
    ih = data.get("imagen_hash")
    f.imagen_hash = str(ih) if ih is not None else None


def _aplicar_items(f: Factura, data: dict) -> None:
    f.items.clear()
    items = data.get("items")
    if not isinstance(items, list):
        return
    for it in items:
        if not isinstance(it, dict):
            continue
        precio = it.get("precio_unitario", it.get("precio"))
        f.items.append(
            Item(
                descripcion=it.get("descripcion"),
                cantidad=_num_or_none(it.get("cantidad")),
                precio_unitario=_num_or_none(precio),
                total=_num_or_none(it.get("total")),
            )
        )


@app.on_event("startup")
def _startup() -> None:
    dbmod.init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/scan")
async def scan(file: UploadFile = File(...)) -> dict:
    """Flujo punta a punta: bytes -> segmentación -> extracción -> validación.

    Acepta imagen (JPG/PNG/WebP/GIF) o PDF. Usa el caché existente y la
    cuota diaria compartida de segmentación/extracción. No expone claves.
    """
    nombre = (file.filename or "").strip()
    ext = Path(nombre).suffix.lower()
    ctype = (file.content_type or "").split(";")[0].strip().lower()
    if ext not in SCAN_EXTENSIONS and ctype not in SCAN_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Tipo de archivo no válido: sube una imagen (JPG, PNG o WebP) o un PDF",
        )
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="El archivo está vacío")
    if segmod._is_pdf_bytes(bytes(content)) and not ext:
        ext = ".pdf"
    if ext == ".pdf" and not segmod._is_pdf_bytes(bytes(content)):
        raise HTTPException(
            status_code=400,
            detail="El archivo no es un PDF válido",
        )

    invoice_id = uuid.uuid4().hex[:12]
    try:
        seg = segmod.segment_document(bytes(content), invoice_id)
    except RuntimeError as exc:
        raise _error_modelo(exc)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo segmentar el documento: {exc}"[:300],
        )

    ok, buf = cv2.imencode(".png", seg.cropped)
    crop_bytes = bytes(buf.tobytes()) if ok else bytes(content)
    try:
        extraccion = extmod.extract_invoice(crop_bytes, invoice_id)
    except RuntimeError as exc:
        raise _error_modelo(exc)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo extraer la factura: {exc}"[:300],
        )

    factura = {k: v for k, v in dict(extraccion).items() if k != "cache_hit"}
    factura["id"] = invoice_id
    alertas = validar_factura(factura)
    return {
        "factura": factura,
        "alertas": [_alerta_dict(a) for a in alertas],
        "fallback": bool(seg.fallback),
        "confianza_segmentacion": float(seg.confidence),
        "crop_base64": base64.b64encode(crop_bytes).decode("ascii"),
    }


def _error_modelo(exc: Exception) -> HTTPException:
    """Mapea errores de modelo a HTTP con mensaje en español, sin claves."""
    msg = str(exc)[:300] or "Error del modelo"
    bajo = msg.lower()
    if "cuota" in bajo or "max_daily_calls" in bajo:
        return HTTPException(status_code=429, detail=msg)
    if "tiempo" in bajo or "timeout" in bajo:
        return HTTPException(status_code=504, detail=msg)
    return HTTPException(status_code=502, detail=msg)


@app.post("/invoices")
def crear_factura(data: dict, sess: Session = Depends(_get_db)) -> dict:
    alertas = validar_factura(_payload_para_validar(data))
    f = Factura()
    _aplicar_payload(f, data)
    _aplicar_items(f, data)
    sess.add(f)
    sess.commit()
    sess.refresh(f)
    return {
        "factura": _factura_dict(f),
        "alertas": [_alerta_dict(a) for a in alertas],
    }


@app.get("/invoices")
def listar_facturas(sess: Session = Depends(_get_db)) -> dict:
    rows = sess.query(Factura).order_by(Factura.id).all()
    return {"facturas": [_factura_dict(f) for f in rows]}


@app.get("/invoices/export.csv", response_class=PlainTextResponse)
def exportar_csv(sess: Session = Depends(_get_db)):
    header = "id,proveedor,nit,fecha,subtotal,iva,total,categoria"
    lineas = [header]
    for f in sess.query(Factura).order_by(Factura.id).all():
        fecha = f.fecha.isoformat() if f.fecha else ""
        prov = (f.proveedor or "").replace('"', '""')
        if "," in prov or '"' in prov:
            prov = f'"{prov}"'
        lineas.append(
            ",".join(
                [
                    str(f.id),
                    prov,
                    f.nit_normalizado or "",
                    fecha,
                    "" if f.subtotal is None else str(int(f.subtotal)),
                    "" if f.iva is None else str(int(f.iva)),
                    "" if f.total is None else str(int(f.total)),
                    f.categoria or "",
                ]
            )
        )
    return PlainTextResponse(
        "\n".join(lineas) + "\n", media_type="text/csv; charset=utf-8"
    )


@app.get("/invoices/{factura_id}")
def obtener_factura(factura_id: int, sess: Session = Depends(_get_db)) -> dict:
    f = sess.get(Factura, factura_id)
    if f is None:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    alertas = validar_factura(
        {
            "proveedor": f.proveedor,
            "nit": f.nit_normalizado,
            "fecha": f.fecha.isoformat() if f.fecha else None,
            "subtotal": f.subtotal,
            "iva": f.iva,
            "total": f.total,
            "items": [
                {
                    "descripcion": it.descripcion,
                    "cantidad": it.cantidad,
                    "precio_unitario": it.precio_unitario,
                    "total": it.total,
                }
                for it in (f.items or [])
            ],
        }
    )
    return {
        "factura": _factura_dict(f),
        "alertas": [_alerta_dict(a) for a in alertas],
    }


@app.get("/reports/total")
def reporte_total(group_by: str, q: str | None = None, sess: Session = Depends(_get_db)):
    if group_by == "mes":
        return {"group_by": "mes", "rows": qmod.total_por_mes(sess)}
    if group_by == "categoria":
        return {"group_by": "categoria", "rows": qmod.total_por_categoria(sess)}
    if group_by == "proveedor":
        if q is None or not q.strip():
            raise HTTPException(
                status_code=400,
                detail="group_by=proveedor requiere el parámetro q",
            )
        return {
            "group_by": "proveedor",
            "proveedor": q,
            "total": int(qmod.total_por_proveedor(sess, q)),
        }
    raise HTTPException(
        status_code=400,
        detail="group_by inválido: usa mes, categoria o proveedor",
    )


@app.post("/assistant")
def assistant(data: dict, sess: Session = Depends(_get_db)) -> dict:
    pregunta = data.get("pregunta", "") if isinstance(data, dict) else ""
    if not isinstance(pregunta, str) or not pregunta.strip():
        raise HTTPException(status_code=400, detail="pregunta es requerida")
    return responder_asistente(pregunta, sess)


@app.put("/invoices/{factura_id}")
def actualizar_factura(
    factura_id: int, data: dict, sess: Session = Depends(_get_db)
) -> dict:
    f = sess.get(Factura, factura_id)
    if f is None:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    alertas = validar_factura(_payload_para_validar(data))
    _aplicar_payload(f, data)
    _aplicar_items(f, data)
    sess.commit()
    sess.refresh(f)
    return {
        "factura": _factura_dict(f),
        "alertas": [_alerta_dict(a) for a in alertas],
    }
