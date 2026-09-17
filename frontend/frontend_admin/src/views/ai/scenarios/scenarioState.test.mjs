import assert from 'node:assert/strict'
import test from 'node:test'
import * as scenarioState from './scenarioState.js'

import {
  LEGACY_MODEL_ROUTE_KEYS,
  MODEL_TO_GROUP,
  SCENARIO_GROUP_ROUTE_KEYS,
  SCENARIO_MODEL_COUNT,
  buildScenarioApiDocumentation,
  clampImagePoint,
  deriveMaskMetrics,
  isAcceptedImageCandidate,
  isCurrentPreviewRequest,
  normalizeWorkbenchResult,
  scaleDetectionGeometry,
  isLatestScenarioRequest,
  mergeSelectedScenario,
  resolveFixedGroupKey,
  resolveGroupKey,
  resolveWorkbench,
  validateSquatParameters,
  serializeScenarioForm,
  undoSegmentationPrompt,
  validateWorkbenchState,
} from './scenarioState.js'

test('resolves each supported workbench type', () => {
  assert.equal(resolveWorkbench('segmentation'), 'segmentation')
  assert.equal(resolveWorkbench('vehicle_reid'), 'vehicle_reid')
  assert.equal(resolveWorkbench('person_reid'), 'person_reid')
  assert.equal(resolveWorkbench('plate_detection'), 'plate_detection')
  assert.equal(resolveWorkbench('obb_detection'), 'obb_detection')
  assert.equal(resolveWorkbench('plate_pose'), 'plate_pose')
  assert.equal(resolveWorkbench('face_recognition'), 'face_recognition')
  assert.equal(resolveWorkbench('object_detection'), 'object_detection')
  assert.equal(resolveWorkbench('instance_segmentation'), 'instance_segmentation')
  assert.equal(resolveWorkbench('document_ocr'), 'document_ocr')
  assert.equal(resolveWorkbench('image_inpainting'), 'image_inpainting')
  assert.equal(resolveWorkbench('image_classification'), 'image_classification')
  assert.equal(resolveWorkbench('multimodal_grounding'), 'multimodal_grounding')
  assert.equal(resolveWorkbench('industrial_diagnosis'), 'industrial_diagnosis')
  assert.equal(resolveWorkbench('body_pose'), 'body_pose')
  assert.equal(resolveWorkbench('squat_counting'), 'squat_counting')
  assert.equal(resolveWorkbench('hand_pose'), 'hand_pose')
  assert.equal(resolveWorkbench('text_nlp'), 'text_nlp')
  assert.equal(resolveWorkbench('speech_asr'), 'speech_asr')
  assert.equal(resolveWorkbench('speech_tts'), 'speech_tts')
  assert.equal(resolveWorkbench('talking_head'), 'talking_head')
})

