import { writeMotionTokens } from "../motion/tokens";
import "@testing-library/jest-dom";

// Node 26+ ships an experimental global `localStorage` that shadows jsdom's
// implementation inside vitest's jsdom environment (vitest only re-exposes
// jsdom's `window.localStorage` for keys not already present on
// `globalThis`, and Node's experimental getter returns `undefined` without
// `--localstorage-file`). Install a minimal in-memory polyfill so
// `window.localStorage` / `localStorage` behave as expected in tests.
class MemoryStorage implements Storage {
  private store = new Map<string, string>();

  get length(): number {
    return this.store.size;
  }

  clear(): void {
    this.store.clear();
  }

  getItem(key: string): string | null {
    return this.store.has(key) ? this.store.get(key)! : null;
  }

  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}

Object.defineProperty(globalThis, "localStorage", {
  value: new MemoryStorage(),
  configurable: true,
  writable: true,
});

// jsdom 29.1.1 does not implement the native dialog methods. Emulate the
// browser behavior used by the app: showModal() opens the dialog, close()
// closes it and emits `close`, and Escape emits a cancelable `cancel` event
// before closing. Listen on document because Escape dismissal is browser
// modal behavior; keydown events fired on a dialog bubble here as they do in
// a browser.
Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
  value: function showModal(this: HTMLDialogElement): void {
    this.open = true;
  },
  configurable: true,
  writable: true,
});

Object.defineProperty(HTMLDialogElement.prototype, "close", {
  value: function close(this: HTMLDialogElement, returnValue?: string): void {
    if (returnValue !== undefined) {
      this.returnValue = returnValue;
    }
    this.open = false;
    this.dispatchEvent(new Event("close"));
  },
  configurable: true,
  writable: true,
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;

  const dialogs = Array.from(document.querySelectorAll<HTMLDialogElement>("dialog[open]"));
  const dialog = dialogs.at(-1);
  if (!dialog) return;

  const cancelEvent = new Event("cancel", { cancelable: true });
  if (dialog.dispatchEvent(cancelEvent)) {
    dialog.close();
  }
});

writeMotionTokens();
