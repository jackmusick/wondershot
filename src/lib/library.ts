import type { Capture, LibraryGroup } from '$lib/types';

const DAY = 86_400_000;

function startOfDay(ms: number): number {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export function groupByDate(captures: Capture[], now: number): LibraryGroup[] {
  const todayStart = startOfDay(now);
  const buckets = new Map<number, Capture[]>();
  for (const c of captures) {
    const key = startOfDay(c.createdAt);
    (buckets.get(key) ?? buckets.set(key, []).get(key)!).push(c);
  }
  const keys = [...buckets.keys()].sort((a, b) => b - a);
  return keys.map((key) => {
    const items = buckets.get(key)!.sort((a, b) => b.createdAt - a.createdAt);
    let label: string;
    if (key === todayStart) label = 'Today';
    else if (key === todayStart - DAY) label = 'Yesterday';
    else label = new Date(key).toLocaleDateString();
    return { label, items };
  });
}
