import assert from 'node:assert/strict'
import test from 'node:test'
import * as scenarioState from './scenarioState.js'

import {
  PHASE_ONE_ROUTE_KEYS,
  buildScenarioApiDocumentation,
  clampImagePoint,
  deriveMaskMetrics,
  isAcceptedImageCandidate,
  isCurrentPreviewRequest,
  normalizeWorkbenchResult,
  scaleDetectionGeometry,
  isLatestScenarioRequest,
  resolveFixedModelKey,
  resolveWorkbench,
  serializeScenarioForm,
  undoSegmentationPrompt,
  validateWorkbenchState,
} from './scenarioState.js'

test('resolves each supported workbench type', () => {
  assert.equal(resolveWorkbench('segmentation'), 'segmentation')
  assert.equal(resolveWorkbench('vehicle_reid'), 'vehicle_reid')
  assert.equal(resolveWorkbench('plate_detection'), 'plate_detection')
  assert.equal(resolveWorkbench('obb_detection'), 'obb_detection')
})

test('marks an unknown workbench type unsupported', () => {
  assert.equal(resolveWorkbench('not-registered'), null)
})

test('serializes segmentation file and prompts using backend field names', () => {
  const form = serializeScenarioForm('segmentation', {
    file: new Blob(['image']),
    points: [[12, 34], [56, 78]],
    pointLabels: [1, 0],
    box: [1, 2, 30, 40],
    precision: 'fast',
    conf: 0.25,
    modelPath: 'C:/not-allowed.pt',
    library: 'not-allowed',
  })

  assert.equal(form.get('file').size, 5)
  assert.equal(form.get('points'), '[[12,34],[56,78]]')
  assert.equal(form.get('labels'), '[1,0]')
  assert.equal(form.get('box'), '[1,2,30,40]')
  assert.equal(form.get('precision'), 'fast')
  assert.equal(form.get('conf'), null)
  assert.equal(form.get('modelPath'), null)
  assert.equal(form.get('library'), null)
})

test('serializes an explicit zero detector confidence', () => {
  const form = serializeScenarioForm('plate_detection', {
    file: new Blob(['image']),
    conf: 0,
    imgsz: 640,
  })

  assert.equal(form.get('conf'), '0')
  assert.equal(form.get('imgsz'), '640')
})

test('serializes a ReID query and repeated gallery fields', () => {
  const query = new Blob(['query'])
  const galleryOne = new Blob(['one'])
  const galleryTwo = new Blob(['two'])
  const form = serializeScenarioForm('vehicle_reid', {
    query,
    gallery: [galleryOne, galleryTwo],
    threshold: 0.7,
  })

  assert.equal(form.get('query').size, 5)
  assert.deepEqual(form.getAll('gallery').map((file) => file.size), [3, 3])
  assert.equal(form.get('threshold'), '0.7')
})

test('exposes exactly the approved phase-one model route keys', () => {
  assert.deepEqual(PHASE_ONE_ROUTE_KEYS, [
    'efficient-sam',
    'mobile-sam',
    'clip-reid-vehicle',
    'keremberke-yolov5m-license-plate',
    'keremberke-yolov5n-license-plate',
    'transreid-vehicle',
    'vehicle-vit-reid',
    'yolo26n-obb',
    'yolo26n-p2-plate',
  ])
})

test('builds the nine real fixed router records from the shared manifest', () => {
  const component = () => Promise.resolve('ScenarioApp')
  assert.equal(typeof scenarioState.createScenarioRouteRecords, 'function')
  const records = scenarioState.createScenarioRouteRecords(component)

  assert.equal(records.length, 9)
  assert.deepEqual(records.map((record) => record.path), PHASE_ONE_ROUTE_KEYS.map(
    (key) => `ai/scenarios/${key}`,
  ))
  for (const record of records) {
    assert.equal(record.component, component)
    assert.equal(record.props.modelKey, record.meta.modelKey)
    assert.equal(record.path, `ai/scenarios/${record.meta.modelKey}`)
  }
})

test('invalidates stale inference completions after a newer run or unmount', () => {
  assert.equal(typeof scenarioState.createAsyncRequestGuard, 'function')
  const guard = scenarioState.createAsyncRequestGuard()
  const first = guard.begin()
  const second = guard.begin()
  assert.equal(guard.isCurrent(first), false)
  assert.equal(guard.isCurrent(second), true)

  guard.dispose()
  assert.equal(guard.isCurrent(second), false)
  assert.equal(guard.begin(), null)
})

