export type ReviewKind = "facts" | "candidates";
export type Category = "" | "policy" | "program" | "event" | "youth_space" | "living";
export type Facts = {
  productType: "" | "event_program" | "policy_reference" | "living_guide";
  category: Category;
  scope: "nationwide" | "specific" | "unknown";
  regions: string[];
  evidence: string;
  foreignEligibility: "eligible" | "ineligible" | "unknown";
  delivery: "online" | "offline" | "hybrid" | "unknown";
  deadlineKind: "" | "fixed" | "none" | "closed";
  deadlineOn: string;
  eventStart: string;
  eventEnd: string;
};
export type CandidateContent = {
  titleKo: string; summaryKo: string; contentKo: string;
  titleJa: string; summaryJa: string; contentJa: string;
};
export type CandidateImageSelection = { mode: "source" | "override" | "none"; url: string | null };
export type CandidateImage = CandidateImageSelection & { sourceUrl: string | null };
export type History = { action: string; actor: string; at: string; note: string; changeLabel?: string };
type BaseItem = {
  id: string; revision: string; version: string;
  source: { name: string; title: string; url: string; body: string };
  history: History[];
};
export type FactsItem = BaseItem & {
  kind: "facts"; facts: Facts; reasons: string[];
  editableFields?: (keyof Facts)[];
  excludeAllowed?: boolean;
  restoredReviewPending?: boolean;
  status: "open" | "resolved" | "excluded";
  aiStatus: "blocked" | "queued" | "claimed" | "completed" | "failed" | "cancelled";
};
export type CandidateItem = BaseItem & {
  kind: "candidates"; content: CandidateContent;
  status: "pending" | "published" | "rejected" | "superseded";
  category: Category; period: string;
  publishedAt: string | null; publishedId: string | null; publishedSlug?: string | null;
  image?: CandidateImage;
  programInfo?: { inputFactsVersion: number; currentFactsVersion: number; inputChanged: boolean; canPublish: boolean; changeReviewed?: boolean; changedFields?: string[]; comparisonAvailable?: boolean; applicationPeriod: string; operatingPeriod: string };
};
export type ReviewItem = FactsItem | CandidateItem;
export type ListItem = { id: string; title: string; sourceName: string; status: string; reasons: string[] };
export type Preconditions = { revision: string; version: string };
export type ReviewCommand =
  | (Preconditions & { action: "save_facts"; facts: Facts; confirmRestored?: true })
  | (Preconditions & { action: "exclude"; note: string })
  | (Preconditions & { action: "save_candidate"; content: CandidateContent; imageSelection?: CandidateImageSelection })
  | (Preconditions & { action: "review_change"; disposition: "no_impact" | "edited"; note: string; content?: CandidateContent })
  | (Preconditions & { action: "publish" })
  | (Preconditions & { action: "reject"; note: string });

// Implementations must compare both preconditions and commit content/state/history
// atomically. Only an explicitly selected adapter may handle requests.
export interface ReviewStore {
  readonly mode: "database" | "local-fixture";
  list(kind: ReviewKind, offset?: number): Promise<ListItem[]>;
  get(kind: ReviewKind, id: string): Promise<ReviewItem>;
  execute(kind: ReviewKind, id: string, command: ReviewCommand, actor: string): Promise<ReviewItem>;
}
export type ReviewFailureCode = "not_connected" | "not_found" | "conflict" | "already_processed" | "publish_failed" | "invalid_input" | "unavailable" | "program_input_changed" | "program_unavailable" | "trash_expired" | "trash_source_changed" | "trash_processing_active" | "trash_already_published";
export class ReviewFailure extends Error {
  readonly code: ReviewFailureCode;
  readonly fields: Record<string, string>;
  constructor(code: ReviewFailureCode, fields: Record<string, string> = {}) {
    super(code); this.code = code; this.fields = fields;
  }
}
