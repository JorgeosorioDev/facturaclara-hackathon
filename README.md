# FacturaClara — hackathon extract (new work Oct 27 – Nov 4 only)

Pre-existing before Oct 27: kickoff scaffolding only; everything in this repo (scan pipeline, extraction, assistant, frontend, evals) is new work from Oct 27 – Nov 4.

## Quick path

1. Copy env: `cp .env.example .env` and set `MODEL_API_KEY` (Meta Model API key).
2. Run: `docker compose up --build`
3. Scan an invoice:
   ```bash
   curl -X POST http://localhost:18001/scan \
     -F "file=@fixtures/factura_mesa.jpg"
   ```
4. Verify: `python scripts/eval_extraction.py --offline` (contract check, no API calls).

## Meta models used

| Task | Model | Via | File |
|------|-------|-----|------|
| Document segmentation (mask + crop) | SAM 3.1 (`sam-3.1`) | Meta Model API | `backend/app/segmentation.py` |
| Field extraction + assistant intents | Muse Spark (`muse-spark-1.3`) | Meta Model API | `backend/app/extraction.py`, `backend/app/assistant.py` |

## Architecture

```
image/PDF -> POST /scan -> SAM 3.1 segment + OpenCV crop
           -> Muse Spark extract (fixed JSON schema)
           -> DIAN validation rules (alerts, non-blocking)
           -> SQLite/Postgres CRUD + assistant (closed intents, SQL-backed figures)
```

Frontend (Next.js, `frontend/`): upload -> review -> invoices dashboard with assistant chat. UI in es-CO Spanish; code and comments in English.

## Honest accuracy

| Eval | Result |
|------|--------|
| Assistant (13 scripted questions, SQL-backed) | 13/13 |
| Extraction (3 fixtures x 5 semantic fields) | 10/15 (67%) |

Known extraction gaps: model rounds `4033.57` to `4033` on the PNG render of the same invoice that scores exact as PDF; `iva` expecteds were corrected to `null` (no IVA line on the documents, contract says `null`). See `scripts/eval_extraction.py`.

## Scope

In scope: `backend/`, `frontend/`, `fixtures/`, `scripts/`, `docker-compose.yml`, `.env.example`.
Out of scope (never published): `.env`, `facturas.db`, `uploads/`, `cache/`, `debug/`, `.next/`, `node_modules/`, internal notes.

Privacy note: `fixtures/factura_mesa.jpg` shows a real residential-complex bill; its `.expected.json` anonymizes the provider name. The NIT also appears in backend tests. `invoice.png` / `Factura-FV-2-4.pdf` are the author's own company invoice (VEFLAT SAS).

## Checklist

- [ ] `docker compose up --build` serves API on :18001 and frontend on :3001
- [ ] `curl POST /scan` returns `factura` + `alertas` JSON
- [ ] No secrets in the tree (`grep -ri 'META_API_KEY\|BASETEN_API_KEY\|gho_' .` is clean apart from code referencing env var names)

## License

MIT.
