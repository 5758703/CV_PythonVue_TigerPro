import test from 'node:test'
import assert from 'node:assert/strict'

let helpers = {}
try {
  helpers = await import('./mtmcRuntimeStatus.js')
} catch (_) {
  // RED: the production helper does not exist yet.
}

test('degraded strong ReID is visible and never labeled ready', () => {
  assert.equal(helpers.runtimeTone?.({ ready: false, degradedReason: 'shape mismatch' }), 'danger')
  assert.equal(helpers.runtimeLabel?.({ ready: false, degradedReason: 'shape mismatch' }), '降级')
  assert.equal(helpers.runtimeRisk?.({ ready: false, degradedReason: 'shape mismatch' }), 'shape mismatch')
})

test('ready runtime without degradation is presented as ready', () => {
  assert.equal(helpers.runtimeTone?.({ ready: true, degraded: false }), 'success')
  assert.equal(helpers.runtimeLabel?.({ ready: true, degraded: false }), '就绪')
})

test('configured asset stays pending before a real inference observation', () => {
  const pending = {
    configured: true,
    assetPresent: true,
    configuredModelKey: 'osnet-x1-0',
    selectedModelKey: null,
    ready: null,
    runtimeState: 'pending',
  }

  assert.equal(helpers.runtimeTone?.(pending), 'info')
  assert.equal(helpers.runtimeLabel?.(pending), '等待探测')
  assert.deepEqual(helpers.runtimeModelRows?.({ models: { personReid: pending } }), [{
    role: 'personReid',
    roleLabel: '人员 ReID',
    cameraId: null,
    selectedModelKey: 'osnet-x1-0',
    modelVersion: '—',
    ready: null,
    degraded: undefined,
    degradedReason: null,
    backend: '—',
    provider: '—',
    inputSize: '—',
    embeddingDim: null,
    tone: 'info',
    statusLabel: '等待探测',
  }])
})

test('model rows preserve actual runtime key version provider input and dimension', () => {
  const rows = helpers.runtimeModelRows?.({
    models: {
      personReid: {
        selectedModelKey: 'opencv-person-reid-youtu',
        modelVersion: 'youtu-v3',
        ready: true,
        degraded: true,
        degradedReason: 'strong: shape mismatch',
        provider: 'youtu-reid-opencv',
        inputSize: [128, 256],
        embeddingDim: 768,
      },
    },
  })

  assert.deepEqual(rows, [{
    role: 'personReid',
    roleLabel: '人员 ReID',
    cameraId: null,
    selectedModelKey: 'opencv-person-reid-youtu',
    modelVersion: 'youtu-v3',
    ready: true,
    degraded: true,
    degradedReason: 'strong: shape mismatch',
    backend: '—',
    provider: 'youtu-reid-opencv',
    inputSize: '128×256',
    embeddingDim: 768,
    tone: 'danger',
    statusLabel: '降级',
  }])
})

test('mixed camera models render independent truthful rows', () => {
  const rows = helpers.runtimeModelRows?.({
    models: {
      personReid: {
        mixed: true,
        selectedModelKey: null,
        provider: null,
        byCamera: {
          1: {
            selectedModelKey: 'osnet-x1-0', modelVersion: 'osnet-a.onnx',
            backend: 'strong-onnx', provider: 'onnxruntime-cuda',
            inputSize: [128, 256], embeddingDim: 512,
            ready: true, degraded: false,
          },
          2: {
            selectedModelKey: 'opencv-person-reid-youtu', modelVersion: 'youtu-b.onnx',
            backend: 'youtu-reid-opencv', provider: 'opencv-dnn-cpu',
            inputSize: [128, 256], embeddingDim: 768,
            ready: true, degraded: true, degradedReason: 'strong unavailable',
          },
        },
      },
    },
  })

  assert.equal(rows.length, 2)
  assert.deepEqual(rows.map((row) => ({
    cameraId: row.cameraId,
    key: row.selectedModelKey,
    backend: row.backend,
    provider: row.provider,
    dim: row.embeddingDim,
  })), [
    { cameraId: '1', key: 'osnet-x1-0', backend: 'strong-onnx', provider: 'onnxruntime-cuda', dim: 512 },
    { cameraId: '2', key: 'opencv-person-reid-youtu', backend: 'youtu-reid-opencv', provider: 'opencv-dnn-cpu', dim: 768 },
  ])
})

test('association breakdown keeps final association score distinct from event score', () => {
  const scores = helpers.associationScoreParts?.({
    appearanceScore: 0.72,
    topologyScore: 0.8,
    timeScore: 0.5,
    margin: 0.03,
    finalScore: 0.288,
    evidence: { eventScore: 0.91 },
  })

  assert.deepEqual(scores, {
    appearance: 0.72,
    topology: 0.8,
    time: 0.5,
    margin: 0.03,
    final: 0.288,
  })
  assert.notEqual(scores.final, 0.91)
})

test('association breakdown remains compatible with legacy nested scores', () => {
  assert.deepEqual(helpers.associationScoreParts?.({
    scores: { reid: 0.61, topology: 1, time: 0.7, final: 0.427 },
    evidence: { matchMargin: 0.08 },
  }), {
    appearance: 0.61,
    topology: 1,
    time: 0.7,
    margin: 0.08,
    final: 0.427,
  })
})

test('effective directed policy text exposes missing-edge rejection', () => {
  assert.equal(helpers.topologyPolicyText?.({
    directed: true,
    authoritative: true,
    missingEdgePolicy: 'reject',
    edges: [{ fromCameraId: 1, toCameraId: 2 }],
  }), '有向权威策略 · 缺边拒绝 · 1 条边')
})

test('missing topology snapshot is not fabricated as an empty undirected policy', () => {
  assert.equal(helpers.topologyPolicyText?.(), '等待策略快照')
  assert.equal(helpers.topologyPolicyText?.({}), '等待策略快照')
})

test('budget rows preserve every scheduling decision counter', () => {
  assert.deepEqual(helpers.runtimeBudgetRows?.({
    personReid: {
      limitPerFrame: 1,
      considered: 5,
      eligible: 3,
      queued: 2,
      consumed: 2,
      budgetSkipped: 1,
      samplerSkipped: 2,
    },
  }), [{
    role: 'personReid',
    label: '人员 ReID',
    limitPerFrame: 1,
    considered: 5,
    eligible: 3,
    queued: 2,
    consumed: 2,
    budgetSkipped: 1,
    samplerSkipped: 2,
  }])
})

test('gallery degradation is included in the operator risk summary', () => {
  assert.equal(helpers.runtimeRiskSummary?.({
    models: {},
    gallery: { ready: false, degraded: true, error: 'index corrupt' },
  }), '人员底库：index corrupt')
})
