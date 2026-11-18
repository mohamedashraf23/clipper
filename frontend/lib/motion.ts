// Shared motion values: one decelerating curve for everything (landing-page-design skill, B7).
import type { Transition, Variants } from "motion/react";

export const EASE = [0.22, 1, 0.36, 1] as const;
export const move: Transition = { duration: 0.5, ease: EASE };
export const fast: Transition = { duration: 0.3, ease: EASE };
export const spring: Transition = { type: "spring", stiffness: 520, damping: 34, mass: 0.8 };

export const riseIn: Variants = {
  hidden: { opacity: 0, y: 24 },
  show: { opacity: 1, y: 0, transition: { duration: 0.7, ease: EASE } },
};

export const stagger = (step = 0.06, delay = 0): Variants => ({
  hidden: {},
  show: { transition: { staggerChildren: step, delayChildren: delay } },
});
