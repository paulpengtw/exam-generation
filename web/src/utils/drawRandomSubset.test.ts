import { describe, expect, it, vi } from "vitest";
import { drawRandomSubset } from "./drawRandomSubset";

describe("drawRandomSubset", () => {
  it("returns empty array for empty pool", () => {
    expect(drawRandomSubset([], 1, 3)).toEqual([]);
  });

  it("returns empty array when min <= 0", () => {
    expect(drawRandomSubset(["a", "b"], 0, 3)).toEqual([]);
  });

  it("returns exactly min items when Math.random returns 0", () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    expect(drawRandomSubset(["a", "b", "c", "d"], 1, 3)).toHaveLength(1);
    vi.restoreAllMocks();
  });

  it("returns exactly max items when Math.random returns near 1", () => {
    vi.spyOn(Math, "random").mockReturnValue(0.9999);
    expect(drawRandomSubset(["a", "b", "c", "d", "e"], 1, 3)).toHaveLength(3);
    vi.restoreAllMocks();
  });

  it("clamps max to pool length", () => {
    vi.spyOn(Math, "random").mockReturnValue(0.9999);
    expect(drawRandomSubset(["a", "b"], 1, 5)).toHaveLength(2);
    vi.restoreAllMocks();
  });

  it("returns unique items from the pool", () => {
    vi.spyOn(Math, "random").mockReturnValue(0.5);
    const result = drawRandomSubset(["a", "b", "c", "d"], 2, 3);
    const pool = new Set(["a", "b", "c", "d"]);
    for (const item of result) expect(pool.has(item)).toBe(true);
    expect(new Set(result).size).toBe(result.length);
    vi.restoreAllMocks();
  });
});
