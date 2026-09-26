import type { ReactNode } from "react";
import { AnimatePresence, m, useReducedMotion } from "motion/react";

import MotionRoot from "./MotionRoot";
import { durations, motionEase } from "./tokens";

export interface MotionDisclosureProps {
  open: boolean;
  children: ReactNode;
  className?: string;
}

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
    : { duration: durations.standard / 1000, ease: motionEase.signature };
  const exitTransition = reducedMotion
    ? { duration: 0 }
    : { duration: durations.quick / 1000, ease: motionEase.exit };

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
