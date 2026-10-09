export const COMMENT_LIMIT = 1000;
export const COMMENT_PAGE_SIZE = 20;
export const RESIDENT_CODE = /^[0-9]{5}(?![\s\S])/;
// An old open composer may send its former code. SQL rejects it with the
// existing identity fence; own accepted receipts remain readable by request ID.
export const EXPECTED_RESIDENT_CODE = /^(?:[0-9]{5}|[A-HJKMNP-Z2-9]{6})(?![\s\S])/;
export const COMMENT_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export type CommentItem = { id: string; residentCode: string; body: string; createdAt: string; canDelete: boolean };
export type CommentCursor = { at: string; id: string };
export type CommentPage = { items: CommentItem[]; next: CommentCursor | null; viewer: { signedIn: boolean; code: string | null; moderator: boolean } };
export function normalizeComment(value: string) { return value.replace(/\r\n?/g, "\n").trim(); }
export function validComment(value: unknown): value is string {
  if (typeof value !== "string" || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value) || /[\uD800-\uDFFF]/u.test(value)) return false;
  const length = [...normalizeComment(value)].length;
  return length > 0 && length <= COMMENT_LIMIT;
}
export function validCursor(at: unknown, id: unknown): boolean {
  return typeof at === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(at) && Number.isFinite(Date.parse(at)) && typeof id === "string" && COMMENT_UUID.test(id);
}

// Only explicit public fields cross this boundary; never spread an RPC payload.
export function commentPage(data: unknown, signedIn: boolean, moderator: boolean): CommentPage {
  const row = data as { items?: unknown; next?: unknown; code?: unknown };
  if (!row || !Array.isArray(row.items) || row.items.length > COMMENT_PAGE_SIZE || (row.code !== null && (typeof row.code !== "string" || !RESIDENT_CODE.test(row.code)))) throw new Error("invalid_comment_response");
  const items = row.items.map((raw): CommentItem => {
    const item = raw as CommentItem;
    if (!item || typeof item.id !== "string" || !COMMENT_UUID.test(item.id) || typeof item.residentCode !== "string" || !RESIDENT_CODE.test(item.residentCode) || !validComment(item.body) || typeof item.createdAt !== "string" || !Number.isFinite(Date.parse(item.createdAt)) || typeof item.canDelete !== "boolean") throw new Error("invalid_comment_response");
    return { id: item.id, residentCode: item.residentCode, body: item.body, createdAt: item.createdAt, canDelete: signedIn && item.canDelete };
  });
  if (new Set(items.map(item => item.id)).size !== items.length) throw new Error("invalid_comment_response");
  const next = row.next as CommentCursor | null;
  if (next !== null && (!next || !validCursor(next.at, next.id))) throw new Error("invalid_comment_response");
  return { items, next: next ? { at: next.at, id: next.id } : null, viewer: { signedIn, code: signedIn ? row.code as string | null : null, moderator: signedIn && moderator } };
}
