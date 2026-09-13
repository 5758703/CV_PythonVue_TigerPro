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
    appendValue(form, 'mode', state.mode)
    appendValue(form, 'precision', state.precision)
    return form
  }

  if (type === 'plate_detection' || type === 'obb_detection') {
    appendValue(form, 'conf', state.conf)
    appendValue(form, 'imgsz', state.imgsz)
  }

  return form
}

const isFiniteNumber = (value) => typeof value === 'number' && Number.isFinite(value)

function validUnitInterval(value) {
  return isFiniteNumber(value) && value >= 0 && value <= 1
}

function imagePolicyError(file, policy = {}) {
  if (!file) return ''
  const formats = Array.isArray(policy.formats) ? policy.formats.map((item) => item.toLowerCase()) : []
  const filename = typeof file.name === 'string' ? file.name.toLowerCase() : ''
  if (formats.length && !formats.some((extension) => filename.endsWith(extension))) {
    return `图片格式不受支持，请使用 ${formats.map((item) => item.replace('.', '').toUpperCase()).join(' / ')}。`
  }
  const maxSizeMb = Number(policy.maxSizeMb)
  if (maxSizeMb > 0 && Number(file.size) > maxSizeMb * 1024 * 1024) {
    return `图片超过 ${maxSizeMb} MB 上传限制。`
  }
  return ''
}

export function validateWorkbenchState(type, state = {}, inputPolicy = {}) {
  const errors = []
  if (type === 'vehicle_reid') {
    if (!state.query) errors.push('请选择查询车辆图片。')
    if (!Array.isArray(state.gallery) || state.gallery.length === 0) errors.push('请至少选择一张候选车辆图片。')
    const queryError = imagePolicyError(state.query, inputPolicy)
    if (queryError) errors.push(queryError)
    const galleryError = (state.gallery || []).map((file) => imagePolicyError(file, inputPolicy)).find(Boolean)
    if (galleryError) errors.push(galleryError)
    if (!validUnitInterval(Number(state.threshold))) errors.push('相似度阈值必须在 0 到 1 之间。')
    return errors
  }

  if (!state.file) errors.push('请选择待处理图片。')
  const fileError = imagePolicyError(state.file, inputPolicy)
  if (fileError) errors.push(fileError)
  if (type === 'segmentation') {
    const points = Array.isArray(state.points) ? state.points : []
    const labels = Array.isArray(state.pointLabels) ? state.pointLabels : []
    if (points.length !== labels.length) errors.push('正负点标签必须与提示点一一对应。')
    if (state.mode !== 'auto' && points.length === 0 && !state.box) {
      errors.push('请添加至少一个提示点或框选区域。')
    }
    return errors
  }

  if (!validUnitInterval(Number(state.conf))) errors.push('置信度阈值必须在 0 到 1 之间。')
  if (!Number.isInteger(Number(state.imgsz)) || Number(state.imgsz) < 32 || Number(state.imgsz) > 4096) {
    errors.push('推理尺寸必须是 32 到 4096 的整数。')
  }
  return errors
}

export function undoSegmentationPrompt(_state, snapshot = {}) {
  return {
    points: (snapshot.points || []).map((point) => [...point]),
    pointLabels: [...(snapshot.pointLabels || [])],
    box: Array.isArray(snapshot.box) ? [...snapshot.box] : null,
  }
}

export function clampImagePoint(point, width, height) {
  const x = Number.isFinite(point?.[0]) ? Math.round(point[0]) : 0
  const y = Number.isFinite(point?.[1]) ? Math.round(point[1]) : 0
  return [clamp(x, 0, Math.max(0, width)), clamp(y, 0, Math.max(0, height))]
}

export function isAcceptedImageCandidate(file, formats = []) {
  if (!file) return false
  if (typeof file.type === 'string' && file.type) return file.type.startsWith('image/')
  const filename = typeof file.name === 'string' ? file.name.toLowerCase() : ''
  return formats.some((extension) => filename.endsWith(String(extension).toLowerCase()))
}

