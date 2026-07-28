export function drawRandomSubset<T>(pool: readonly T[], min: number, max: number): T[] {
  if (pool.length === 0 || min <= 0) return [];
  const upper = Math.min(max, pool.length);
  const lower = Math.min(min, upper);
  const range = Math.max(1, upper - lower + 1);
  const count = Math.floor(Math.random() * range) + lower;
  const arr = [...pool];
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr.slice(0, count);
}
