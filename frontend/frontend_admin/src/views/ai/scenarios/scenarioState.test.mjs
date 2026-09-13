import assert from 'node:assert/strict'
import test from 'node:test'

import {
  PHASE_ONE_ROUTE_KEYS,
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
