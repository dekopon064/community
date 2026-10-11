import { ReviewFailure } from "./contracts";
import type { CandidateItem, ReviewItem } from "./contracts";

// A public edit is a separate operation, never an acknowledgement of source changes.
export function canEditPublishedBody(item: ReviewItem | null): item is CandidateItem & { publishedBodyVersion: string } {
  return item?.kind === "candidates" && item.status === "published" && Boolean(item.publishedId) &&
    /^[a-f0-9]{64}$/.test(item.publishedBodyVersion ?? "") && !item.programInfo?.inputChanged;
}
export function publishedBodyCommand(item: ReviewItem, contentKo: string, contentJa: string, note: string) {
  if (!canEditPublishedBody(item)) throw new ReviewFailure("conflict");
  return { action: "save_published_body" as const, revision: item.revision, version: item.version,
    publicVersion: item.publishedBodyVersion, contentKo, contentJa, note };
}