export function isCurrentPreviewRequest(requestGeneration, activeGeneration, requestedUrl, currentUrl) {
  return requestGeneration === activeGeneration && requestedUrl === currentUrl
}

function normalizeNumberList(value, length) {
  if (!Array.isArray(value) || value.length !== length || !value.every(isFiniteNumber)) return undefined
  return value.slice()
}

function normalizeQuad(value) {
  if (!Array.isArray(value) || value.length !== 4) return undefined
  const points = value.map((point) => normalizeNumberList(point, 2))
  return points.every(Boolean) ? points : undefined
}

function normalizeDetection(item) {
  if (!item || typeof item !== 'object') return {}
  const normalized = { ...item }
  const bbox = normalizeNumberList(item.bbox, 4)
  const quad = normalizeQuad(item.quad)
  if (bbox) normalized.bbox = bbox
  else delete normalized.bbox
  if (quad) normalized.quad = quad
  else delete normalized.quad
  if (!isFiniteNumber(item.confidence)) delete normalized.confidence
  if (!isFiniteNumber(item.angle)) delete normalized.angle
  return normalized
}

export function normalizeWorkbenchResult(type, value) {
  const source = value && typeof value === 'object' ? value : {}
  if (type === 'vehicle_reid') {
    const matches = Array.isArray(source.matches)
      ? source.matches.map((item, galleryIndex) => {
        const match = item && typeof item === 'object' ? { ...item } : {}
        if (!isFiniteNumber(item?.similarity)) delete match.similarity
        if (typeof item?.matched !== 'boolean') delete match.matched
        return { ...match, galleryIndex }
      }).sort((left, right) => {
        const leftScore = isFiniteNumber(left.similarity) ? left.similarity : -Infinity
        const rightScore = isFiniteNumber(right.similarity) ? right.similarity : -Infinity
        return rightScore - leftScore || left.galleryIndex - right.galleryIndex
      })
      : []
    return { ...source, matches }
  }
  return {
    ...source,
    detections: Array.isArray(source.detections) ? source.detections.map(normalizeDetection) : [],
  }
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value))
}

function quadAngle(quad) {
  if (!quad) return undefined
  const [first, second] = quad
  const degrees = Math.atan2(second[1] - first[1], second[0] - first[0]) * 180 / Math.PI
  return Math.round(degrees * 10) / 10
}

export function scaleDetectionGeometry(result, targetWidth, targetHeight) {
  const sourceWidth = Number(result?.width)
  const sourceHeight = Number(result?.height)
  if (!(sourceWidth > 0 && sourceHeight > 0 && targetWidth > 0 && targetHeight > 0)) return []
  const scaleX = targetWidth / sourceWidth
  const scaleY = targetHeight / sourceHeight
  return (result.detections || []).map((detection, index) => {
    const bbox = normalizeNumberList(detection.bbox, 4)?.map((value, coordinate) => (
      clamp(value * (coordinate % 2 === 0 ? scaleX : scaleY), 0, coordinate % 2 === 0 ? targetWidth : targetHeight)
    ))
    const sourceQuad = normalizeQuad(detection.quad)
    const quad = sourceQuad?.map(([x, y]) => [
      clamp(x * scaleX, 0, targetWidth),
      clamp(y * scaleY, 0, targetHeight),
    ])
    const angle = isFiniteNumber(detection.angle) ? detection.angle : quadAngle(sourceQuad)
    return {
      index,
      ...(bbox ? { bbox } : {}),
      ...(quad ? { quad } : {}),
      ...(angle !== undefined ? { angle } : {}),
    }
  })
}

export function deriveMaskMetrics(rgba, width, height) {
  if (!rgba || !(width > 0 && height > 0) || rgba.length < width * height * 4) return null
  let area = 0
  for (let offset = 0; offset < width * height * 4; offset += 4) {
    if (rgba[offset + 3] > 0 && (rgba[offset] > 0 || rgba[offset + 1] > 0 || rgba[offset + 2] > 0)) area += 1
  }
  return { area, ratio: area / (width * height) }
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
