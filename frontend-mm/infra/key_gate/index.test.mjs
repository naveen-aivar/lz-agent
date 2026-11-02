// Run with: node --test infra/key_gate
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const gate = createRequire(import.meta.url)('./index.js');

test('with no environment the gate is the TCO gate it always was', () => {
  const config = gate.settings({});
  assert.deepEqual(config, {
    secretId: 'ingram-mm-dashboard/tco-access-key',
    upstream: 'sdcr1ipp07.execute-api.us-east-1.amazonaws.com',
    prefix: '/agents/tco/api',
    stage: 'dev',
    label: 'tco',
  });
  assert.equal(gate.upstreamPath(config, '/agents/tco/api/jobs'), '/dev/jobs');
});

test('the environment makes it the orchestrator gate, with its own secret and API', () => {
  const config = gate.settings({
    PREFIX: '/agents/orchestrator/api',
    STAGE: 'dev',
    UPSTREAM: 'aafoxbd4f1.execute-api.us-east-1.amazonaws.com',
    SECRET_ID: 'ingram-mm-dashboard/orchestrator-access-key',
    LABEL: 'orchestrator',
  });
  assert.equal(config.secretId, 'ingram-mm-dashboard/orchestrator-access-key');
  assert.equal(config.upstream, 'aafoxbd4f1.execute-api.us-east-1.amazonaws.com');
  assert.equal(gate.upstreamPath(config, '/agents/orchestrator/api/jobs/abc/start'), '/dev/jobs/abc/start');
  assert.equal(gate.upstreamPath(config, '/agents/orchestrator/api'), '/dev');
});

test('a path that does not start with the prefix goes through as it came (the origin path already added the stage)', () => {
  const config = gate.settings({});
  assert.equal(gate.upstreamPath(config, '/dev/jobs'), '/dev/jobs');
  assert.equal(gate.upstreamPath(config, '/agents/orchestrator/api/jobs'), '/agents/orchestrator/api/jobs');
});

test('a key stored with a line break or spaces around it is trimmed, and an empty secret stays empty', () => {
  assert.equal(gate.cleanKey('abc123\n'), 'abc123');
  assert.equal(gate.cleanKey('  abc123 \r\n'), 'abc123');
  assert.equal(gate.cleanKey(undefined), '');
  assert.equal(gate.cleanKey('\n'), '');
});
