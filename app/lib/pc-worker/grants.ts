import { createHmac } from 'node:crypto';
import { pcWorkerSchema, workerGrantInput } from './contracts';

// Domain-separated capability key; the existing server secret is NEVER returned.
export function issueWorkerGrant(input: ReturnType<typeof workerGrantInput>, actor: string, origin: string,
  config: { project: string; key: string }, now = Date.now()) {
  if (input.hello.project !== config.project || config.key.length < 24) throw Error('worker_configuration');
  const iat = Math.floor(now / 1000);
  const payload = Buffer.from(JSON.stringify({ schema: pcWorkerSchema, operation: input.action, command: input.command,
    requestId: input.requestId, instance: input.hello.instance, challenge: input.hello.challenge, project: config.project,
    actor, origin, catalog:input.hello.catalog, iat, exp: iat + 60 })).toString('base64url');
  const key = createHmac('sha256', config.key).update('machimoa.pc-worker.capability.v1').digest();
  return `pcw1.${payload}.${createHmac('sha256',key).update(payload).digest('base64url')}`;
}
