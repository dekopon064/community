import type { CandidateItem, ReviewItem } from './contracts';

// Validated server image metadata is the capability. Source names are not a UI
// allowlist; missing server metadata must never be invented as an empty image.
export function canEditCandidateImage(item: ReviewItem | null): item is CandidateItem & { image: NonNullable<CandidateItem['image']> } {
  return item?.kind === 'candidates'
    && item.status === 'pending' && !item.publishedId && Boolean(item.image);
}
