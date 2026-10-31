import test from 'node:test'
import assert from 'node:assert/strict'
import { getContextOrgId, setContextOrgId, retainValidContext, matchesPermission } from './organizationContext.js'

test('work identity uses tab session storage and rejects malformed identifiers', () => {
  const values = new Map()
  globalThis.sessionStorage = { getItem: k => values.get(k), setItem: (k, v) => values.set(k, v), removeItem: k => values.delete(k) }
  setContextOrgId(210)
  assert.equal(getContextOrgId(), 210)
  for (const value of ['bad', 0, -1, 2.5, null]) {
    setContextOrgId(value)
    assert.equal(getContextOrgId(), null)
  }
})

test('revoked context is cleared; a valid selected context is retained', () => {
  assert.equal(retainValidContext(210, [{ orgId: 210 }]), 210)
  assert.equal(retainValidContext(210, [{ orgId: 220 }]), null)
})

test('frontend permission matching agrees with segment wildcard backend semantics', () => {
  assert.equal(matchesPermission(['system:user:*'], 'system:user:edit'), true)
  assert.equal(matchesPermission(['system:user:query'], 'system:user:edit'), false)
  assert.equal(matchesPermission(['system:*:query'], ['system:dept:edit', 'system:dept:query']), true)
})
