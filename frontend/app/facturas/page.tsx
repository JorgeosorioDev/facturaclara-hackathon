"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Bot, Loader2, Receipt, Send, TrendingUp, Wallet } from "lucide-react";
import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { Skeleton } from "../../components/ui/Skeleton";
import { API_URL, formatoCOP, formatoFecha, type Factura } from "../../lib/api";

type Mensaje = { rol: "yo" | "bot"; texto: string; fuente?: "sql" | "ayuda" | null };

type FilaMes = { mes: string; total: number };
type FilaCategoria = { categoria: string; total: number };

const SUGERENCIAS = [
  "¿Cuánto gasté en octubre de 2026?",
  "¿Cuánto llevo gastado en transporte?",
  "Muéstrame las últimas 3 facturas",
];

export default function FacturasPage() {
  const router = useRouter();
  const [fase, setFase] = useState<"cargando" | "lista" | "error" | "vacia">("cargando");
  const [facturas, setFacturas] = useState<Factura[]>([]);
  const [mensajes, setMensajes] = useState<Mensaje[]>([]);
  const [pregunta, setPregunta] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [filasMes, setFilasMes] = useState<FilaMes[]>([]);
  const [filasCategoria, setFilasCategoria] = useState<FilaCategoria[]>([]);
  const [errorMsg, setErrorMsg] = useState("");

  async function cargar() {
    setFase("cargando");
    setErrorMsg("");
    try {
      const [rFact, rMes, rCat] = await Promise.all([
        fetch(`${API_URL}/invoices`),
        fetch(`${API_URL}/reports/total?group_by=mes`),
        fetch(`${API_URL}/reports/total?group_by=categoria`),
      ]);
      if (!rFact.ok) throw new Error(`GET /invoices devolvió HTTP ${rFact.status}`);
      if (!rMes.ok) throw new Error(`GET /reports/total?group_by=mes devolvió HTTP ${rMes.status}`);
      if (!rCat.ok) throw new Error(`GET /reports/total?group_by=categoria devolvió HTTP ${rCat.status}`);
      const dFact = await rFact.json();
      const dMes = await rMes.json();
      const dCat = await rCat.json();
      const rows: Factura[] = dFact.facturas ?? dFact ?? [];
      setFacturas(rows);
      setFilasMes(Array.isArray(dMes.rows) ? dMes.rows : []);
      setFilasCategoria(Array.isArray(dCat.rows) ? dCat.rows : []);
      setFase(rows.length === 0 ? "vacia" : "lista");
    } catch (err) {
      setErrorMsg(
        err instanceof Error
          ? err.message
          : "No pudimos contactar al backend."
      );
      setFase("error");
    }
  }

  useEffect(() => {
    cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totalMes = useMemo(() => {
    const ahora = new Date();
    const mes = `${ahora.getFullYear()}-${String(ahora.getMonth() + 1).padStart(2, "0")}`;
    const fila = filasMes.find((r) => r.mes === mes);
    if (fila) return fila.total;
    const delMes = facturas.filter((f) => (f.fecha ?? "").startsWith(mes));
    if (delMes.length === 0) return null;
    return delMes.reduce((acc, f) => acc + (f.total ?? 0), 0);
  }, [filasMes, facturas]);

  const totalGeneral = useMemo(() => {
    if (filasMes.length > 0) return filasMes.reduce((acc, r) => acc + (r.total ?? 0), 0);
    return facturas.length ? facturas.reduce((acc, f) => acc + (f.total ?? 0), 0) : null;
  }, [filasMes, facturas]);

  async function preguntar(textoDirecto?: string) {
    const texto = (textoDirecto ?? pregunta).trim();
    if (!texto || enviando) return;
    setMensajes((m) => [...m, { rol: "yo", texto }]);
    setPregunta("");
    setEnviando(true);
    try {
      const res = await fetch(`${API_URL}/assistant`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pregunta: texto }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        const detalle =
          data && typeof data.detail === "string" ? `: ${data.detail}` : "";
        throw new Error(`HTTP ${res.status}${detalle}`);
      }
      const respuesta: string = data?.respuesta ?? "Sin respuesta del asistente.";
      const fuente = data?.fuente === "sql" || data?.fuente === "ayuda" ? data.fuente : null;
      setMensajes((m) => [...m, { rol: "bot", texto: respuesta, fuente }]);
    } catch {
      setMensajes((m) => [
        ...m,
        { rol: "bot", texto: "No pudimos consultar al asistente. Revisa tu conexión e inténtalo de nuevo.", fuente: null },
      ]);
    } finally {
      setEnviando(false);
    }
  }

  if (fase === "cargando") {
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
        <Skeleton className="h-40 w-full" />
        <p className="flex items-center gap-2 text-sm font-medium text-zinc-300">
          <Loader2 size={16} className="animate-spin" /> Cargando tus facturas…
        </p>
      </div>
    );
  }

  if (fase === "error") {
    return (
      <Alert tone="error" className="items-center justify-between">
        <span>No pudimos cargar tus facturas.{errorMsg ? ` ${errorMsg}` : ""}</span>
        <Button onClick={cargar}>Reintentar</Button>
      </Alert>
    );
  }

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold text-white">Facturas y asistente</h1>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Card className="space-y-1">
          <p className="flex items-center gap-1.5 text-xs font-medium text-zinc-400">
            <Wallet size={14} aria-hidden className="text-emerald-400" /> Total del mes
          </p>
          <p className="font-mono text-2xl font-bold text-white sm:text-3xl">{totalMes !== null ? formatoCOP(totalMes) : "—"}</p>
        </Card>
        <Card className="space-y-1">
          <p className="flex items-center gap-1.5 text-xs font-medium text-zinc-400">
            <TrendingUp size={14} aria-hidden className="text-emerald-400" /> Total general
          </p>
          <p className="font-mono text-2xl font-bold text-white sm:text-3xl">{totalGeneral !== null ? formatoCOP(totalGeneral) : "—"}</p>
        </Card>
        <Card className="space-y-1">
          <p className="flex items-center gap-1.5 text-xs font-medium text-zinc-400">
            <Receipt size={14} aria-hidden className="text-emerald-400" /> Facturas
          </p>
          <p className="font-mono text-2xl font-bold text-white sm:text-3xl">{facturas.length}</p>
        </Card>
      </div>

      {filasCategoria.length > 0 && (
        <Card className="space-y-2">
          <p className="text-sm font-semibold text-zinc-100">Por categoría</p>
          <ul className="space-y-1 text-sm">
            {filasCategoria.map((r) => (
              <li key={r.categoria} className="flex items-center justify-between">
                <Badge className="border-emerald-400/20 bg-emerald-400/10 text-emerald-300">{r.categoria}</Badge>
                <span className="font-semibold text-zinc-100">{formatoCOP(r.total)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div>
        <a
          href={`${API_URL}/invoices/export.csv`}
          className="rounded text-sm font-semibold text-emerald-300 underline underline-offset-4 focus-visible:outline-2"
        >
          Exportar CSV
        </a>
      </div>

      {fase === "vacia" ? (
        <Card className="space-y-3 text-center">
          <Receipt size={28} aria-hidden className="mx-auto text-emerald-400/50" />
          <p className="font-semibold">Aún no tienes facturas. Toma la primera foto.</p>
          <p className="text-sm text-zinc-400">En menos de un minuto queda lista para revisar.</p>
          <div>
            <Button onClick={() => router.push("/")} className="whitespace-nowrap">Tomar foto</Button>
          </div>
        </Card>
      ) : (
        <Card className="max-h-[420px] overflow-auto p-0">
          <table className="w-full min-w-[480px] text-left text-sm">
            <thead className="sticky top-0 z-[5]">
              <tr className="border-b border-white/5 bg-zinc-950 text-xs uppercase text-zinc-400">
                <th scope="col" className="bg-zinc-950 px-4 py-2">Proveedor</th>
                <th scope="col" className="bg-zinc-950 px-4 py-2">Fecha</th>
                <th scope="col" className="bg-zinc-950 px-4 py-2">Categoría</th>
                <th scope="col" className="bg-zinc-950 px-4 py-2 text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {facturas.map((f) => (
                <tr key={f.id} className="border-b border-white/5 transition last:border-0 hover:bg-white/5">
                  <td className="px-4 py-2 font-medium text-zinc-100">{f.proveedor ?? "—"}</td>
                  <td className="px-4 py-2 text-zinc-300">{formatoFecha(f.fecha)}</td>
                  <td className="px-4 py-2">
                    <Badge className="border-emerald-400/20 bg-emerald-400/10 text-emerald-300">{f.categoria ?? "—"}</Badge>
                  </td>
                  <td className="px-4 py-2 text-right font-semibold text-zinc-100">{formatoCOP(f.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <Card className="space-y-3">
        <p className="flex items-center gap-2 font-semibold text-zinc-100">
          <Bot size={18} className="text-emerald-400" /> Asistente{" "}
          <Badge className="border-emerald-400/20 bg-emerald-400/10 text-emerald-300">dato de tu base</Badge>
        </p>
        <div aria-live="polite" className="max-h-64 space-y-2 overflow-y-auto rounded-xl border border-white/10 bg-zinc-950 p-3">
          {mensajes.length === 0 && (
            <p className="text-sm text-zinc-400">Pregunta, por ejemplo: “¿cuánto gasté en transporte?”</p>
          )}
          {mensajes.map((m, i) => (
            <div key={i} className={`rounded-xl p-2 text-sm ${m.rol === "yo" ? "ml-8 bg-emerald-500 text-zinc-950" : "mr-8 border border-white/10 bg-zinc-900 text-zinc-100"}`}>
              {m.texto}
              {m.rol === "bot" && m.fuente && (
                <p className="mt-1 text-xs text-zinc-400">
                  {m.fuente === "sql" ? "dato de tu base" : "ayuda: pide un mes, categoría, proveedor o las últimas facturas"}
                </p>
              )}
            </div>
          ))}
          {enviando && (
            <p className="flex items-center gap-2 text-sm text-zinc-400">
              <Loader2 size={14} className="animate-spin" /> Consultando…
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {SUGERENCIAS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => preguntar(s)}
              disabled={enviando}
              className="rounded-full border border-emerald-400/30 bg-emerald-400/5 px-3 py-2 text-sm font-medium text-emerald-300 transition hover:bg-emerald-400/10 focus-visible:outline-2 active:scale-[0.98] disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            value={pregunta}
            onChange={(e) => setPregunta(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && preguntar()}
            placeholder="Escribe tu pregunta…"
            aria-label="Escribe tu pregunta al asistente"
            className="min-h-[44px] flex-1 rounded-xl border border-white/15 bg-zinc-950 px-3 py-2 text-base text-zinc-100 placeholder:text-zinc-500 focus:border-emerald-400/50 focus:outline-none focus:ring-2 focus:ring-emerald-400/20"
          />
          <Button onClick={() => preguntar()} aria-label="Enviar pregunta" disabled={enviando}>
            <Send size={20} />
          </Button>
        </div>
      </Card>
    </div>
  );
}
