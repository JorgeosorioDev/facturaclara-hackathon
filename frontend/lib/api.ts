export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:18001";

export function formatoCOP(valor: number | null | undefined): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return "—";
  return new Intl.NumberFormat("es-CO", {
    style: "currency",
    currency: "COP",
    maximumFractionDigits: 0,
  }).format(valor);
}

export function formatoFecha(iso: string | null | undefined): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (m) return `${m[3]}/${m[2]}/${m[1]}`;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  return `${dd}/${mm}/${d.getFullYear()}`;
}

export type Factura = {
  id: number;
  proveedor: string | null;
  nit: string | null;
  fecha: string | null;
  subtotal: number | null;
  iva: number | null;
  total: number | null;
  categoria: string | null;
  confianza: number | null;
};

export type Alerta = {
  campo: string;
  regla: string;
  mensaje: string;
  severidad: "error" | "aviso";
};

export const CATEGORIAS = [
  "transporte",
  "alimentacion",
  "oficina",
  "servicios",
  "salud",
  "otros",
];
