import * as React from "react";

export function Skeleton({ className = "", ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={`animate-pulse rounded-lg bg-white/10 ${className}`}
      {...rest}
    />
  );
}
