import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { reviewDatabase } from './review_queue_test_fixture.mjs';

// The Python collector sees a synthetic list and detail. Replay its observation
// through the real SQL functions in an isolated, in-memory PostgreSQL database.
const scripts = new URL('./', import.meta.url);
const python = process.env.MACHIMOA_TEST_PYTHON || 'python';
const observation = JSON.parse(execFileSync(python, ['-B', '-X', 'utf8', '-c', [
  'from test_culture_portal import Fake',
  'import json',
  'collector = Fake()',
  'collector.run()',
  "args, = [args for name, args in collector.calls if name == 'observe_culture_portal_event']",
  'print(json.dumps(args))',
].join('\n')], { cwd: scripts, encoding: 'utf8' }));

const { db, query, rpc, source, job } = await reviewDatabase();
const apply = async name => db.exec((await readFile(new URL('../supabase/migrations/' + name, import.meta.url), 'utf8')).replaceAll('\r\n', '\n'));
const facts = () => rpc('admin_review_list', ['facts', 0, 25]);
const queue = () => rpc('admin_review_ai_queue', [0, 25, '{}']);
try {
  await apply('20261002000100_admin_review_trash.sql');
  await apply('20261002000200_admin_review_trash_publication.sql');
  await apply('20261002000300_myseoul_program_contract.sql');
  await apply('20261002000400_myseoul_program_ai.sql');
  const queuedIds = [];
  for (const origin of ['seoul_reservation', 'myseoul_program']) {
    queuedIds.push(await job(await source('waiting-' + origin, origin)));
  }
  const before = await queue();
  assert.deepEqual(before.items.map(row => row.jobId).sort(), queuedIds.sort());

  // Exercise the same detail wrapper used by main for general viewing.
  // Only its dependency (the candidate column) and definition are needed here.
  const outings = await readFile(new URL('../supabase/migrations/20261126104626_program_outings.sql', import.meta.url), 'utf8');
  await db.exec('alter table machimoa_review.curation_candidates add column general_viewing jsonb');
  const wrapper = outings.slice(outings.indexOf('alter function machimoa_review.admin_review_item'), outings.indexOf('create function public.admin_review_save_candidate_viewing'));
  await db.exec(wrapper);
  await apply('20261127045726_seoul_culture_portal_collection.sql');
  assert.deepEqual(await facts(), []);
  await query("update machimoa_review.ingest_sources set enabled=true where source_id='seoul_culture_portal' and not enabled and permission_status='testing_only'");
  const [{run_id}] = await query("select run_id from public.start_ingest_run('seoul_culture_portal', 900)");
  const observe = () => rpc('observe_culture_portal_event', [run_id, observation.p_event, observation.p_review]);
  const first = await observe();
  assert.equal(first.outcome, 'new_review');
  assert.equal(first.reviewQueued, true);
  const snapshot = await facts();
  const [row] = snapshot;
  assert.equal(snapshot.length, 1);
  assert.equal(row.id, first.sourceItemId);
  assert.equal(row.title, observation.p_event.title);
  assert.equal(row.sourceName, 'seoul_culture_portal');
  assert.equal((await observe()).outcome, 'unchanged');
  assert.deepEqual(await facts(), snapshot);
  const detail = await rpc('admin_review_detail', ['facts', row.id]);
  assert.equal(detail.collectionReview.observedRevision, observation.p_event.revision_hash);
  assert.equal(detail.aiStatus, 'blocked');
  assert.deepEqual((await queue()).items, before.items);
  const jobs = await query('select processing_stage, status from machimoa_review.processing_jobs where source_item_id=$1', [row.id]);
  assert.deepEqual(jobs, [{processing_stage: 'content_review', status: 'queued'}]);
  console.log('PASS festival facts 0 -> 1 -> 1; confirmed detail and exactly one review job; both original AI jobs unchanged');
} finally {
  await db.close();
}
