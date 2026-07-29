import { useEffect, useId, useRef } from "react";

import { useT } from "../i18n/useT";

export interface DestructiveConfirmProps {
  open: boolean;
  titleKey: string;
  bodyKeys: string[];
  confirmKey: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function DestructiveConfirm({
  open,
  titleKey,
  bodyKeys,
  confirmKey,
  onConfirm,
  onCancel,
}: DestructiveConfirmProps) {
  const t = useT();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      onCancel={onCancel}
      className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-6 shadow-lg backdrop:bg-black/40"
    >
      {open && (
        <>
          <h2 id={titleId} className="text-lg font-semibold text-gray-900">
            {t(titleKey)}
          </h2>
          <div className="mt-3 space-y-2 text-sm text-gray-700">
            {bodyKeys.map((bodyKey) => (
              <p key={bodyKey}>{t(bodyKey)}</p>
            ))}
          </div>
          <div className="mt-6 flex justify-end gap-2">
            <button
              type="button"
              onClick={onCancel}
              className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              {t("confirm.destructive_cancel")}
            </button>
            <button
              type="button"
              onClick={onConfirm}
              className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700"
            >
              {t(confirmKey)}
            </button>
          </div>
        </>
      )}
    </dialog>
  );
}
