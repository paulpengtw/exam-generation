import { useContext, useMemo, type ReactNode } from "react";
import { domAnimation, LazyMotion, MotionConfig } from "motion/react";
import { durations, motionEase } from "./tokens";
import { MotionPlatformContext, type MotionPlatformContextValue } from "./MotionPlatformContext";

const defaultTransition = {
  duration: durations.standard / 1000,
  ease: motionEase.signature,
};

export default function MotionRoot({ children }: { children: ReactNode }) {
  const existingPlatform = useContext(MotionPlatformContext);
  const platform = useMemo<MotionPlatformContextValue>(() => ({ provided: true }), []);

  if (existingPlatform) return <>{children}</>;

  return (
    <MotionPlatformContext.Provider value={platform}>
      <LazyMotion features={domAnimation} strict>
        <MotionConfig
          reducedMotion="user"
          transition={defaultTransition}
        >
          {children}
        </MotionConfig>
      </LazyMotion>
    </MotionPlatformContext.Provider>
  );
}
