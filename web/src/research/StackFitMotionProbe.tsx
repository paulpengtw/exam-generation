import { useState } from "react";
import {
  AnimatePresence,
  MotionConfig,
  motion,
  useReducedMotion,
} from "motion/react";

const motionTokens = {
  duration: 0.2,
  ease: "easeOut" as const,
};

export function StackFitMotionProbe() {
  const [status, setStatus] = useState<"pending" | "done" | "failed">("pending");
  const [items, setItems] = useState(["question-1"]);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const reducedMotion = useReducedMotion();

  return (
    <MotionConfig transition={motionTokens} reducedMotion="user">
      <section aria-label="Motion probe">
        <motion.button
          type="button"
          aria-label={`status ${status}`}
          animate={
            reducedMotion
              ? undefined
              : { scale: status === "pending" ? 1 : 1.02 }
          }
          onClick={() => setStatus((current) => current === "pending" ? "done" : "failed")}
        >
          {status}
        </motion.button>

        <motion.ul layout aria-label="streamed questions">
          <AnimatePresence initial={false}>
            {items.map((item) => (
              <motion.li
                key={item}
                layout
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
              >
                {item}
              </motion.li>
            ))}
          </AnimatePresence>
        </motion.ul>
        <button type="button" onClick={() => setItems([])}>Remove questions</button>

        <motion.button
          type="button"
          aria-expanded={detailsOpen}
          onClick={() => setDetailsOpen((open) => !open)}
        >
          Disclosure
        </motion.button>
        <AnimatePresence initial={false}>
          {detailsOpen && (
            <motion.div
              layout
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
            >
              Details
            </motion.div>
          )}
        </AnimatePresence>
      </section>
    </MotionConfig>
  );
}
