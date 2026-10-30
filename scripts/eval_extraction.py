"""Eval de extracción Día 2: precisión por campo sobre fixtures.

Modo --offline: valida cada ``fixtures/*.expected.json`` contra el contrato
(sin llamar a la API) y emite la tabla a ``reports/precision.md``.
Sin --offline (requiere MODEL_API_KEY): extraería con extract_invoice y
compararía campo a campo.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

FIELDS = ["proveedor", "nit", "fecha", "items", "subtotal", "iva", "total",
          "categoria_sugerida", "confianza"]
CATEGORIES = {"papeleria", "transporte", "servicios", "alimentacion", "salud", "otros"}


def validate_contract(data: dict) -> list[str]:
    errors = []
    for f in FIELDS:
        if f not in data:
            errors.append(f"falta campo {f}")
    if "categoria_sugerida" in data and data["categoria_sugerida"] not in CATEGORIES:
        errors.append(f"categoria inválida: {data.get('categoria_sugerida')!r}")
    items = data.get("items")
    if items is not None and not isinstance(items, list):
        errors.append("items debe ser lista")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", default="fixtures")
    ap.add_argument("--report", default=os.path.join("reports", "precision.md"))
    ap.add_argument("--offline", action="store_true",
                    help="valida los expected contra el contrato sin llamar a la API")
    args = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(args.fixtures, "*.expected.json")))
    rows = []
    for path in paths:
        name = os.path.basename(path)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            rows.append((name, {f: "error" for f in FIELDS}, f"no JSON: {exc}"))
            continue
        if args.offline:
            errors = validate_contract(data)
            status = {f: ("ok" if f not in " ".join(errors) else "revisar") for f in FIELDS}
            note = "; ".join(errors) if errors else "contrato válido (offline, sin API)"
            rows.append((name, status, note))
        else:
            # Requiere API: importar aquí para no exigir deps en offline.
            sys.path.insert(0, os.path.join("backend"))
            from app.extraction import extract_invoice  # noqa: E402
            from app import segmentation as seg  # noqa: E402
            raw = seg.load_image_bytes(path.replace(".expected.json", ""))
            out = extract_invoice(raw, name)
            status = {f: ("ok" if out.get(f) == data.get(f) else "difiere") for f in FIELDS}
            rows.append((name, status, f"cache_hit={out.get('cache_hit')}"))

    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as fh:
        fh.write("# Precisión de extracción por campo\n\n")
        fh.write("| Fixture | " + " | ".join(FIELDS) + " | Nota |\n")
        fh.write("|---" * (len(FIELDS) + 2) + "|\n")
        for name, status, note in rows:
            fh.write("| " + name + " | " + " | ".join(status[f] for f in FIELDS) + f" | {note} |\n")
        if not rows:
            fh.write("\nSin fixtures `*.expected.json`.\n")
    print(f"reporte: {args.report} ({len(rows)} fixtures)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
