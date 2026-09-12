import { useEffect, useRef } from "react";

import styles from "./StackFitNativeCssProbe.module.css";

export function StackFitNativeCssProbe() {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || dialog.open) return;
    dialog.showModal();
    return () => {
      if (dialog.open) dialog.close();
    };
  }, []);

  return (
    <dialog ref={dialogRef} className={styles.dialog}>
      Native dialog probe
    </dialog>
  );
}
