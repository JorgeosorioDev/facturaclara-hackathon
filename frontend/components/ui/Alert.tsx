import * as React from "react";

type Props = React.HTMLAttributes<HTMLDivElement> & {
  tone: "error" | "aviso" | "exito" | "info";
};

const tones: Record<Props["tone"], string> = {
  error: "border-red-400/30 bg-red-400/10 text-red-300",
  aviso: "border-amber-400/30 bg-amber-400/10 text-amber-300",
  exito: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  info: "border-white/15 bg-white/5 text-zinc-200",
};

export function Alert({ tone, className = "", ...rest }: Props) {
  return (
    <div role="alert" className={`flex gap-2 rounded-lg border p-3 text-sm ${tones[tone]} ${className}`} {...rest} />
  );
}
