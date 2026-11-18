"use client";
import { motion, AnimatePresence, animate, useMotionValue, useMotionValueEvent } from "motion/react";
import { useEffect, useState, type ReactNode } from "react";
import { spring, fast } from "@/lib/motion";

/** Two-option segmented control; the highlight slides between options. */
export function Segmented<T extends string>({ id, value, options, onChange, label }: {
  id: string; value: T; label: string;
  options: { value: T; label: string; icon?: ReactNode }[]; onChange: (v: T) => void;
}) {
  return (
    <div className="seg" role="tablist" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" role="tab" aria-selected={value === o.value}
                className="button-sm" onClick={() => onChange(o.value)}>
          {value === o.value && <motion.span layoutId={`${id}-bg`} className="pill-bg" transition={spring} />}
          <span>{o.icon}{o.label}</span>
        </button>
      ))}
    </div>
  );
}

/** A whole-row toggle with a sliding switch. */
export function Toggle({ checked, onChange, icon, children }: {
  checked: boolean; onChange: (v: boolean) => void; icon: ReactNode; children: ReactNode;
}) {
  return (
    <button type="button" role="switch" aria-checked={checked} className="toggle" onClick={() => onChange(!checked)}>
      <span className="txt body-5">{icon}{children}</span>
      <span className={`switch ${checked ? "on" : ""}`}>
        <motion.span layout className="thumb" transition={spring} />
      </span>
    </button>
  );
}

/** Number that counts to its new value instead of jumping. */
export function AnimatedNumber({ value, suffix = "" }: { value: number; suffix?: string }) {
  const mv = useMotionValue(value);
  const [shown, setShown] = useState(value);
  useMotionValueEvent(mv, "change", (v) => setShown(Math.round(v)));
  useEffect(() => {
    const c = animate(mv, value, { duration: 0.6, ease: [0.22, 1, 0.36, 1] });
    return () => c.stop();
  }, [mv, value]);
  return <>{shown}{suffix}</>;
}

/** Inline error that slides in under its control. */
export function InlineError({ message, icon }: { message: string; icon: ReactNode }) {
  return (
    <AnimatePresence>
      {message && (
        <motion.div key={message} className="form-err body-6" role="alert"
                    initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={fast}>
          {icon}<span>{message}</span>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
