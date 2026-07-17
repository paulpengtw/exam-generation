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
