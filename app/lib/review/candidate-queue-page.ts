import { ReviewFailure, type ListItem } from "./contracts";

const pageSize = 25;
const maxPage = Math.floor(999999 / pageSize);

// Reuse the authorized queue RPC's scope and ordering, including published
// My서울+ entries awaiting source-change review. Probe sparsely for large queues.
export async function candidateQueuePage(read: (offset: number) => Promise<ListItem[]>, offset: number) {
  const pages = new Map<number, ListItem[]>();
  async function page(index: number) {
    const cached = pages.get(index);
    if (cached) return cached;
    const rows = await read(index * pageSize);
    pages.set(index, rows);
    return rows;
  }
  const requested = Math.floor(offset / pageSize);
  let high = requested;
  let low = -1;
  let rows = await page(high);
  while (rows.length === pageSize) {
    low = high;
    if (high === maxPage) throw new ReviewFailure("unavailable");
    high = Math.min(maxPage, high + Math.max(1, high - requested));
    rows = await page(high);
  }
  // An empty probe may be beyond the last page, including after removing
  // the only candidate on the requested page.
  while (!rows.length && high - low > 1) {
    const middle = Math.floor((low + high) / 2);
    const probe = await page(middle);
    if (probe.length === pageSize) low = middle;
    else { high = middle; rows = probe; }
  }
  const total = high * pageSize + rows.length;
  const index = Math.min(requested, Math.max(0, Math.ceil(total / pageSize) - 1));
  return { items: await page(index), total, offset: index * pageSize, hasMore: (index + 1) * pageSize < total };
}
