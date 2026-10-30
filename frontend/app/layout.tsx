import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { Badge } from "../components/ui/Badge";
import { TopNav } from "../components/dashboard/TopNav";

export const metadata: Metadata = {
  title: "FacturaClara",
  description: "Escanea, revisa y entiende tus facturas",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es-CO">
      <body className="flex min-h-dvh flex-col bg-zinc-950 text-zinc-100">
        <header className="sticky top-0 z-10 border-b border-white/10 bg-zinc-950/80 backdrop-blur">
          <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between gap-3 px-4">
            <Link href="/" className="flex shrink-0 items-center gap-2">
              <span className="text-lg font-bold text-white">FacturaClara</span>
              <Badge className="border border-emerald-400/20 bg-emerald-400/10 text-emerald-300">
                Beta Colombia
              </Badge>
            </Link>
            <TopNav />
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 pb-16 pt-6">{children}</main>
        <footer className="border-t border-white/10">
          <p className="mx-auto w-full max-w-6xl px-4 py-4 text-xs text-zinc-400">
            Hecho para DIAN · Datos en tu base
          </p>
        </footer>
      </body>
    </html>
  );
}
