/** 拉取图像分割相关模型（按 task 分页，避免全库截断漏掉 EfficientSAM）。 */

const SEG_TASKS = ['instance-segmentation', 'interactive-segmentation']

const ENGINE_LIBS = {
  rfdetr: ['rfdetr'],
  ultralytics: ['ultralytics'],
  'yolo-master': ['yolo-master'],
  mobilesam: ['mobilesam'],
  efficientsam: ['opencv-sam', 'efficientsam', 'efficient-sam'],
}

export function isEfficientSamModel(m) {
  const lib = String(m?.library || '').toLowerCase()
  const key = String(m?.modelKey || '').toLowerCase()
  const name = String(m?.modelName || '')
  return (
    ENGINE_LIBS.efficientsam.includes(lib)
    || key === 'efficient-sam'
    || /efficient\s*sam/i.test(name)
  )
}

export function resolveSegEngine(m) {
  if (!m) return null
  if (isEfficientSamModel(m)) return 'efficientsam'
  const lib = String(m.library || '').toLowerCase()
  if (lib === 'mobilesam') return 'mobilesam'
  if (lib === 'ultralytics') return 'ultralytics'
  if (lib === 'yolo-master') return 'yolo-master'
  if (lib === 'rfdetr') return 'rfdetr'
  return null
}

export function isUsableSegModel(m) {
  if (!m?.filePath) return false
  if (String(m.status) !== '0') return false
  const task = String(m.task || '').toLowerCase()
  if (!SEG_TASKS.includes(task)) return false
  return resolveSegEngine(m) != null
}

export function filterSegModelsByEngine(models, engine) {
  const list = (models || []).filter(isUsableSegModel)
  if (!engine) return list
  if (engine === 'efficientsam') return list.filter(isEfficientSamModel)
  const libs = ENGINE_LIBS[engine]
  if (!libs) return list
  return list.filter((m) => libs.includes(String(m.library || '').toLowerCase()))
}

export async function loadSegmentationModels(modelApi, { pageSize = 200 } = {}) {
  const byId = new Map()
  const ingest = (rows) => {
    for (const m of rows || []) {
      if (m?.id != null) byId.set(m.id, m)
    }
  }

  for (const task of SEG_TASKS) {
    let pageNum = 1
    let total = Infinity
    while (byId.size < total + 50 && pageNum <= 20) {
      const res = await modelApi.list({ pageNum, pageSize, task })
      const rows = res.data?.rows || []
      total = Number(res.data?.total ?? rows.length)
      ingest(rows)
      if (!rows.length || rows.length < pageSize) break
      pageNum += 1
    }
  }

  // 名称兜底：防止 task/分页异常漏掉 EfficientSAM
  if (![...byId.values()].some(isEfficientSamModel)) {
    const res = await modelApi.list({ pageNum: 1, pageSize: 50, modelName: 'EfficientSAM' })
    ingest(res.data?.rows || [])
    const res2 = await modelApi.list({ pageNum: 1, pageSize: 50, modelName: 'efficient-sam' })
    ingest(res2.data?.rows || [])
  }

  const list = [...byId.values()].filter(isUsableSegModel)
  list.sort((a, b) => {
    const rank = (m) => {
      if (isEfficientSamModel(m)) return 0
      if (String(m.library || '').toLowerCase() === 'mobilesam') return 1
      if (String(m.library || '').toLowerCase() === 'ultralytics') return 2
      if (String(m.library || '').toLowerCase() === 'yolo-master') return 2
      return 3
    }
    return rank(a) - rank(b) || Number(a.id) - Number(b.id)
  })
  return list
}

export function pickPreferredSegModel(models, engine, currentId) {
  const scoped = filterSegModelsByEngine(models, engine)
  if (currentId && scoped.some((m) => m.id === currentId)) return currentId
  return scoped[0]?.id || null
}