test('keeps the route model key fixed when a query tries to switch models', () => {
  assert.equal(
    resolveFixedModelKey({
      meta: { modelKey: 'efficient-sam' },
      query: { modelKey: 'mobile-sam' },
    }),
    'efficient-sam',
  )
})

test('builds curl against the real Open API inference route', () => {
  const documentation = buildScenarioApiDocumentation({
    modelKey: 'yolo26n-obb',
    workbenchType: 'obb_detection',
    defaults: { conf: 0.5, imgsz: 640 },
  }, { origin: 'https://vision.example' })

  assert.match(
    documentation.curl,
    /^curl -X POST "https:\/\/vision\.example\/openapi\/v1\/model-scenarios\/yolo26n-obb\/infer"/,
  )
  assert.doesNotMatch(documentation.curl, /\/api\/open\/v1/)
  assert.match(documentation.curl, /X-Timestamp: <UNIX_SECONDS>/)
  assert.match(documentation.curl, /X-Nonce: <UNIQUE_NONCE>/)
  assert.match(documentation.curl, /X-Signature: <HMAC_SHA256>/)
})

test('documents fixed-model segmentation fields without ignored parameters', () => {
  const efficient = buildScenarioApiDocumentation({
    modelKey: 'efficient-sam',
    workbenchType: 'segmentation',
    defaults: {},
  })
  const mobile = buildScenarioApiDocumentation({
    modelKey: 'mobile-sam',
    workbenchType: 'segmentation',
    defaults: {},
  })

  assert.deepEqual(efficient.fields.map((field) => field.name), [
    'file', 'points', 'labels', 'box', 'precision',
  ])
  assert.deepEqual(mobile.fields.map((field) => field.name), [
    'file', 'mode', 'points', 'labels', 'box',
  ])
  assert.match(efficient.fields.find((field) => field.name === 'points').description, /\[x, y\]/)
  assert.match(efficient.fields.find((field) => field.name === 'labels').description, /等长/)
  assert.match(efficient.fields.find((field) => field.name === 'box').description, /\[x1, y1, x2, y2\]/)
  assert.match(mobile.fields.find((field) => field.name === 'mode').description, /auto.*无需提示/)
  assert.match(mobile.curl, /-F "mode=auto"/)
  assert.doesNotMatch(`${efficient.curl}\n${mobile.curl}`, /-F "conf=/)
})

test('matches the Open API success envelope and normalized result field names', () => {
  const fixtures = [
    ['efficient-sam', 'segmentation'],
    ['clip-reid-vehicle', 'vehicle_reid'],
    ['yolo26n-p2-plate', 'plate_detection'],
    ['yolo26n-obb', 'obb_detection'],
  ]
  const docs = Object.fromEntries(fixtures.map(([modelKey, workbenchType]) => [
    workbenchType,
    buildScenarioApiDocumentation({ modelKey, workbenchType, defaults: {} }, { requestId: 'req-test' }),
  ]))

  for (const [modelKey, workbenchType] of fixtures) {
    const response = docs[workbenchType].response
    assert.equal(response.code, 0)
    assert.equal(response.message, 'ok')
    assert.equal(response.requestId, 'req-test')
    assert.equal(response.data.modelKey, modelKey)
    assert.equal(response.data.workbench, workbenchType)
    assert.equal(response.data.elapsedMs, 7)
  }

  assert.deepEqual(Object.keys(docs.segmentation.response.data.result).sort(), [
    'count', 'detections', 'height', 'imageBase64', 'width',
  ])
  assert.deepEqual(Object.keys(docs.segmentation.response.data.result.detections[0]).sort(), [
    'areaPixels', 'areaRatio', 'bbox', 'classId', 'className', 'confidence', 'maskBase64',
  ])
  assert.deepEqual(Object.keys(docs.vehicle_reid.response.data.result).sort(), [
    'backend', 'matches', 'query',
  ])
  assert.equal(docs.vehicle_reid.response.data.result.backend.inputSize, '256x256')
  assert.equal(typeof docs.vehicle_reid.response.data.result.backend.inputSize, 'string')
  assert.deepEqual(Object.keys(docs.vehicle_reid.response.data.result.matches[0]).sort(), [
    'distance', 'filename', 'matched', 'rank', 'similarity', 'sourceIndex',
  ])
  assert.deepEqual(Object.keys(docs.plate_detection.response.data.result.detections[0]).sort(), [
    'bbox', 'classId', 'className', 'confidence',
  ])
  assert.deepEqual(Object.keys(docs.obb_detection.response.data.result.detections[0]).sort(), [
    'angle', 'angleUnit', 'bbox', 'classId', 'className', 'confidence', 'quad',
  ])
})

test('accepts only the latest detail response for the current fixed route key', () => {
  assert.equal(isLatestScenarioRequest(2, 2, 'mobile-sam', 'mobile-sam'), true)
  assert.equal(isLatestScenarioRequest(1, 2, 'efficient-sam', 'mobile-sam'), false)
  assert.equal(isLatestScenarioRequest(2, 2, 'efficient-sam', 'mobile-sam'), false)
})

test('restores the full segmentation snapshot when a replacement box is undone', () => {
  const previous = {
    points: [[10, 20]],
    pointLabels: [1],
    box: [5, 6, 50, 60],
  }
  const current = {
    points: [[10, 20]],
    pointLabels: [1],
    box: [100, 110, 180, 190],
  }

  const restored = undoSegmentationPrompt(current, previous)
  previous.points[0][0] = 999
  previous.box[0] = 999

  assert.deepEqual(restored, {
    points: [[10, 20]],
    pointLabels: [1],
    box: [5, 6, 50, 60],
  })
})

test('clamps pointer coordinates to the image boundary when dragging outside', () => {
  assert.deepEqual(clampImagePoint([-18, 145], 100, 80), [0, 80])
  assert.deepEqual(clampImagePoint([42.7, 21.2], 100, 80), [43, 21])
})

test('validates each workbench form at its business input boundaries', () => {
  const image = new Blob(['image'], { type: 'image/png' })
  assert.deepEqual(validateWorkbenchState('segmentation', {
    file: image,
    mode: 'prompt',
    points: [[1, 2]],
    pointLabels: [1],
  }), [])
  assert.deepEqual(validateWorkbenchState('segmentation', {
    file: image,
    mode: 'prompt',
    points: [[1, 2]],
    pointLabels: [],
  }), ['正负点标签必须与提示点一一对应。'])
  assert.deepEqual(validateWorkbenchState('vehicle_reid', {
    query: image,
    gallery: [image, image],
    threshold: 1.01,
  }), ['相似度阈值必须在 0 到 1 之间。'])
  assert.equal(validateWorkbenchState('vehicle_reid', {
    query: image,
    gallery: [image, image, image],
    threshold: 0.7,
  }, { maxGalleryImages: 2 })[0].includes('2'), true)
  assert.equal(validateWorkbenchState('segmentation', {
    file: image,
    mode: 'prompt',
    points: [[1, 1], [2, 2], [3, 3]],
    pointLabels: [1, 1, 0],
  }, { maxPrompts: 2 })[0].includes('2'), true)
  assert.deepEqual(validateWorkbenchState('plate_detection', {
    file: image,
    conf: 0,
    imgsz: 32,
  }), [])
  assert.deepEqual(validateWorkbenchState('obb_detection', {
    file: image,
    conf: 0.5,
    imgsz: 4097,
  }), ['推理尺寸必须是 32 到 4096 的整数。'])
})

test('rejects workbench uploads outside the declared image policy', () => {
  const wrongFormat = new File(['image'], 'plate.gif', { type: 'image/gif' })
  const tooLarge = new File([new Uint8Array(1049)], 'plate.png', { type: 'image/png' })
  const policy = { formats: ['.jpg', '.png'], maxSizeMb: 0.001 }

  assert.deepEqual(validateWorkbenchState('plate_detection', {
    file: wrongFormat,
    conf: 0.5,
    imgsz: 640,
  }, policy), ['图片格式不受支持，请使用 JPG / PNG。'])
  assert.deepEqual(validateWorkbenchState('plate_detection', {
    file: tooLarge,
    conf: 0.5,
    imgsz: 640,
  }, policy), ['图片超过 0.001 MB 上传限制。'])
})

test('normalizes real ReID matches by similarity and leaves missing decisions missing', () => {
  const normalized = normalizeWorkbenchResult('vehicle_reid', {
    query: 'query.jpg',
    backend: { backend: 'vehicle-onnx', dim: 768 },
    matches: [
      { filename: 'low.jpg', similarity: 0.2, matched: false },
      { filename: 'unknown.jpg', similarity: null },
      { filename: 'high.jpg', similarity: 0.91, matched: true },
      { filename: 'bad.jpg', similarity: '0.8', matched: true },
    ],
  })

  assert.deepEqual(normalized.matches.map((item) => item.filename), [
    'high.jpg', 'low.jpg', 'unknown.jpg', 'bad.jpg',
  ])
  assert.equal(normalized.matches[2].matched, undefined)
  assert.equal(normalized.matches[3].similarity, undefined)
})

test('keeps ReID gallery indices stable for duplicate names and equal scores', () => {
  const normalized = normalizeWorkbenchResult('vehicle_reid', {
    matches: [
      { filename: 'other.jpg', similarity: 0.9, distance: 0.1, matched: true, sourceIndex: 2, rank: 1 },
      { filename: 'same.jpg', similarity: 0.9, distance: 0.1, matched: true, sourceIndex: 1, rank: 2 },
      { filename: 'same.jpg', similarity: 0.8, distance: 0.2, matched: true, sourceIndex: 0, rank: 3 },
    ],
  })

  assert.deepEqual(normalized.matches.map((item) => item.galleryIndex), [2, 1, 0])
  assert.deepEqual(normalized.matches.map((item) => item.rank), [1, 2, 3])
})

test('keeps only finite drawable detector geometry and scales within canvas bounds', () => {
  const normalized = normalizeWorkbenchResult('obb_detection', {
    width: 200,
    height: 100,
    detections: [
      { className: 'plate', confidence: 0.9, bbox: [-10, 5, 220, 95], quad: [[0, 0], [200, 0], [200, 100], [0, 100]] },
      { className: 'bad', bbox: [0, 0, Number.NaN, 20], quad: [[0, 0]] },
      { className: 'native-angle', angle: 37.5 },
    ],
  })
  const shapes = scaleDetectionGeometry(normalized, 100, 50)

  assert.deepEqual(shapes[0].bbox, [0, 2.5, 100, 47.5])
  assert.deepEqual(shapes[0].quad, [[0, 0], [100, 0], [100, 50], [0, 50]])
  assert.equal(shapes[0].angle, 0)
  assert.equal(shapes[1].bbox, undefined)
  assert.equal(shapes[1].quad, undefined)
  assert.equal(shapes[1].angle, undefined)
  assert.equal(shapes[2].angle, 37.5)
})

test('derives mask area and ratio only from actual RGBA mask pixels', () => {
  const rgba = new Uint8ClampedArray([
    0, 0, 0, 0,
    255, 255, 255, 255,
    5, 5, 5, 255,
    0, 0, 0, 255,
  ])
  assert.deepEqual(deriveMaskMetrics(rgba, 2, 2), { area: 2, ratio: 0.5 })
  assert.equal(deriveMaskMetrics(rgba, 0, 2), null)
})

test('accepts an extension-approved image when the browser leaves MIME empty', () => {
  assert.equal(isAcceptedImageCandidate(
    new File(['image'], 'plate.PNG', { type: '' }),
    ['.jpg', '.png'],
  ), true)
  assert.equal(isAcceptedImageCandidate(
    new File(['image'], 'plate.gif', { type: '' }),
    ['.jpg', '.png'],
  ), false)
  assert.equal(isAcceptedImageCandidate(
    new File(['image'], 'plate.png', { type: 'text/plain' }),
    ['.jpg', '.png'],
  ), false)
})

test('rejects a stale async preview callback by generation or selected URL', () => {
  assert.equal(isCurrentPreviewRequest(3, 3, 'data:new', 'data:new'), true)
  assert.equal(isCurrentPreviewRequest(2, 3, 'data:old', 'data:new'), false)
  assert.equal(isCurrentPreviewRequest(3, 3, 'data:old', 'data:new'), false)
})
