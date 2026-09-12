import type { CSSProperties } from "react";

const style = {
  "--motion-duration": "200ms",
  "--motion-ease": "cubic-bezier(0.2, 0, 0, 1)",
} as CSSProperties;

export function StackFitTwAnimateProbe() {
  return (
    <div
      data-testid="tw-animate-probe"
      className="animate-in fade-in slide-in-from-bottom-2 duration-(--motion-duration) ease-[var(--motion-ease)]"
      style={style}
    >
      CSS animation probe
    </div>
  );
}
