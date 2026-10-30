import * as React from "react";

export function Badge({ className = "", ...rest }: React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={`inline-flex items-center rounded-full border border-white/10 bg-zinc-800 px-3 py-1 text-xs font-semibold text-zinc-200 ${className}`}
      {...rest}
    />
  );
}
