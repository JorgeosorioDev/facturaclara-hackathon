"use client";

import * as React from "react";
import { motion, useReducedMotion } from "motion/react";
import { UploadCloud } from "lucide-react";
import { Button } from "../ui/Button";

type Props = {
  onSubir: () => void;
  panel: React.ReactNode;
};

const EASE = [0.16, 1, 0.3, 1] as const;

// Split hero 50/50: copy left, upload panel right. Reveal on inView with stagger.
export function HeroWow({ onSubir, panel }: Props) {
  const reduce = useReducedMotion();
  const anim = (i: number) =>
    reduce
      ? {}
      : {
          initial: { opacity: 0, y: 24 },
          whileInView: { opacity: 1, y: 0 },
          viewport: { once: true, amount: 0.4 },
          transition: { duration: 0.6, delay: i * 0.06, ease: EASE },
        };

  return (
    <section className="grid items-center gap-8 pt-6 md:grid-cols-2 md:pt-10">
      <div className="space-y-5">
        <motion.p
          {...anim(0)}
          className="text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-300"
        >
          DIAN · Colombia
        </motion.p>
        <motion.h1
          {...anim(1)}
          className="text-4xl font-bold leading-[1.05] tracking-tight text-white md:text-5xl"
        >
          Factura clara
          <br />
          en segundos
        </motion.h1>
        <motion.p
          {...anim(2)}
          className="max-w-[45ch] text-base leading-relaxed text-zinc-400"
        >
          Foto de tu factura y listo: NIT, fecha y total validados.
        </motion.p>
        <motion.div {...anim(3)} className="flex flex-wrap items-center gap-3">
          <Button onClick={onSubir} className="whitespace-nowrap">
            <UploadCloud size={20} aria-hidden /> Subir factura
          </Button>
          <a
            href="#como"
            className="inline-flex min-h-[44px] items-center justify-center rounded-lg border border-white/15 px-5 py-3 text-base font-semibold text-zinc-100 transition hover:bg-white/5 active:scale-[0.98]"
          >
            Ver cómo funciona
          </a>
        </motion.div>
        <motion.p {...anim(4)} className="font-mono text-xs text-zinc-500">
          12s · 100% DIAN · COP
        </motion.p>
      </div>
      <motion.div {...anim(2)}>{panel}</motion.div>
    </section>
  );
}
