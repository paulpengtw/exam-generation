import { useLayoutEffect, type ReactNode } from 'react';
import { LazyMotion, domAnimation, MotionConfig } from 'motion/react';
import { useLocation } from 'react-router-dom';
import { writeMotionTokens } from './tokens';
import { useMotionTiming } from './useMotionTiming';
import { prototypeEnabled, routeEvent, settingsEvent } from './prototypeSettings';
import PrototypeSwitcher from './PrototypeSwitcher';

export default function MotionRoot({ children }: { children: ReactNode }) {
  const location = useLocation();
  const timing = useMotionTiming();
  useLayoutEffect(() => {
    window.dispatchEvent(new Event(settingsEvent));
    window.dispatchEvent(new Event(routeEvent));
  }, [location.key, location.pathname, location.search]);
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = 'light';
    document.documentElement.dataset.motion = timing.reduced ? 'reduced' : 'full';
    writeMotionTokens(timing.scale);
  }, [timing.reduced, timing.scale]);
  return <LazyMotion features={domAnimation} strict>
    <MotionConfig reducedMotion={timing.reduced ? 'always' : 'user'} transition={timing.transition()}>
      {children}
      {prototypeEnabled && <PrototypeSwitcher />}
    </MotionConfig>
  </LazyMotion>;
}
