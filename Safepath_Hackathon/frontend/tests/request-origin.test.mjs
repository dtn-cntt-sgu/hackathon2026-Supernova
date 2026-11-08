import test from 'node:test';
import assert from 'node:assert/strict';
import { isSameOriginMutation } from '../src/lib/request-origin.ts';
test('cookie mutation checks configured public origin rather than normalized internal URL', () => {
  assert.equal(isSameOriginMutation('https://safe.example', 'https://safe.example', 'http://localhost:3000/api/v1/user/incidents'), true);
  for (const origin of [null, 'null', 'https://evil.example', 'http://safe.example', 'https://safe.example.evil.org']) {
    assert.equal(isSameOriginMutation(origin, 'https://safe.example', 'http://localhost:3000/api'), false);
  }
});
