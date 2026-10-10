import { filterInfo } from './content-filter-store';
import { ReviewFailure } from "./contracts";
import type { RpcClient } from "./database-store";
import { myObject, myText, myStrings, myseoulFacts, myseoulGuidance, myseoulOfficialUrl, myseoulPatchFields, myseoulProfile, myseoulSchema, myseoulReasonFields } from "./myseoul-contract";
import type { MySeoulCommand } from "./myseoul-contract";
import { myseoulRpcFailure } from './myseoul-errors';

export function myseoulItem(raw: unknown, id: string) {
  try {
    const o = myObject(raw), source = myObject(o.source), result = myObject(o.result);
    if (o.id !== id || source.name !== "myseoul_program" || o.schema !== myseoulSchema || o.profile !== myseoulProfile ||
      !Number.isSafeInteger(o.factsVersion) || (o.factsVersion as number) < 1 || !/^[a-f0-9]{64}$/.test(myText(o.revision, 64)) || !/^[a-f0-9]{64}$/.test(myText(o.version, 64)) ||
      !["open", "resolved", "excluded"].includes(myText(o.status, 20)) || !["blocked", "queued", "claimed", "completed", "failed", "cancelled"].includes(String(o.aiStatus)) || !["in_scope", "out_of_scope", "review_required", "not_currently_available"].includes(myText(result.decision, 50)) ||
      !["target", "non_target", "observe_only"].includes(myText(result.disposition, 30))) throw new ReviewFailure("unavailable");
    const editableFields = myStrings(o.editableFields), reasons = myStrings(result.reasons);
    if (editableFields.some(k => !(myseoulPatchFields as readonly string[]).includes(k)) || !Array.isArray(o.history) || o.history.length > 25) throw new ReviewFailure("unavailable");
    const facts = myseoulFacts(o.facts), observedFacts = myseoulFacts(o.observedFacts);
    if (facts.source_revision !== o.revision || observedFacts.source_revision !== o.revision || facts.official_url !== source.url) throw new ReviewFailure("unavailable");
    return { id, filterInfo: filterInfo(o.filterInfo, String(o.revision)), revision: myText(o.revision), version: myText(o.version), schema: myseoulSchema, profile: myseoulProfile, factsVersion: o.factsVersion,
      source: { name: "myseoul_program", title: myText(source.title, 500), url: myseoulOfficialUrl(source.url), body: myText(source.body) },
      facts, observedFacts, status: myText(o.status), aiStatus: myText(o.aiStatus, 20), editableFields, restoredReviewPending: o.restoredReviewPending === true,
      residenceReview: residenceReview(o.residenceReview),
      activityReview: {confirmed: confirmation(o.activityReview)},
      bodyReview: bodyReview(o.bodyReview),
      result: { decision: myText(result.decision), disposition: myText(result.disposition), scope: myText(result.scope), application: myText(result.application), quality: myText(result.quality), public_category: myText(result.public_category), reasons },
      reasonGuidance: reasons.map(code => ({ code, text: myseoulGuidance(code), supported: myseoulReasonFields(code).length > 0 })),
      history: o.history.map(raw => { const h = myObject(raw); return { action: myText(h.action, 30), actor: myText(h.actor, 36), at: myText(h.at, 100), note: myText(h.note, 4000), fields: myStrings(h.fields) }; }) };
  } catch { throw new ReviewFailure("unavailable"); }
}

function residenceReview(raw: unknown) {
  if (raw === undefined) return {confirmed:false,basis:'unconfirmed'};
  const v = myObject(raw);
  if (typeof v.confirmed !== 'boolean' || !['operator_no_restriction','source_evidence','unconfirmed'].includes(String(v.basis))) throw new ReviewFailure('unavailable');
  return {confirmed:v.confirmed,basis:String(v.basis)};
}
function confirmation(raw: unknown) {
  if(raw===undefined)return false;
  const o=myObject(raw);if(typeof o.confirmed!=='boolean')throw new ReviewFailure('unavailable');return o.confirmed;
}
function bodyReview(raw: unknown) {
  if(raw===undefined)return {required:false,confirmed:false,imageUrl:null};
  const o=myObject(raw);if(typeof o.required!=='boolean')throw new ReviewFailure('unavailable');
  const imageUrl=o.imageUrl===null?null:myText(o.imageUrl,2048);
  if(imageUrl&&!/^https:\/\/global\.seoul\.go\.kr\/contents\/commoneditor\/[^?#\s]+\.(png|jpe?g|webp|gif)$/i.test(imageUrl))throw new ReviewFailure('unavailable');
  return {required:o.required,confirmed:confirmation(o),imageUrl};
}

export class MySeoulReviewStore {
  private client: RpcClient;
  constructor(client: RpcClient) { this.client = client; }
  private async invoke(name: string, args: Record<string, unknown>) {
    try {
      const { data, error } = await this.client.rpc(name, args);
      if (error) throw myseoulRpcFailure(error);
      if (data === null || data === undefined) throw new ReviewFailure("unavailable");
      return data;
    } catch (e) { if (e instanceof ReviewFailure) throw e; throw new ReviewFailure("unavailable"); }
  }
  async get(id: string) { return myseoulItem(await this.invoke("admin_myseoul_program_detail", { p_id: id }), id); }
  async execute(id: string, c: MySeoulCommand, actor: string) {
    if(c.action==='confirm_body')return myseoulItem(await this.invoke('admin_myseoul_body_confirm',{p_id:id,p_revision:c.revision,p_version:c.version,p_description:c.description,p_actor:actor}),id);
    if(c.action==='confirm_activity')return myseoulItem(await this.invoke('admin_myseoul_activity_confirm',{p_id:id,p_revision:c.revision,p_version:c.version,p_filter_version:c.filterVersion,p_filters:Object.fromEntries(c.fields.map(k=>[k,c.data[k]])),p_patch:c.patch,p_actor:actor}),id);
    if (c.action === 'confirm_residence') return myseoulItem(await this.invoke('admin_myseoul_residence_confirm', {p_id:id,p_revision:c.revision,p_version:c.version,p_restricted:c.restricted,p_scope:c.scope,p_condition:c.condition,p_evidence:c.evidence,p_actor:actor,p_request:c.requestId}),id);
    const args: Record<string, unknown> = { p_id: id, p_revision: c.revision, p_version: c.version, p_actor: actor };
    if (c.action === "save_facts") args.p_patch = c.patch;
    else args.p_note = c.note;
    return myseoulItem(await this.invoke(c.action === "save_facts" ? "admin_myseoul_program_save_v2" : "admin_myseoul_program_exclude", args), id);
  }
}
