import type { ReactNode } from "react";
import { AnimatePresence, m, useReducedMotion } from "motion/react";

import MotionRoot from "./MotionRoot";
import { durations, easings } from "./tokens";

export interface MotionDisclosureProps {
  open: boolean;
  children: ReactNode;
  className?: string;
}

const signatureEase = [...easings.signature] as [number, number, number, number];
const exitEase = [...easings.exit] as [number, number, number, number];

/**
 * Shared height/opacity disclosure motion. The content remains mounted for a
 * real exit so callers can preserve the acknowledgement semantics of a
 * disclosure while the visual state changes.
 */
export function MotionDisclosure({
  open,
  children,
  className,
}: MotionDisclosureProps) {
  const reducedMotion = useReducedMotion();
  const enterTransition = reducedMotion
    ? { duration: 0 }
    : { duration: durations.standard / 1000, ease: signatureEase };
  const exitTransition = reducedMotion
    ? { duration: 0 }
    : { duration: durations.quick / 1000, ease: exitEase };

  return (
    <MotionRoot>
      <AnimatePresence initial={false}>
        {open ? (
          <m.div
            key="disclosure"
            initial={reducedMotion ? false : { height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{
              height: 0,
              opacity: 0,
              transition: exitTransition,
            }}
            transition={enterTransition}
            className={`overflow-hidden${className ? ` ${className}` : ""}`}
          >
            {children}
          </m.div>
        ) : null}
      </AnimatePresence>
    </MotionRoot>
  );
}
