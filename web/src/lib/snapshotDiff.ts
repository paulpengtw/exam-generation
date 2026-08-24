export interface SnapshotDiffEntry {
  path: string;
  before: unknown;
  after: unknown;
}

function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function appendPath(path: string, segment: string | number): string {
  return typeof segment === "number"
    ? `${path}[${segment}]`
    : path.length > 0
      ? `${path}.${segment}`
      : segment;
}

function collectDiff(
  path: string,
  before: unknown,
  after: unknown,
  changes: SnapshotDiffEntry[],
): void {
  if (Array.isArray(before) && Array.isArray(after)) {
    const itemCount = Math.max(before.length, after.length);
    for (let index = 0; index < itemCount; index += 1) {
      collectDiff(appendPath(path, index), before[index], after[index], changes);
    }
    return;
  }

  if (isObjectRecord(before) && isObjectRecord(after)) {
    const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
    for (const key of keys) {
      collectDiff(appendPath(path, key), before[key], after[key], changes);
    }
    return;
  }

  if (!Object.is(before, after)) {
    changes.push({ path, before, after });
  }
}

export function diffSnapshots(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
): SnapshotDiffEntry[] {
  const changes: SnapshotDiffEntry[] = [];
  const paths = new Set([...Object.keys(before), ...Object.keys(after)]);

  for (const path of paths) {
    collectDiff(path, before[path], after[path], changes);
  }

  return changes;
}
