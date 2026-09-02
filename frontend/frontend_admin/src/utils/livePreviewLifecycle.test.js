import test from 'node:test'
import assert from 'node:assert/strict'

import { createLivePreviewLifecycle } from './livePreviewLifecycle.js'

test('invalidating an opener makes its late result stale', () => {
  const lifecycle = createLivePreviewLifecycle({
    requestFrame: () => 1,
    cancelFrame: () => {},
  })

  const first = lifecycle.beginOpen()
  lifecycle.invalidate()
  const second = lifecycle.beginOpen()

  assert.equal(lifecycle.isCurrent(first), false)
  assert.equal(lifecycle.isCurrent(second), true)
})

test('preview loop redraws continuously and stops after invalidation', () => {
  const queued = new Map()
  const cancelled = []
  let nextId = 0
  const lifecycle = createLivePreviewLifecycle({
    requestFrame: (callback) => {
      const id = ++nextId
      queued.set(id, callback)
      return id
    },
    cancelFrame: (id) => {
      cancelled.push(id)
      queued.delete(id)
    },
  })
  const token = lifecycle.beginOpen()
  let draws = 0
  lifecycle.startLoop(token, () => { draws += 1 })

  const runFrame = (id) => {
    const callback = queued.get(id)
    queued.delete(id)
    callback()
  }
  runFrame(1)
  runFrame(2)
  assert.equal(draws, 2)

  lifecycle.invalidate()
  assert.equal(cancelled.includes(3), true)
  assert.equal(queued.size, 0)
})

test('starting analysis can stop painting without invalidating the open source', () => {
  let cancelled = null
  const lifecycle = createLivePreviewLifecycle({
    requestFrame: () => 9,
    cancelFrame: (id) => { cancelled = id },
  })
  const token = lifecycle.beginOpen()
  lifecycle.startLoop(token, () => {})
  lifecycle.stopLoop()

  assert.equal(cancelled, 9)
  assert.equal(lifecycle.isCurrent(token), true)
})
