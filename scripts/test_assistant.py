"""Corre las 10 preguntas de fixtures/preguntas.json contra la API.

Por defecto REQUIERE confirmación (--si) antes de llamar a la API,
porque cada pregunta con intención clara consume 1 llamada al modelo.
No ejecutar sin autorización del autor (presupuesto $150).

Uso:
  python scripts/test_assistant.py --offline   # valida el JSON sin red
  python scripts/test_assistant.py --si --base-url http://localhost:8000
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "preguntas.json"
SEED = ROOT / "fixtures" / "seed_facturas.json"

INTENCIONES = {
    "total_mes",
    "total_categoria",
    "total_proveedor",
    "ultimas_facturas",
    "fuera_de_alcance",
}


def validar_offline() -> int:
    import datetime as dt
    import tempfile
    import os

    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 10, "se esperan 10 preguntas"
    ids = set()
    for item in data:
        assert set(("id", "pregunta", "intencion_esperada", "respuesta_esperada", "notas")) <= set(item), item
        assert item["id"] not in ids, f"id duplicado: {item['id']}"
        ids.add(item["id"])
        assert isinstance(item["pregunta"], str) and item["pregunta"].strip(), item
        assert item["intencion_esperada"] in INTENCIONES, item
        assert isinstance(item["respuesta_esperada"], dict), "respuesta_esperada la escribe el autor a mano"
        assert isinstance(item["notas"], str) and item["notas"].strip(), item
    print(f"offline OK: {len(data)} preguntas válidas en {FIXTURE}")

    # Aritmética seed vs esperado, sin red (igual que antes).
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    assert isinstance(seed, list) and len(seed) == 9, "se esperan 9 facturas seed"
    por_id = {f["id"]: f for f in seed}
    assert sorted(por_id) == list(range(1, 10)), "ids seed deben ser 1-9"
    for f in seed:
        assert f["nit"] is None and f["iva"] == 0, f
        assert len(f["items"]) == 1 and f["items"][0]["precio_unitario"] == f["total"], f
    mes = {}
    cat: dict[str, int] = {}
    prov: dict[str, int] = {}
    for f in seed:
        mes[f["fecha"][:7]] = mes.get(f["fecha"][:7], 0) + f["total"]
        cat[f["categoria"]] = cat.get(f["categoria"], 0) + f["total"]
        prov[f["proveedor"]] = prov.get(f["proveedor"], 0) + f["total"]
    ult3 = sorted(por_id, reverse=True)[:3]
    ult5 = sorted(por_id, reverse=True)[:5]
    esperado = {i["id"]: i["respuesta_esperada"] for i in data}
    checks = [
        (1, mes.get("2026-10"), esperado[1].get("cifra")),
        (2, mes.get("2026-09"), esperado[2].get("cifra")),
        (3, cat.get("transporte"), esperado[3].get("cifra")),
        (4, cat.get("papeleria"), esperado[4].get("cifra")),
        (5, prov.get("Proveedor A"), esperado[5].get("cifra")),
        (6, prov.get("Proveedor B"), esperado[6].get("cifra")),
    ]
    for qid, calc, esp in checks:
        assert calc == esp, f"Q{qid}: seed={calc} esperado={esp}"
        print(f"  Q{qid} aritmética OK: {calc}")
    assert esperado[7].get("ids") == ult3, f"Q7: {ult3}"
    assert esperado[8].get("ids") == ult5, f"Q8: {ult5}"
    print(f"  Q7 ids OK: {ult3}  Q8 ids OK: {ult5}")
    for qid in (9, 10):
        assert esperado[qid].get("fuente") == "ayuda" and esperado[qid].get("cifra") is None, qid
    print("  Q9/Q10 ayuda OK (sin modelo)")

    # Fase 2: seed en SQLite TEMPORAL aislada + queries.py, sin modelo.
    # Nunca tocar backend/facturas.db ni la DB de la app.
    assert "facturas.db" not in os.environ.get("DATABASE_URL", ""), "DATABASE_URL apunta a facturas.db"
    sys.path.insert(0, str(ROOT / "backend"))
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import Base, Factura, Item
    from app import queries as qmod
    from app import assistant as amod

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_path = tmp.name
    tmp.close()
    assert "facturas.db" not in tmp_path, tmp_path
    try:
        eng = create_engine(f"sqlite:///{tmp_path}")
        Base.metadata.create_all(bind=eng)
        S = sessionmaker(bind=eng, expire_on_commit=False)
        with S() as sess:
            for f in seed:
                row = Factura(
                    id=f["id"],
                    proveedor=f["proveedor"],
                    nit_normalizado=f.get("nit"),
                    fecha=dt.date.fromisoformat(f["fecha"]),
                    subtotal=f["total"],
                    iva=f.get("iva", 0),
                    total=f["total"],
                    categoria=f["categoria"],
                )
                for it in f.get("items", []):
                    row.items.append(
                        Item(
                            descripcion=it.get("descripcion"),
                            cantidad=it.get("cantidad", 1),
                            precio_unitario=it.get("precio_unitario"),
                        )
                    )
                sess.merge(row)
            sess.commit()
        print(f"seed temporal OK: {len(seed)} facturas en {tmp_path}")

        # Mock que revienta si algo llama al clasificador (modelo).
        def _boom(_pregunta: str):  # pragma: no cover
            raise AssertionError("clasificador llamado en --offline")

        amod._llamar_modelo = _boom  # type: ignore[attr-defined]

        # Clasificador simulado determinista (sin modelo): params por id.
        PARAMS = {
            1: {"intencion": "total_mes", "parametros": {"mes": "2026-10"}},
            2: {"intencion": "total_mes", "parametros": {"mes": "2026-09"}},
            3: {"intencion": "total_categoria", "parametros": {"categoria": "transporte"}},
            4: {"intencion": "total_categoria", "parametros": {"categoria": "papeleria"}},
            5: {"intencion": "total_proveedor", "parametros": {"proveedor": "Proveedor A"}},
            6: {"intencion": "total_proveedor", "parametros": {"proveedor": "Proveedor B"}},
            7: {"intencion": "ultimas_facturas", "parametros": {"n": 3}},
            8: {"intencion": "ultimas_facturas", "parametros": {}},
        }
        fallas = 0
        with S() as sess:
            for item in data:
                qid = item["id"]
                esp = item.get("respuesta_esperada") or {}
                try:
                    if qid in (9, 10):
                        norm = amod.normalizar(item["pregunta"])
                        assert not amod.tiene_intencion_clara(norm), f"Q{qid} tiene pista inesperada"
                        # responder() con mock _boom: debe devolver ayuda sin llamar al modelo.
                        # Evita ensuciar el caché real redirigiéndolo al tempdir.
                        orig_cache = amod._cache_path
                        amod._cache_path = lambda _n, _t=tmp_path: _t + f".ask{qid}.json"  # type: ignore[assignment]
                        try:
                            got = amod.responder(item["pregunta"], sess)
                        finally:
                            amod._cache_path = orig_cache
                        assert got.get("fuente") == "ayuda" and got.get("cifra") is None, got
                        assert esp.get("fuente") == "ayuda", esp
                    elif item["intencion_esperada"] == "ultimas_facturas":
                        got_ids = [f.id for f in qmod.ultimas(sess, n=PARAMS[qid]["parametros"].get("n", 5))]
                        assert got_ids == esp.get("ids"), f"ids={got_ids} esperado={esp.get('ids')}"
                        out = amod._componer(PARAMS[qid], sess)
                        assert out.get("fuente") == "sql", out
                    else:
                        out = amod._componer(PARAMS[qid], sess)
                        assert out.get("fuente") == esp.get("fuente") == "sql", out
                        assert out.get("cifra") == esp.get("cifra"), f"cifra={out.get('cifra')} esperado={esp.get('cifra')}"
                    print(f"Q{qid}: PASA")
                except AssertionError as exc:
                    fallas += 1
                    print(f"Q{qid}: FALLA ({exc})")
        print(f"offline queries: {10 - fallas}/10 PASA")
        return 1 if fallas else 0
    finally:
        try:
            eng.dispose()
        except Exception:
            pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def cargar_seed_en_db(db_url: str | None = None) -> None:
    """Carga fixtures/seed_facturas.json en SQLite (temporal o la DB que use).

    Solo se llama desde el flujo con --si (con red local). Nunca en --offline.
    """
    import datetime as dt
    import os
    import sys

    sys.path.insert(0, str(ROOT / "backend"))
    os.environ.setdefault("DATABASE_URL", db_url or os.environ.get("DATABASE_URL", "sqlite:///:memory:"))
    from app import db as dbmod
    from app.models import Factura, Item

    seed = json.loads(SEED.read_text(encoding="utf-8"))
    dbmod.init_db()
    with dbmod.SessionLocal() as sess:
        sess.query(Item).delete()
        sess.query(Factura).delete()
        for f in seed:
            row = Factura(
                id=f["id"],
                proveedor=f["proveedor"],
                nit_normalizado=f.get("nit"),
                fecha=dt.date.fromisoformat(f["fecha"]),
                subtotal=f["total"],
                iva=f.get("iva", 0),
                total=f["total"],
                categoria=f["categoria"],
            )
            for it in f.get("items", []):
                row.items.append(
                    Item(
                        descripcion=it.get("descripcion"),
                        cantidad=it.get("cantidad", 1),
                        precio_unitario=it.get("precio_unitario"),
                    )
                )
            sess.merge(row)
        sess.commit()
    print(f"seed OK: {len(seed)} facturas en {os.environ.get('DATABASE_URL')}")


def correr_api(base_url: str) -> int:
    import urllib.request

    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ok = 0
    for item in data:
        cuerpo = json.dumps({"pregunta": item["pregunta"]}).encode("utf-8")
        req = urllib.request.Request(
            base_url.rstrip("/") + "/assistant",
            data=cuerpo,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        esp = item.get("respuesta_esperada") or {}
        marca = ""
        if item["intencion_esperada"] == "ultimas_facturas" and esp.get("ids") is not None:
            marca = f" esperado_ids={esp['ids']}"
        elif "cifra" in esp and esp.get("fuente") == "sql":
            marca = f" esperado_cifra={esp['cifra']}" + (" OK" if out.get("cifra") == esp["cifra"] else " DIFIERE")
        elif esp.get("fuente") == "ayuda":
            marca = " esperado_fuente=ayuda" + (" OK" if out.get("fuente") == "ayuda" else " DIFIERE")
        print(f"[{item['id']}] {item['pregunta']}\n  -> {out.get('respuesta')} (fuente={out.get('fuente')}){marca}")
        ok += 1
    print(f"API OK: {ok}/10 respondidas")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="valida el JSON sin red")
    ap.add_argument("--si", action="store_true", help="confirmo gastar llamadas al modelo")
    ap.add_argument("--base-url", default="http://localhost:8000")
    args = ap.parse_args(argv)
    if args.offline:
        return validar_offline()
    if not args.si:
        print("Requiere confirmación: pasa --si para llamar a la API (gasta llamadas al modelo).")
        print("Sin red: usa --offline.")
        return 2
    return correr_api(args.base_url)


if __name__ == "__main__":
    sys.exit(main())
