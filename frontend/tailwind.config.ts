import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primario: "#1E3A5F",
        fondo: "#FAFAF7",
        carbon: "#1F2937",
        exito: "#15803D",
        error: "#B91C1C",
        aviso: "#B45309",
        esmeralda: "#10B981",
      },
      // Consistent corner scale: cards 16px, controls 12px.
      borderRadius: {
        xl: "1rem",
        lg: "0.75rem",
      },
      // Shadows tinted toward primario, never pure black.
      boxShadow: {
        saas: "0 1px 2px rgba(30,58,95,0.08), 0 12px 32px -16px rgba(30,58,95,0.35)",
        "saas-sm": "0 1px 2px rgba(30,58,95,0.10)",
        glow: "0 0 40px -12px rgba(16,185,129,0.5)",
      },
    },
  },
  plugins: [],
};
export default config;
