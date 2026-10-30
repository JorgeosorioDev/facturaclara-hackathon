"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Subir" },
  { href: "/revisar", label: "Revisar" },
  { href: "/facturas", label: "Facturas" },
];

// Client nav with active state; keeps layout.tsx a server component.
export function TopNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Principal" className="flex items-center gap-1 overflow-x-auto whitespace-nowrap">
      {LINKS.map((l) => {
        const active = pathname === l.href;
        return (
          <Link
            key={l.href}
            href={l.href}
            aria-current={active ? "page" : undefined}
            className={`rounded-lg px-3 py-2 text-sm transition focus-visible:outline-2 ${
              active
                ? "bg-emerald-400/10 font-semibold text-emerald-300"
                : "text-zinc-400 hover:bg-white/5 hover:text-zinc-100"
            }`}
          >
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}
