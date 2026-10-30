import * as React from "react";

type Props = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary";
};

export function Button({ variant = "primary", className = "", ...rest }: Props) {
  const base =
    "inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg px-5 py-3 text-base font-semibold transition active:scale-[0.98] disabled:opacity-50";
  const styles =
    variant === "primary"
      ? "bg-emerald-500 text-zinc-950 shadow-glow hover:bg-emerald-400"
      : "border border-white/15 text-zinc-100 hover:bg-white/5";
  return <button className={`${base} ${styles} ${className}`} {...rest} />;
}
