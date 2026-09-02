import test from 'node:test'
import assert from 'node:assert/strict'

let helpers = {}
try {
  helpers = await import('./mtmcRuntimeStatus.js')
} catch (_) {
  // RED: the production helper does not exist yet.
}

test('failed strong ReID takes precedence over its degraded fallback metadata', () => {
  assert.equal(helpers.runtimeTone?.({ ready: false, degradedReason: 'shape mismatch' }), 'danger')
  assert.equal(helpers.runtimeLabel?.({ ready: false, degradedReason: 'shape mismatch' }), '失败')
  assert.equal(helpers.runtimeRisk?.({ ready: false, degradedReason: 'shape mismatch' }), 'shape mismatch')
  assert.deepEqual(helpers.runtimeOverallStatus?.({
    models: {
      personReid: { ready: false, runtimeState: 'failed', degraded: true, degradedReason: 'shape mismatch' },
    },
  }), { tone: 'danger', label: '存在失败' })
})

test('successful fallback is warning degradation rather than failure', () => {
  const degraded = { ready: true, runtimeState: 'degraded', degraded: true, degradedReason: 'strong unavailable' }

  assert.equal(helpers.runtimeTone?.(degraded), 'warning')
  assert.equal(helpers.runtimeLabel?.(degraded), '降级')
  assert.deepEqual(helpers.runtimeOverallStatus?.({
    models: { personReid: degraded },
  }), { tone: 'warning', label: '存在降级' })
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
    tone: 'warning',
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

test('same model with different camera health renders ready and failed rows', () => {
  const rows = helpers.runtimeModelRows?.({
    models: {
      vehicleReid: {
        mixed: true,
        selectedModelKey: 'vehicle-reid-v1',
        byCamera: {
          1: {
            selectedModelKey: 'vehicle-reid-v1', modelVersion: 'vehicle.onnx',
            backend: 'vehicle-onnx', provider: 'onnxruntime-cpu',
            ready: true, runtimeState: 'ready', degraded: false,
          },
          2: {
            selectedModelKey: 'vehicle-reid-v1', modelVersion: 'vehicle.onnx',
            backend: 'vehicle-onnx', provider: 'onnxruntime-cpu',
            ready: false, runtimeState: 'failed', degraded: true,
            degradedReason: 'camera 2 ORT crash',
          },
        },
      },
    },
  })

  assert.deepEqual(rows.map(({ cameraId, selectedModelKey, tone, statusLabel }) => ({
    cameraId, selectedModelKey, tone, statusLabel,
  })), [
    { cameraId: '1', selectedModelKey: 'vehicle-reid-v1', tone: 'success', statusLabel: '就绪' },
    { cameraId: '2', selectedModelKey: 'vehicle-reid-v1', tone: 'danger', statusLabel: '失败' },
  ])
})

test('plate OCR and local tracker failures are visible with Chinese labels and affect risks', () => {
  const runtime = {
    models: {
      plateOcr: {
        selectedModelKey: 'plate-ocr', ready: false, runtimeState: 'failed',
        degraded: true, degradedReason: 'OCR callable crash',
      },
      localTracker: {
        selectedModelKey: 'bytetrack', ready: false, runtimeState: 'failed',
        degraded: true, degradedReason: 'tracker update crash',
      },
    },
  }

  const rows = helpers.runtimeModelRows?.(runtime)
  assert.deepEqual(rows.map(({ role, roleLabel, tone }) => ({ role, roleLabel, tone })), [
    { role: 'plateOcr', roleLabel: '车牌 OCR', tone: 'danger' },
    { role: 'localTracker', roleLabel: '本地跟踪器', tone: 'danger' },
  ])
  assert.equal(
    helpers.runtimeRiskSummary?.(runtime),
    '车牌 OCR：OCR callable crash；本地跟踪器：tracker update crash',
  )
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

test('topology draft explicitly preserves overlap type and zero weight', () => {
  assert.deepEqual(helpers.normalizeTopologyDraft?.({
    fromCameraId: 1,
    toCameraId: 2,
    minTransitSec: 0,
    maxTransitSec: 30,
    edgeType: 'overlap',
    weight: 0,
  }), {
    ok: true,
    value: {
      fromCameraId: 1,
      toCameraId: 2,
      minTransitSec: 0,
      maxTransitSec: 30,
      edgeType: 'overlap',
      weight: 0,
    },
  })
})

test('topology draft rejects self edges and reversed transit windows', () => {
  assert.equal(helpers.normalizeTopologyDraft?.({
    fromCameraId: 1, toCameraId: 1, minTransitSec: 0, maxTransitSec: 10,
  }).ok, false)
  assert.equal(helpers.normalizeTopologyDraft?.({
    fromCameraId: 1, toCameraId: 2, minTransitSec: 20, maxTransitSec: 10,
  }).ok, false)
})

test('camera observation summary exposes active and lost per-camera state', () => {
  assert.equal(helpers.cameraObservationSummary?.({
    cameraObservations: {
      2: { active: false, lostAt: 20 },
      1: { active: true, lastObservedAt: 21 },
    },
  }), '#1 在线 · #2 丢失')
})

test('candidate score parts expose best second margin and all components', () => {
  assert.deepEqual(helpers.candidateScoreParts?.({
    finalScore: 0.7,
    reidScore: 0.8,
    topologyScore: 1,
    timeScore: 0.5,
    secondBestScore: 0.65,
    matchMargin: 0.05,
  }), {
    best: 0.7,
    second: 0.65,
    margin: 0.05,
    appearance: 0.8,
    topology: 1,
    time: 0.5,
    final: 0.7,
  })
})

test('stop outcome only completes for a stopped response', () => {
  assert.deepEqual(helpers.stopSessionOutcome?.({ status: 'pending', retryable: true }), {
    status: 'pending', completed: false, retryable: true,
  })
  assert.deepEqual(helpers.stopSessionOutcome?.({ status: 'stopped', retryable: false }), {
    status: 'stopped', completed: true, retryable: false,
  })
})

test('gallery degradation is included in the operator risk summary', () => {
  assert.equal(helpers.runtimeRiskSummary?.({
    models: {},
    gallery: { ready: false, degraded: true, error: 'index corrupt' },
  }), '人员底库：index corrupt')
})
