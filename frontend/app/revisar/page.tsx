"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  OctagonAlert,
  Save,
} from "lucide-react";
import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { Input } from "../../components/ui/Input";
import { Skeleton } from "../../components/ui/Skeleton";
import { API_URL, CATEGORIAS, formatoCOP, formatoFecha, type Alerta } from "../../lib/api";

type Form = {
  proveedor: string;
  nit: string;
  fecha: string;
  total: string;
  categoria: string;
};

type ScanFactura = {
  proveedor?: string | null;
  nit?: string | null;
  fecha?: string | null;
  subtotal?: number | null;
  iva?: number | null;
  total?: number | null;
  categoria?: string | null;
  categoria_sugerida?: string | null;
  confianza?: number | null;
};

type ScanResult = {
  factura?: ScanFactura | null;
  alertas?: Alerta[];
  fallback?: boolean;
  confianza_segmentacion?: number | null;
  crop_base64?: string | null;
};

function str(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return "";
  return String(v);
}

const EJEMPLO: Form = {
  proveedor: "Papelería Central",
  nit: "900123456-7",
  fecha: "2026-10-15",
  total: "1250000",
  categoria: "oficina",
};

function validarLocal(f: Form): Alerta[] {
  const alertas: Alerta[] = [];
  if (!f.proveedor.trim())
    alertas.push({ campo: "proveedor", regla: "obligatorio", mensaje: "Falta el proveedor.", severidad: "error" });
  if (!f.nit.trim())
    alertas.push({ campo: "nit", regla: "obligatorio", mensaje: "Falta el NIT.", severidad: "error" });
  if (!f.fecha.trim())
    alertas.push({ campo: "fecha", regla: "obligatorio", mensaje: "Falta la fecha.", severidad: "error" });
  if (!f.total.trim() || Number.isNaN(Number(f.total)))
    alertas.push({ campo: "total", regla: "obligatorio", mensaje: "El total no es un número válido.", severidad: "error" });
  return alertas;
}

