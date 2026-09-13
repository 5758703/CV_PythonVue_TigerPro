import assert from 'node:assert/strict'
import test from 'node:test'

import {
  PHASE_ONE_ROUTE_KEYS,
  buildScenarioApiDocumentation,
  isLatestScenarioRequest,
  resolveFixedModelKey,
  resolveWorkbench,
  serializeScenarioForm,
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
  assert.equal(form.get('conf'), '0.25')
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
    'bbox', 'classId', 'className', 'confidence', 'maskBase64',
  ])
  assert.deepEqual(Object.keys(docs.vehicle_reid.response.data.result).sort(), [
    'backend', 'matches', 'query',
  ])
  assert.deepEqual(Object.keys(docs.vehicle_reid.response.data.result.matches[0]).sort(), [
    'filename', 'matched', 'similarity',
  ])
  assert.deepEqual(Object.keys(docs.plate_detection.response.data.result.detections[0]).sort(), [
    'bbox', 'classId', 'className', 'confidence',
  ])
  assert.deepEqual(Object.keys(docs.obb_detection.response.data.result.detections[0]).sort(), [
    'bbox', 'classId', 'className', 'confidence', 'quad',
  ])
})

test('accepts only the latest detail response for the current fixed route key', () => {
  assert.equal(isLatestScenarioRequest(2, 2, 'mobile-sam', 'mobile-sam'), true)
  assert.equal(isLatestScenarioRequest(1, 2, 'efficient-sam', 'mobile-sam'), false)
  assert.equal(isLatestScenarioRequest(2, 2, 'efficient-sam', 'mobile-sam'), false)
})
