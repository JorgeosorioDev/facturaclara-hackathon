# Precisión de extracción por campo — medición REAL (2026-10-29)

Modo REAL con Muse Spark 1.3 (`scripts/eval_extraction.py` sin `--offline`).
3 fixtures con imagen, 3 llamadas API (todas `cache_hit=False`; la caché
anterior `ext_07de…` del 10-28 quedó invalidada por cambio de `PROMPT_VERSION`).

> Nada es 100%: el total semántico es **10/15 ≈ 67%**.

## Tabla honesta por campo (NIT / proveedor / fecha / IVA / total)

Criterio semántico: ✓ = valor correcto aunque difiera el formato (p. ej. NIT
con/sin DV); ✗ = valor incorrecto o que no coincide con el expected.

| Fixture | proveedor | NIT | fecha | IVA | total | Aciertos |
|---|---|---|---|---|---|---|
| Factura-FV-2-4.pdf | ✓ VEFLAT SAS | ✓ 901475872-2 | ✓ 2026-10-16 | ✗ (expected 0, modelo null) | ✓ 4033.57 | 4/5 |
| factura_mesa.jpg | ✗ (expected anonimizado a propósito) | ✓ (mismo NIT; modelo devuelve con DV `900055719-8`) | ✓ 2026-09-01 | ✗ (expected 0, modelo null) | ✓ 413580 | 3/5 |
| invoice.png | ✓ VEFLAT SAS | ✓ (mismo NIT; expected sin DV, modelo con DV) | ✓ 2026-10-16 | ✗ (expected 0, modelo null) | ✗ (modelo redondeó 4033.57 → 4033) | 3/5 |
| **Total** | | | | | | **10/15 ≈ 67%** |

Lectura honesta de los 5 fallos:
- **IVA (3×): el fallo está en los expected, no en el modelo.** Ningún
  documento muestra línea de IVA; el contrato ordena `null` si el campo no
  aparece, y el modelo devolvió `null`. Los expected asumieron `0`.
  Acción: corregir los expected a `iva: null`.
- **proveedor factura_mesa (1×): anonimización intencional**, no error del
  modelo (devolvió el nombre real legible).
- **total invoice.png (1×): error REAL del modelo** — redondeó 4033.57 a 4033
  (y también subtotal e items). El mismo documento vía PDF sí salió exacto
  (4033.57). Inconsistencia del modelo entre renderizados.

## Tabla estricta exacta (salida del script, igualdad `==` por campo)

Incluye `items`, `subtotal`, `categoria_sugerida` y `confianza` con igualdad
exacta (la confianza flotante casi siempre difiere: no es un fallo útil).

| Fixture | proveedor | nit | fecha | items | subtotal | iva | total | categoria_sugerida | confianza | Nota |
|---|---|---|---|---|---|---|---|---|---|---|
| Factura-FV-2-4.pdf.expected.json | ok | ok | ok | ok | ok | difiere | ok | ok | difiere | cache_hit=False |
| factura_mesa.jpg.expected.json | difiere | difiere | ok | difiere | difiere | difiere | ok | ok | difiere | cache_hit=False |
| invoice.png.expected.json | ok | difiere | ok | difiere | difiere | difiere | difiere | difiere | difiere | cache_hit=False |

Discrepancias known en los expected (a corregir, no son fallos de medición):
- `factura_mesa`: items dice `CUOTA EXTRA`, la imagen dice `CUOTA EXTRA 6/12`;
  `subtotal: 413580` cuando la imagen no muestra subtotal (debería ser null).
- `invoice.png`: `nit` sin DV (`901475872`, la imagen muestra `901.475.872-2`),
  `categoria: transporte` para un servicio de software (debería ser servicios).

## Fixtures (3)

- `fixtures/factura_mesa.jpg` (+ `.expected.json`): cuenta de cobro conjunto
  residencial, COP, 2026-09-01, total 413580. Proveedor anonimizado en el
  expected; NIT real ya público en tests. Moneda COP (dentro del contrato).
- `fixtures/invoice.png` (+ `.expected.json`): VEFLAT SAS FVEF 4, fecha
  2026-10-16, total 4033.57 **USD — fuera del contrato COP**.
- `fixtures/Factura-FV-2-4.pdf` (+ `.expected.json` NUEVO, creado a mano esta
  sesión): mismo documento que `invoice.png` (FVEF 4, VEFLAT → XQUADRA USA INC,
  4033.57 **USD — fuera del contrato COP**). NIT con DV tal como impreso.

## Corrección 2026-10-29 (expected corregidos, misma medición REAL del 10-29)

Se corrigieron los 3 `.expected.json` (sin re-correr el modelo):
- Los 3: `iva: 0 → null` (contrato: `null` si no hay línea IVA; el modelo
  había devuelto `null` en los 3, así que ahora cuentan como acierto).
- `factura_mesa.jpg`: `items[1].descripcion` → `CUOTA EXTRA 6/12` (como en la
  imagen); `subtotal: 413580 → null` (la imagen no muestra subtotal).
  Proveedor anonimizado + `nota_anonimizacion` se mantienen (privacidad).
- `invoice.png`: `nit` → `901475872-2` (DV tal como impreso `901.475.872-2`);
  `categoria_sugerida` → `servicios`. Total se mantiene en `4033.57`.

### Tabla semántica honesta (misma medición, expected corregidos)

Criterio: IVA `null` = acierto si el modelo dio `null`; proveedor anonimizado
de `factura_mesa` = conocido-no-error (no fallo del modelo), contado como
acierto con nota.

| Fixture | proveedor | NIT | fecha | IVA | total | Aciertos |
|---|---|---|---|---|---|---|
| Factura-FV-2-4.pdf | ✓ VEFLAT SAS | ✓ 901475872-2 | ✓ 2026-10-16 | ✓ null (sin línea IVA) | ✓ 4033.57 | 5/5 |
| factura_mesa.jpg | ✓* anonimizado a propósito (modelo dio el real) | ✓ (mismo NIT; modelo con DV `900055719-8`) | ✓ 2026-09-01 | ✓ null (sin línea IVA) | ✓ 413580 | 5/5* |
| invoice.png | ✓ VEFLAT SAS | ✓ 901475872-2 | ✓ 2026-10-16 | ✓ null (sin línea IVA) | ✗ (modelo redondeó 4033.57 → 4033) | 4/5 |
| **Total honesto** | | | | | | **14/15 ≈ 93%** |

Cálculo explícito: medición original 10/15 + 3 IVA (fallo de expected, no del
modelo) = 13/15 + 1 proveedor anonimizado (exclusión intencional por
privacidad, contado como conocido-no-error) = **14/15**. Alternativa
estricta sin ese ajuste: **13/15 ≈ 87%**. En ambos conteos el único error
REAL del modelo es el total de `invoice.png` (redondeo 4033.57 → 4033).
