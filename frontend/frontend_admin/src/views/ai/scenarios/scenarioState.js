const SUPPORTED_WORKBENCHES = new Set([
  'segmentation',
  'vehicle_reid',
  'plate_detection',
  'obb_detection',
])

export const PHASE_ONE_ROUTE_KEYS = [
  'efficient-sam',
  'mobile-sam',
  'clip-reid-vehicle',
  'keremberke-yolov5m-license-plate',
  'keremberke-yolov5n-license-plate',
  'transreid-vehicle',
  'vehicle-vit-reid',
  'yolo26n-obb',
  'yolo26n-p2-plate',
]

export function resolveWorkbench(type) {
  return SUPPORTED_WORKBENCHES.has(type) ? type : null
}

export function resolveFixedModelKey(route) {
  return typeof route?.meta?.modelKey === 'string' ? route.meta.modelKey : null
}

function segmentationFields(modelKey) {
  const promptFields = [
    {
      name: 'points',
      required: false,
      description: '提示点 JSON 数组，每项为有限坐标 [x, y]；prompt 模式下 points 或 box 至少提供一项。',
    },
    {
      name: 'labels',
      required: false,
      description: '与 points 等长的 JSON 数组；1 表示正点，0 表示负点。',
    },
    {
      name: 'box',
      required: false,
      description: '矩形提示框 JSON 数组 [x1, y1, x2, y2]；四项均须为有限数值。',
    },
  ]
  if (modelKey === 'mobile-sam') {
    return [
      { name: 'file', required: true, description: '待分割图片。' },
      { name: 'mode', required: false, description: 'prompt 使用点/框提示；auto 自动分割且无需提示。' },
      ...promptFields,
    ]
  }
  return [
    { name: 'file', required: true, description: '待分割图片。' },
    ...promptFields,
    { name: 'precision', required: false, description: 'ONNX 精度偏好，可选 fp32 或 int8。' },
  ]
}

function apiFields(scenario) {
  if (scenario.workbenchType === 'segmentation') return segmentationFields(scenario.modelKey)
  if (scenario.workbenchType === 'vehicle_reid') {
    return [
      { name: 'query', required: true, description: '单张车辆查询图片。' },
      { name: 'gallery', required: true, description: '一张或多张候选车辆图片，可重复提交。' },
      { name: 'threshold', required: false, description: `0—1 相似度阈值，默认 ${scenario.defaults?.threshold ?? 0.7}。` },
    ]
  }
  return [
    { name: 'file', required: true, description: '待检测图片。' },
    { name: 'conf', required: false, description: `0—1 置信度阈值，默认 ${scenario.defaults?.conf ?? 0.5}。` },
    { name: 'imgsz', required: false, description: `32—4096 整数推理尺寸，默认 ${scenario.defaults?.imgsz ?? 640}。` },
  ]
}

function curlFields(scenario) {
  if (scenario.modelKey === 'mobile-sam') {
    return ['-F "file=@input.jpg"', '-F "mode=auto"']
  }
  if (scenario.workbenchType === 'segmentation') {
    return [
      '-F "file=@input.jpg"',
      "-F 'points=[[320,240]]'",
      "-F 'labels=[1]'",
      '-F "precision=fp32"',
    ]
  }
  if (scenario.workbenchType === 'vehicle_reid') {
    return [
      '-F "query=@query.jpg"',
      '-F "gallery=@candidate-01.jpg"',
      `-F "threshold=${scenario.defaults?.threshold ?? 0.7}"`,
    ]
  }
  return [
    '-F "file=@input.jpg"',
    `-F "conf=${scenario.defaults?.conf ?? 0.5}"`,
    `-F "imgsz=${scenario.defaults?.imgsz ?? 640}"`,
  ]
}

function normalizedResult(workbenchType) {
  if (workbenchType === 'vehicle_reid') {
    return {
      query: 'query.jpg',
      backend: { backend: 'vehicle-onnx', dim: 768, inputSize: '256x256' },
      matches: [{ filename: 'candidate-01.jpg', similarity: 0.86, matched: true }],
    }
  }
  const detection = {
    className: workbenchType === 'segmentation' ? 'segment' : workbenchType === 'plate_detection' ? 'plate' : 'vehicle',
    classId: 0,
    confidence: workbenchType === 'obb_detection' ? 0.91 : 0.88,
    bbox: [120, 80, 420, 260],
  }
  if (workbenchType === 'segmentation') detection.maskBase64 = '<BASE64_PNG>'
  if (workbenchType === 'obb_detection') {
    detection.quad = [[130, 70], [430, 100], [410, 270], [110, 240]]
  }
  return {
    detections: [detection],
    count: 1,
    imageBase64: '<BASE64_JPEG>',
    width: 1280,
    height: 720,
  }
}

export function buildScenarioApiDocumentation(
  scenario,
  { origin = '', requestId = '<REQUEST_ID>' } = {},
) {
  const endpoint = `/openapi/v1/model-scenarios/${encodeURIComponent(scenario.modelKey)}/infer`
  const prefix = String(origin).replace(/\/$/, '')
  const formFields = curlFields(scenario)
  const curl = [
    `curl -X POST "${prefix}${endpoint}" \\`,
    '  -H "Authorization: Bearer <YOUR_API_KEY>" \\',
    ...formFields.map((field, index) => `  ${field}${index < formFields.length - 1 ? ' \\' : ''}`),
  ].join('\n')
  return {
    curl,
    fields: apiFields(scenario),
    response: {
      code: 0,
      message: 'ok',
      requestId,
      data: {
        modelKey: scenario.modelKey,
        workbench: scenario.workbenchType,
        elapsedMs: 7,
        result: normalizedResult(scenario.workbenchType),
      },
    },
  }
}

export function isLatestScenarioRequest(
  requestSequence,
  activeSequence,
  requestedKey,
  currentKey,
) {
  return requestSequence === activeSequence && requestedKey === currentKey
}

function appendValue(form, name, value) {
  if (value !== undefined && value !== null) {
    form.append(name, String(value))
  }
}

function appendJson(form, name, value) {
  if (value !== undefined && value !== null) {
    form.append(name, JSON.stringify(value))
  }
}

export function serializeScenarioForm(type, state) {
  const form = new FormData()

  if (type === 'vehicle_reid') {
    if (state.query) form.append('query', state.query)
    for (const file of state.gallery || []) form.append('gallery', file)
    appendValue(form, 'threshold', state.threshold)
    return form
  }

  if (state.file) form.append('file', state.file)

  if (type === 'segmentation') {
    appendJson(form, 'points', state.points)
    appendJson(form, 'labels', state.pointLabels)
    appendJson(form, 'box', state.box)
    appendValue(form, 'precision', state.precision)
    appendValue(form, 'conf', state.conf)
    return form
  }

  if (type === 'plate_detection' || type === 'obb_detection') {
    appendValue(form, 'conf', state.conf)
    appendValue(form, 'imgsz', state.imgsz)
  }

  return form
}

export function downloadJson(name, value) {
  if (typeof document === 'undefined' || typeof URL === 'undefined') return

  const filename = name.endsWith('.json') ? name : `${name}.json`
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' })
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = filename
  link.click()
  URL.revokeObjectURL(href)
}