export default function RevisarPage() {
  const router = useRouter();
  const [fase, setFase] = useState<"cargando" | "lista" | "error" | "vacia">("cargando");
  const [preview, setPreview] = useState<string | null>(null);
  const [bajaCalidad, setBajaCalidad] = useState(false);
  const [usarCompleta, setUsarCompleta] = useState(false);
  const [mostrarMascara, setMostrarMascara] = useState(true);
  const [form, setForm] = useState<Form>({ proveedor: "", nit: "", fecha: "", total: "", categoria: "otros" });
  const [errorMsg, setErrorMsg] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [confianza, setConfianza] = useState<number | null>(null);
  const [alertasBackend, setAlertasBackend] = useState<Alerta[]>([]);
  const [fallback, setFallback] = useState(false);
  const [crop, setCrop] = useState<string | null>(null);

  function hidratarDesdeSesion(): boolean {
    try {
      const img = sessionStorage.getItem("facturaclara:preview");
      if (!img) {
        setFase("vacia");
        return false;
      }
      setPreview(img);
      setBajaCalidad(sessionStorage.getItem("facturaclara:bajaCalidad") === "1");
      const raw = sessionStorage.getItem("facturaclara:scan");
      if (raw) {
        const scan: ScanResult = JSON.parse(raw);
        const f = scan.factura ?? {};
        const cat = f.categoria_sugerida ?? f.categoria ?? "otros";
        setForm({
          proveedor: str(f.proveedor),
          nit: str(f.nit),
          fecha: str(f.fecha),
          total: f.total === null || f.total === undefined ? "" : String(f.total),
          categoria: CATEGORIAS.includes(cat ?? "") ? (cat as string) : "otros",
        });
        setAlertasBackend(Array.isArray(scan.alertas) ? scan.alertas : []);
        setFallback(Boolean(scan.fallback));
        if (typeof scan.confianza_segmentacion === "number") {
          setConfianza(scan.confianza_segmentacion);
        } else if (typeof f.confianza === "number") {
          setConfianza(f.confianza);
        }
        if (typeof scan.crop_base64 === "string" && scan.crop_base64.length > 0) {
          setCrop(`data:image/png;base64,${scan.crop_base64}`);
          setBajaCalidad((prev) => prev || Boolean(scan.fallback));
        }
      }
      setFase("lista");
      return true;
    } catch {
      setFase("error");
      setErrorMsg("No pudimos cargar el resultado del escaneo.");
      return false;
    }
  }

  useEffect(() => {
    const t = setTimeout(hidratarDesdeSesion, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const alertasLocales = useMemo(() => validarLocal(form), [form]);
  const alertas = useMemo(
    () => [...alertasBackend, ...alertasLocales],
    [alertasBackend, alertasLocales]
  );
  const errores = alertas.filter((a) => a.severidad === "error");
  const errorDe = (campo: keyof Form): string | undefined =>
    alertasLocales.find((a) => a.campo === campo)?.mensaje;
  const imagenVisible = usarCompleta ? preview : crop ?? preview;
  const alertaNit = alertas.find((a) => a.campo === "nit");
  const totalNum = form.total.trim() === "" ? null : Number(form.total);
  const totalVistaPrevia = formatoCOP(
    totalNum === null || Number.isNaN(totalNum) ? null : totalNum
  );
  const fechaVistaPrevia = formatoFecha(form.fecha.trim() || null);

  function setCampo(k: keyof Form, v: string) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function guardar() {
    if (guardando) return;
    setGuardando(true);
    setErrorMsg("");
    try {
      const res = await fetch(`${API_URL}/invoices`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          proveedor: form.proveedor || null,
          nit: form.nit || null,
          fecha: form.fecha || null,
          total: form.total === "" ? null : Number(form.total),
          categoria: form.categoria,
        }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        const detalle =
          data && typeof data.detail === "string" ? `: ${data.detail}` : "";
        const alertasResp = Array.isArray(data?.alertas) ? data.alertas : null;
        if (alertasResp) setAlertasBackend(alertasResp);
        throw new Error(`El backend devolvió HTTP ${res.status}${detalle}`);
      }
      if (Array.isArray(data?.alertas)) setAlertasBackend(data.alertas);
      sessionStorage.removeItem("facturaclara:preview");
      sessionStorage.removeItem("facturaclara:scan");
      sessionStorage.removeItem("facturaclara:bajaCalidad");
      router.push("/facturas");
    } catch (err) {
      setGuardando(false);
      setErrorMsg(
        err instanceof Error
          ? `No pudimos guardar la factura. ${err.message}`
          : "No pudimos guardar la factura. Revisa tu conexión."
      );
    }
  }

  if (fase === "cargando") {
    return (
      <div className="space-y-3">
        <Skeleton className="h-56 w-full" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-2/3" />
        <p aria-live="polite" className="flex items-center gap-2 text-sm font-medium text-zinc-300">
          <Loader2 size={16} className="animate-spin" />
          Leyendo la factura…
        </p>
      </div>
    );
  }

  if (fase === "vacia") {
    return (
      <Card className="space-y-3 text-center">
        <p className="font-semibold">Aún no tienes facturas. Toma la primera foto.</p>
        <Button onClick={() => router.push("/")}>Tomar foto</Button>
      </Card>
    );
  }

  if (fase === "error") {
    return (
      <Alert tone="error" className="items-center justify-between">
        <span>{errorMsg || "Ocurrió un error."}</span>
        <Button
          onClick={() => {
            setFase("cargando");
            setErrorMsg("");
            hidratarDesdeSesion();
          }}
        >
          Reintentar
        </Button>
      </Alert>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Revisa la factura</h1>
        <Badge className={confianza !== null && confianza >= 0.8 ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-300" : "border-amber-400/20 bg-amber-400/10 text-amber-300"}>
          {confianza !== null ? `Confianza ${Math.round(confianza * 100)}%` : "Confianza —"}
        </Badge>
      </div>

      {bajaCalidad && !usarCompleta && (
        <Alert tone="aviso">
          <AlertTriangle size={18} className="mt-0.5 shrink-0" />
          <span>
            Imagen de baja calidad. Puedes{" "}
            <button className="rounded font-semibold text-emerald-300 underline underline-offset-2 focus-visible:outline-2" onClick={() => setUsarCompleta(true)}>
              usar imagen completa
            </button>
            .
          </span>
        </Alert>
      )}

      {fallback && (
        <Alert tone="aviso">
          <AlertTriangle size={18} className="mt-0.5 shrink-0" />
          <span>
            El recorte automático falló y usamos la imagen completa
            (fallback del backend). Revisa los datos con cuidado.
          </span>
        </Alert>
      )}

      <div className="grid gap-5 md:grid-cols-2">
      <Card className="space-y-3">
        <div className="relative overflow-hidden rounded-xl border border-white/10 bg-zinc-950">
          {imagenVisible ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={imagenVisible} alt="Recorte de la factura escaneada" className="max-h-72 w-full object-contain" />
          ) : (
            <div className="flex h-48 items-center justify-center text-sm text-zinc-400">
              Sin imagen
            </div>
          )}
          {mostrarMascara && imagenVisible && (
            <div
              aria-hidden
              className="pointer-events-none absolute inset-6 rounded border-2 border-dashed border-emerald-400 bg-emerald-400/15"
            />
          )}
        </div>
        <label className="flex min-h-[44px] cursor-pointer items-center gap-2 text-sm font-medium text-zinc-300">
          <input
            type="checkbox"
            checked={mostrarMascara}
            onChange={(e) => setMostrarMascara(e.target.checked)}
            className="h-5 w-5 accent-emerald-500"
          />
          Mostrar máscara de recorte
        </label>
        {crop && preview && crop !== preview && (
          <button
            className="rounded text-sm font-semibold text-emerald-300 underline underline-offset-2 focus-visible:outline-2"
            onClick={() => setUsarCompleta((v) => !v)}
          >
            {usarCompleta ? "Ver recorte del backend" : "Ver imagen completa"}
          </button>
        )}
      </Card>

      <Card className="space-y-3">
        <div className="grid gap-3">
          <Input label="Proveedor" value={form.proveedor} onChange={(e) => setCampo("proveedor", e.target.value)} placeholder="Ej: Papelería Central" error={errorDe("proveedor")} />
          <Input label="NIT" value={form.nit} onChange={(e) => setCampo("nit", e.target.value)} placeholder="Ej: 900123456-7" error={errorDe("nit")} />
          {alertaNit && (
            <Alert tone={alertaNit.severidad === "error" ? "error" : "aviso"}>
              {alertaNit.severidad === "error" ? (
                <OctagonAlert size={18} className="mt-0.5 shrink-0" />
              ) : (
                <AlertTriangle size={18} className="mt-0.5 shrink-0" />
              )}
              <span className="font-medium"><strong>DIAN:</strong> NIT no validado por la DIAN, revísalo antes de guardar.</span>
            </Alert>
          )}
          <Input label="Fecha (AAAA-MM-DD)" value={form.fecha} onChange={(e) => setCampo("fecha", e.target.value)} placeholder="2026-10-15" error={errorDe("fecha")} />
          <Input label="Total" inputMode="numeric" value={form.total} onChange={(e) => setCampo("total", e.target.value)} placeholder="1250000" error={errorDe("total")} />
          <p aria-live="polite" className="rounded-xl border border-white/10 bg-zinc-950 px-3 py-2 text-sm text-zinc-100">
            Vista previa: <strong>{totalVistaPrevia}</strong>
            {" · "}
            <strong>{fechaVistaPrevia}</strong>
          </p>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-zinc-300">Categoría</span>
            <select
              value={form.categoria}
              onChange={(e) => setCampo("categoria", e.target.value)}
              className="min-h-[44px] w-full rounded-xl border border-white/15 bg-zinc-950 px-3 py-2 text-base text-zinc-100 focus:border-emerald-400/50 focus:outline-none focus:ring-2 focus:ring-emerald-400/20"
            >
              {CATEGORIAS.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
        </div>
        <Button variant="secondary" onClick={() => setForm(EJEMPLO)}>
          Usar datos de ejemplo
        </Button>
      </Card>
      </div>

      <div className="space-y-2">
        {alertas.length === 0 ? (
          <Alert tone="exito">
            <CheckCircle2 size={18} className="mt-0.5 shrink-0" />
            <span>Todo cuadra. Puedes guardar.</span>
          </Alert>
        ) : (
          alertas.map((a, i) => (
            <Alert key={i} tone={a.severidad === "error" ? "error" : "aviso"}>
              {a.severidad === "error" ? (
                <OctagonAlert size={18} className="mt-0.5 shrink-0" />
              ) : (
                <AlertTriangle size={18} className="mt-0.5 shrink-0" />
              )}
              <span><strong>{a.campo}:</strong> {a.mensaje}</span>
            </Alert>
          ))
        )}
      </div>

      {errorMsg && (
        <Alert tone="error" className="flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <span className="font-medium">{errorMsg}</span>
          <Button onClick={guardar} disabled={guardando} className="w-full sm:w-auto">
            Reintentar
          </Button>
        </Alert>
      )}

      <Button className="w-full" disabled={errores.length > 0 || guardando} onClick={guardar}>
        {guardando ? (
          <><Loader2 size={20} className="animate-spin" /> Guardando…</>
        ) : (
          <><Save size={20} /> Guardar</>
        )}
      </Button>
    </div>
  );
}
