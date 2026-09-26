import { createContext } from "react";

export interface MotionPlatformContextValue {
  provided: true;
}

export const MotionPlatformContext = createContext<MotionPlatformContextValue | null>(null);
