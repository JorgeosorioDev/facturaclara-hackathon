"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Camera,
  Check,
  ImagePlus,
  Loader2,
  RotateCcw,
  UploadCloud,
} from "lucide-react";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Skeleton } from "../components/ui/Skeleton";
import { HeroWow } from "../components/landing/HeroWow";
import { API_URL } from "../lib/api";

const PASOS_NOMBRES = ["Recortando documento", "Leyendo datos", "Validando NIT"];

const COMO = [
  {
    n: "1",
    titulo: "Foto",
    texto: "Toma una foto o arrastra el PDF de tu factura desde el celular.",
  },
  {
    n: "2",
    titulo: "Revisa",
    texto: "Verifica NIT, fecha y total antes de guardar. Nada se guarda solo.",
  },
  {
    n: "3",
    titulo: "Guarda",
    texto: "Tu factura queda lista para la DIAN con totales en COP.",
  },
];

export default function SubirPage() {
  const router = useRouter();
  const camaraRef = useRef<HTMLInputElement>(null);
  const galeriaRef = useRef<HTMLInputElement>(null);
  const [estado, setEstado] = useState<"idle" | "cargando" | "error">("idle");
  const [error, setError] = useState("");
  const [paso, setPaso] = useState(0);
  const [arrastrando, setArrastrando] = useState(false);
  const [vistaLocal, setVistaLocal] = useState<string | null>(null);
  const ultimoArchivo = useRef<File | null>(null);
  const temporizadores = useRef<ReturnType<typeof setTimeout>[]>([]);

  function limpiarPasos() {
    temporizadores.current.forEach(clearTimeout);
    temporizadores.current = [];
  }

  const PASOS = PASOS_NOMBRES;

  async function manejarArchivo(file: File) {
    ultimoArchivo.current = file;
    setEstado("cargando");
    setError("");
    setPaso(0);
    limpiarPasos();
    temporizadores.current = [
      setTimeout(() => setPaso(1), 700),
      setTimeout(() => setPaso(2), 1600),
    ];
    try {
      const preview = await new Promise<string>((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => resolve(String(r.result));
        r.onerror = reject;
        r.readAsDataURL(file);
      });
      setVistaLocal(preview);
      sessionStorage.setItem("facturaclara:preview", preview);
      const form = new FormData();
      form.append("file", file);
      let res: Response;
      try {
        res = await fetch(`${API_URL}/scan`, { method: "POST", body: form });
      } catch {
        throw new Error("API caída: no se pudo contactar al backend en /scan.");
      }
      if (!res.ok) {
        let detalle = "";
        try {
          const data = await res.json();
          detalle = typeof data?.detail === "string" ? `: ${data.detail}` : "";
        } catch {
          /* cuerpo no JSON */
        }
        throw new Error(`El backend devolvió HTTP ${res.status}${detalle}`);
      }
      const scan = await res.json();
      limpiarPasos();
      setPaso(2);
      sessionStorage.setItem("facturaclara:scan", JSON.stringify(scan));
      sessionStorage.setItem(
        "facturaclara:bajaCalidad",
        scan?.fallback ? "1" : "0"
      );
      router.push("/revisar");
    } catch (err) {
      limpiarPasos();
      setEstado("error");
      setError(
        err instanceof Error
          ? `No pudimos leer la factura. ${err.message}`
          : "No pudimos leer la imagen. Revisa el archivo e inténtalo de nuevo."
      );
    }
  }

  function reintentar() {
    const f = ultimoArchivo.current;
    if (f) manejarArchivo(f);
    else setEstado("idle");
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setArrastrando(false);
    const f = e.dataTransfer.files?.[0];
    if (f) manejarArchivo(f);
  }

  const subir = () => galeriaRef.current?.click();
  const confianzaPct = ["33%", "66%", "100%"][paso] ?? "33%";

  return (
    <div className="space-y-12">
      <HeroWow
        onSubir={subir}
        panel={
          <Card className="space-y-4 border-white/10 bg-zinc-900 shadow-glow">
            <div
              role="button"
              tabIndex={0}
              aria-label="Arrastra una factura o pulsa para elegir un archivo"
              onClick={() => galeriaRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") galeriaRef.current?.click();
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setArrastrando(true);
              }}
              onDragLeave={() => setArrastrando(false)}
              onDrop={onDrop}
              className={`flex min-h-44 cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center transition focus-visible:outline-2 ${
                arrastrando
                  ? "border-emerald-400 bg-emerald-400/10"
                  : "border-white/15 bg-white/5 hover:bg-white/10"
              }`}
            >
              {vistaLocal ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={vistaLocal}
                  alt="Vista previa de la factura elegida"
                  className="max-h-40 rounded-xl border border-white/10 object-contain"
                />
              ) : (
                <>
                  <UploadCloud size={28} aria-hidden className="text-emerald-400" />
                  <p className="text-sm font-medium text-zinc-100">
                    Arrastra tu factura aquí o pulsa para elegirla
                  </p>
                  <p className="text-xs text-zinc-500">JPG o PNG desde tu celular o computador</p>
                </>
              )}
            </div>

            <div className="grid gap-3">
              <Button
                onClick={() => camaraRef.current?.click()}
                className="min-h-14 w-full whitespace-nowrap text-lg"
              >
                <Camera size={22} /> Tomar foto
              </Button>
              <Button
                variant="secondary"
                onClick={() => galeriaRef.current?.click()}
                className="w-full whitespace-nowrap"
              >
                <ImagePlus size={20} /> Elegir de galería
              </Button>
            </div>

            <input
              ref={camaraRef}
              type="file"
              accept="image/*"
              capture="environment"
              aria-label="Tomar foto de la factura"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) manejarArchivo(f);
              }}
            />
            <input
              ref={galeriaRef}
              type="file"
              accept="image/*"
              aria-label="Elegir imagen de la factura"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) manejarArchivo(f);
              }}
            />
          </Card>
        }
      />

      {estado === "cargando" && (
        <Card className="space-y-3 border-white/10 bg-zinc-900" aria-live="polite">
          <Skeleton className="h-40 w-full" />
          <div
            className="h-1 overflow-hidden rounded-full bg-white/10"
            role="progressbar"
            aria-valuenow={paso + 1}
            aria-valuemin={1}
            aria-valuemax={3}
            aria-label="Confianza de lectura"
          >
            <div
              className="h-full rounded-full bg-emerald-400 transition-all"
              style={{ width: confianzaPct }}
            />
          </div>
          <ol className="space-y-2">
            {PASOS.map((nombre, i) => {
              const activo = i === paso;
              const hecho = i < paso;
              return (
                <li
                  key={nombre}
                  aria-current={activo ? "step" : undefined}
                  className={`flex items-center gap-2 text-sm ${
                    activo
                      ? "font-semibold text-emerald-300"
                      : hecho
                        ? "font-medium text-zinc-300"
                        : "text-zinc-500"
                  }`}
                >
                  {hecho ? (
                    <Check size={16} aria-hidden className="shrink-0 text-emerald-400" />
                  ) : activo ? (
                    <Loader2 size={16} aria-hidden className="shrink-0 animate-spin text-emerald-300" />
                  ) : (
                    <span aria-hidden className="inline-block h-4 w-4 rounded-full border border-white/20" />
                  )}
                  {nombre}
                  {activo ? "…" : hecho ? "" : ""}
                </li>
              );
            })}
          </ol>
        </Card>
      )}

      {estado === "error" && (
        <Alert tone="error" className="flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <span className="font-medium">{error}</span>
          <Button onClick={reintentar} className="w-full whitespace-nowrap sm:w-auto">
            <RotateCcw size={18} /> Reintentar
          </Button>
        </Alert>
      )}

      <section id="como" aria-label="Cómo funciona" className="scroll-mt-20 space-y-4">
        <h2 className="text-2xl font-bold tracking-tight text-white">
          De la foto al registro
        </h2>
        <div className="grid gap-4 md:grid-cols-2">
          {COMO.map((p, i) => (
            <div
              key={p.n}
              className={`rounded-xl border border-white/10 bg-zinc-900 p-5 ${
                i === 0 ? "md:col-span-2 md:flex md:items-center md:gap-4" : ""
              }`}
            >
              <span className="font-mono text-xs text-emerald-300">{p.n}</span>
              <h3 className="mt-1 text-lg font-semibold text-white">{p.titulo}</h3>
              <p className="mt-1 text-sm leading-relaxed text-zinc-400">{p.texto}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
