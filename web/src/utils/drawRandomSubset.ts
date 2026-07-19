export function drawRandomSubset<T>(pool: readonly T[], min: number, max: number): T[] {
  if (pool.length === 0 || min <= 0) return [];
  const upper = Math.min(max, pool.length);
  const lower = Math.min(min, upper);
  const range = Math.max(1, upper - lower + 1);
  const count = Math.floor(Math.random() * range) + lower;
  const shuffled = [...pool].sort(() => Math.random() - 0.5);
  return shuffled.slice(0, count);
}
