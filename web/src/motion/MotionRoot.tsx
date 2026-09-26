import type { ReactNode } from "react";
import { domAnimation, LazyMotion, MotionConfig } from "motion/react";
import { durations, easings } from "./tokens";

const defaultTransition = {
  duration: durations.standard / 1000,
  ease: [...easings.signature] as [number, number, number, number],
};

export default function MotionRoot({ children }: { children: ReactNode }) {
  return (
    <LazyMotion features={domAnimation} strict>
      <MotionConfig
        reducedMotion="user"
        transition={defaultTransition}
      >
        {children}
      </MotionConfig>
    </LazyMotion>
  );
}
