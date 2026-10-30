import * as React from "react";

export function Card({ className = "", ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`rounded-xl border border-white/10 bg-zinc-900 p-4 text-zinc-100 shadow-glow ${className}`}
      {...rest}
    />
  );
}
