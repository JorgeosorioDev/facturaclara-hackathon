import * as React from "react";

type Props = React.InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string };

export function Input({ label, id, error, className = "", ...rest }: Props) {
  const inputId = id ?? `input-${label}`;
  return (
    <label htmlFor={inputId} className="block">
      <span className="mb-1 block text-sm font-medium text-zinc-300">{label}</span>
      <input
        id={inputId}
        aria-invalid={error ? true : undefined}
        className={`min-h-[44px] w-full rounded-xl border border-white/15 bg-zinc-950 px-3 py-2 text-base text-zinc-100 placeholder:text-zinc-500 focus:border-emerald-400/50 focus:outline-none focus:ring-2 focus:ring-emerald-400/20 ${className}`}
        {...rest}
      />
      {error && (
        <span role="alert" className="mt-1 block text-sm font-medium text-red-300">
          {error}
        </span>
      )}
    </label>
  );
}
