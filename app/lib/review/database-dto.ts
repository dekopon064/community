import { ReviewFailure } from "./contracts";
import type { ReviewItem, ReviewKind, ListItem, Facts, CandidateContent } from "./contracts";

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new ReviewFailure("unavailable");
  return value as Record<string, unknown>;
}
function string(value: unknown): string { if (typeof value !== "string") throw new ReviewFailure("unavailable"); return value; }
function strings(value: unknown): string[] { if (!Array.isArray(value)) throw new ReviewFailure("unavailable"); return value.map(string); }
function nullable(value: unknown) { return value === null ? null : string(value); }
function choice<T extends string>(value: unknown, choices: readonly T[]): T {
  if (!choices.includes(value as T)) throw new ReviewFailure("unavailable"); return value as T;
}
// Explicit projection is a second boundary against accidentally returning raw payloads.
export function databaseList(data: unknown): ListItem[] {
  if (!Array.isArray(data) || data.length > 25) throw new ReviewFailure("unavailable");
  return data.map((value) => { const v = object(value); return { id: string(v.id), title: string(v.title), sourceName: string(v.sourceName), status: string(v.status), reasons: strings(v.reasons) }; });
}
export function databaseItem(data: unknown, kind: ReviewKind, id: string): ReviewItem {
  const v = object(data); const src = object(v.source);
  if (v.kind !== kind || v.id !== id || !/^[0-9a-f]{64}$/.test(string(v.revision)) || !/^[0-9a-f]{64}$/.test(string(v.version)) || !Array.isArray(v.history)) throw new ReviewFailure("unavailable");
  const base = { id, revision: string(v.revision), version: string(v.version), source: { name: string(src.name), title: string(src.title), url: string(src.url), body: string(src.body) },
    history: v.history.map((entry) => { const h = object(entry); if (Number.isNaN(Date.parse(string(h.at)))) throw new ReviewFailure("unavailable"); return { action: string(h.action), actor: string(h.actor), at: string(h.at), note: string(h.note) }; }) };
  if (kind === "facts") {
    const f = object(v.facts);
    const facts: Facts = {
      productType: choice(f.productType, ["", "event_program", "policy_reference", "living_guide"]), category: choice(f.category, ["", "policy", "program", "event", "youth_space", "living"]),
      scope: choice(f.scope, ["nationwide", "specific", "unknown"]), regions: strings(f.regions), evidence: string(f.evidence), foreignEligibility: choice(f.foreignEligibility, ["eligible", "ineligible", "unknown"]),
      delivery: choice(f.delivery, ["online", "offline", "hybrid", "unknown"]), deadlineKind: choice(f.deadlineKind, ["", "fixed", "none", "closed"]), deadlineOn: string(f.deadlineOn), eventStart: string(f.eventStart), eventEnd: string(f.eventEnd),
    };
    const editableFields = strings(v.editableFields);
    if (editableFields.some((key) => !Object.hasOwn(facts, key)) || typeof v.excludeAllowed !== "boolean") throw new ReviewFailure("unavailable");
    return { ...base, kind, facts, editableFields: editableFields as (keyof Facts)[], excludeAllowed: v.excludeAllowed,
      restoredReviewPending: v.restoredReviewPending === true,
      status: choice(v.status, ["open", "resolved", "excluded"]), reasons: strings(v.reasons), aiStatus: choice(v.aiStatus, ["blocked", "queued", "claimed", "completed", "failed", "cancelled"]) };
  }
  const c = object(v.content); const content = Object.fromEntries(["titleKo", "titleJa", "summaryKo", "summaryJa", "contentKo", "contentJa"].map((key) => [key, string(c[key])])) as CandidateContent;
  const publishedAt = nullable(v.publishedAt);
  if (publishedAt !== null && Number.isNaN(Date.parse(publishedAt))) throw new ReviewFailure("unavailable");
  let programInfo;
  if (["seoul_reservation", "myseoul_program"].includes(base.source.name)) {
    const p = object(v.programInfo);
    if (!Number.isSafeInteger(p.inputFactsVersion) || Number(p.inputFactsVersion) < 1 || !Number.isSafeInteger(p.currentFactsVersion) || Number(p.currentFactsVersion) < 1 ||
        typeof p.inputChanged !== "boolean" || typeof p.canPublish !== "boolean" || p.inputChanged !== (p.inputFactsVersion !== p.currentFactsVersion) || (p.inputChanged && p.canPublish)) throw new ReviewFailure("unavailable");
    programInfo = { inputFactsVersion: Number(p.inputFactsVersion), currentFactsVersion: Number(p.currentFactsVersion), inputChanged: p.inputChanged, canPublish: p.canPublish,
      applicationPeriod: string(p.applicationPeriod), operatingPeriod: string(p.operatingPeriod) };
  }
  return { ...base, kind, content, status: choice(v.status, ["pending", "published", "rejected", "superseded"]), category: choice(v.category, ["", "policy", "program", "event", "youth_space", "living"]), period: string(v.period), publishedAt, publishedId: nullable(v.publishedId), ...(programInfo ? { programInfo } : {}) };
}
