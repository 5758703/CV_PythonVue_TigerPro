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