test('validates squat thresholds and confirmation parameters', () => {
  assert.deepEqual(validateSquatParameters({ standingAngle: 100, bottomAngle: 160 }), [
    '站立阈值必须大于下蹲阈值',
  ])
  assert.deepEqual(validateSquatParameters({
    standingAngle: 160,
    bottomAngle: 100,
    confirmFrames: 3,
  }), [])
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

test('serializes face recognition thresholds with the shared field names', () => {
  const form = serializeScenarioForm('face_recognition', {
    file: new Blob(['face']),
    threshold: 0.4,
    detThresh: 0.5,
  })

  assert.equal(form.get('file').size, 4)
  assert.equal(form.get('threshold'), '0.4')
  assert.equal(form.get('detThresh'), '0.5')
  assert.equal(form.get('conf'), null)
})

test('serializes plate pose and object detection like plate detection', () => {
  for (const type of ['plate_pose', 'object_detection']) {
    const form = serializeScenarioForm(type, {
      file: new Blob(['image']),
      conf: 0.25,
      imgsz: 640,
    })
    assert.equal(form.get('conf'), '0.25')
    assert.equal(form.get('imgsz'), '640')
  }
})

test('serializes phase-three inpainting, classification, grounding and pose fields', () => {
  const inpaint = serializeScenarioForm('image_inpainting', {
    file: new Blob(['image']),
    mask: new Blob(['mask']),
    dilatePx: 8,
  })
  assert.equal(inpaint.get('file').size, 5)
  assert.equal(inpaint.get('mask').size, 4)
  assert.equal(inpaint.get('dilatePx'), '8')

  const classify = serializeScenarioForm('image_classification', {
    file: new Blob(['image']),
    topK: 5,
    precision: 'int8',
    conf: 0.3,
  })
  assert.equal(classify.get('topK'), '5')
  assert.equal(classify.get('precision'), 'int8')
  assert.equal(classify.get('conf'), '0.3')
  assert.equal(classify.get('imgsz'), null)

  const grounding = serializeScenarioForm('multimodal_grounding', {
    file: new Blob(['image']),
    prompt: 'person, car',
    conf: 0.25,
  })
  assert.equal(grounding.get('prompt'), 'person, car')
  assert.equal(grounding.get('conf'), '0.25')
  assert.equal(grounding.get('imgsz'), null)

  const pose = serializeScenarioForm('body_pose', {
    file: new Blob(['image']),
    conf: 0.4,
  })
  assert.equal(pose.get('conf'), '0.4')
  assert.equal(pose.get('imgsz'), null)
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

test('exposes exactly the forty scenario group route keys', () => {
  assert.equal(SCENARIO_GROUP_ROUTE_KEYS.length, 40)
  assert.deepEqual(SCENARIO_GROUP_ROUTE_KEYS.slice(0, 12), [
    'interactive-segmentation',
    'vehicle-reid',
    'plate-detection',
    'obb-detection',
    'plate-pose',
    'face-recognition',
    'medical-detection',
    'image-inpainting',
    'image-classification',
    'multimodal-grounding',
    'body-pose',
    'squat-counting',
  ])
  assert.ok(SCENARIO_GROUP_ROUTE_KEYS.includes('person-reid'))
  assert.ok(SCENARIO_GROUP_ROUTE_KEYS.includes('text-to-speech'))
  assert.ok(SCENARIO_GROUP_ROUTE_KEYS.includes('talking-head'))
  assert.equal(SCENARIO_GROUP_ROUTE_KEYS.at(-1), 'talking-head')
})

test('maps all ninety legacy model keys onto the forty groups', () => {
  assert.equal(SCENARIO_MODEL_COUNT, 90)
  assert.equal(LEGACY_MODEL_ROUTE_KEYS.length, 90)
  assert.equal(resolveGroupKey('interactive-segmentation'), 'interactive-segmentation')
  assert.equal(resolveGroupKey('efficient-sam'), 'interactive-segmentation')
  assert.equal(resolveGroupKey('mobile-sam'), 'interactive-segmentation')
  assert.equal(resolveGroupKey('clip-reid-vehicle'), 'vehicle-reid')
  assert.equal(resolveGroupKey('yolo26n-obb'), 'obb-detection')
  assert.equal(resolveGroupKey('brain-tumor-yolo-opennoor'), 'medical-detection')
  assert.equal(resolveGroupKey('inpainting-lama'), 'image-inpainting')
  assert.equal(resolveGroupKey('mobilenet-v2'), 'image-classification')
  assert.equal(resolveGroupKey('vlm-fo1-3b'), 'multimodal-grounding')
  assert.equal(resolveGroupKey('dwpose-m'), 'body-pose')
  assert.equal(resolveGroupKey('unknown-model'), null)
  assert.equal(MODEL_TO_GROUP['yolo26n-p2-plate'], 'plate-detection')
  assert.equal(MODEL_TO_GROUP['insightface-buffalo-l'], 'face-recognition')
  assert.equal(MODEL_TO_GROUP['yolo-master-cls-n'], 'image-classification')
  assert.equal(MODEL_TO_GROUP['rtmpose-m'], 'body-pose')
  assert.equal(MODEL_TO_GROUP['osnet-x1-0'], 'person-reid')
  assert.equal(resolveGroupKey('talking-head'), 'talking-head')
  assert.equal(resolveGroupKey('linly-talker'), 'talking-head')
})

test('builds forty group router records and ninety legacy redirects', () => {
  const component = () => Promise.resolve('ScenarioApp')
  assert.equal(typeof scenarioState.createScenarioRouteRecords, 'function')
  assert.equal(typeof scenarioState.createLegacyScenarioRedirectRecords, 'function')
  const records = scenarioState.createScenarioRouteRecords(component)
  const redirects = scenarioState.createLegacyScenarioRedirectRecords()

  assert.equal(SCENARIO_GROUP_ROUTE_KEYS.length, 40)
  assert.equal(records.length, 40)
  assert.deepEqual(records.map((record) => record.path), SCENARIO_GROUP_ROUTE_KEYS.map(
    (key) => `ai/scenarios/${key}`,
  ))
  assert.deepEqual(records.map((record) => record.meta.groupKey), SCENARIO_GROUP_ROUTE_KEYS)
  for (const record of records) {
    assert.equal(record.component, component)
    assert.equal(record.props.groupKey, record.meta.groupKey)
    assert.equal(record.path, `ai/scenarios/${record.meta.groupKey}`)
  }

  assert.equal(redirects.length, 90)
  const efficientRedirect = redirects.find((item) => item.path === 'ai/scenarios/efficient-sam')
  assert.equal(typeof efficientRedirect.redirect, 'function')
  assert.deepEqual(efficientRedirect.redirect({ query: {} }), {
    path: '/ai/scenarios/interactive-segmentation',
    query: { model: 'efficient-sam' },
  })
  const poseRedirect = redirects.find((item) => item.path === 'ai/scenarios/rtmo-m')
  assert.deepEqual(poseRedirect.redirect({ query: {} }), {
    path: '/ai/scenarios/body-pose',
    query: { model: 'rtmo-m' },
  })
})

test('merges group shared fields with the selected model identity', () => {
  const merged = mergeSelectedScenario({
    groupKey: 'interactive-segmentation',
    name: '交互分割',
    project: '缺陷与目标精细轮廓提取',
    description: 'group description',
    workbenchType: 'segmentation',
    defaultModelKey: 'efficient-sam',
    models: [
      {
        modelKey: 'efficient-sam',
        name: 'EfficientSAM-Ti（OpenCV）',
        defaults: { precision: 'fp32' },
        apiReady: true,
        adapter: 'efficient_sam',
        apiPath: '/openapi/v1/model-scenarios/efficient-sam/infer',
        input: { formats: ['.png'] },
      },
      {
        modelKey: 'mobile-sam',
        name: 'MobileSAM 交互分割',
        defaults: { mode: 'prompt' },
        apiReady: false,
        adapter: 'mobile_sam',
        apiPath: '/openapi/v1/model-scenarios/mobile-sam/infer',
        input: { formats: ['.jpg'] },
      },
    ],
  }, 'mobile-sam')

  assert.equal(merged.groupKey, 'interactive-segmentation')
  assert.equal(merged.name, '交互分割')
  assert.equal(merged.modelKey, 'mobile-sam')
  assert.equal(merged.modelName, 'MobileSAM 交互分割')
  assert.equal(merged.apiReady, false)
  assert.deepEqual(merged.defaults, { mode: 'prompt' })
  assert.equal(merged.adapter, 'mobile_sam')
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

test('keeps the route group key fixed when a query tries to switch groups', () => {
  assert.equal(
    resolveFixedGroupKey({
      meta: { groupKey: 'interactive-segmentation' },
      query: { model: 'mobile-sam' },
    }),
    'interactive-segmentation',
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
  assert.deepEqual(validateWorkbenchState('image_inpainting', {
    file: image,
    mask: image,
    dilatePx: 8,
  }), [])
  assert.deepEqual(validateWorkbenchState('image_inpainting', {
    file: image,
    dilatePx: 8,
  }), ['请选择遮罩图片。'])
  assert.deepEqual(validateWorkbenchState('image_classification', {
    file: image,
    topK: 5,
  }), [])
  assert.deepEqual(validateWorkbenchState('image_classification', {
    file: image,
    topK: 21,
  }), ['Top-K 必须是 1 到 20 的整数。'])
  assert.deepEqual(validateWorkbenchState('multimodal_grounding', {
    file: image,
    prompt: 'person',
    conf: 0.25,
  }), [])
  assert.deepEqual(validateWorkbenchState('multimodal_grounding', {
    file: image,
    prompt: '   ',
    conf: 0.25,
  }), ['请填写定位提示词。'])
  assert.deepEqual(validateWorkbenchState('body_pose', {
    file: image,
    conf: 0.25,
  }), [])
  assert.deepEqual(validateWorkbenchState('body_pose', {
    file: image,
    conf: 1.2,
  }), ['置信度阈值必须在 0 到 1 之间。'])
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
