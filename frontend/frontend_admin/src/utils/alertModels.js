/**
 * 检测告警可用模型筛选（摄像头 / 视频检测 / 目标追踪共用）。
 * 启用告警后只展示能跑告警管线的目标检测模型。
 */

/** 视频/摄像头告警叠加支持的推理库 */
export const ALERT_DETECT_LIBS = new Set(['ultralytics', 'rfdetr', 'transformers'])

/** 种子/常用告警相关模型（优先展示） */
export const ALERT_PREFERRED_KEYS = new Set([
  'fire-smoke-detection',
  'ppe-detection',
  'yolo26n',
  'yolo26s',
])

/**
 * @param {object} m AiModel 行
 * @param {{ forTrack?: boolean }} opts forTrack=true 时仅 ultralytics（ByteTrack）
 */
export function isAlertCapableModel(m, opts = {}) {
  if (!m || m.status !== '0' || !m.filePath) return false
  if ((m.task || '') !== 'object-detection') return false
  const lib = (m.library || 'ultralytics').toLowerCase()
  if (opts.forTrack) {
    return lib === 'ultralytics'
  }
  return ALERT_DETECT_LIBS.has(lib)
}

/**
 * 在全量模型列表上按「是否启用告警」过滤，并尽量把告警相关模型排前面。
 * @param {object[]} allModels
 * @param {{ alertEnabled?: boolean, forTrack?: boolean, category?: string }} opts
 */
export function filterWorkbenchModels(allModels, opts = {}) {
  const { alertEnabled = false, forTrack = false, category = '' } = opts
  let list = Array.isArray(allModels) ? [...allModels] : []

  if (alertEnabled) {
    list = list.filter((m) => isAlertCapableModel(m, { forTrack }))
    list.sort((a, b) => {
      const pa = ALERT_PREFERRED_KEYS.has(a.modelKey) ? 0 : 1
      const pb = ALERT_PREFERRED_KEYS.has(b.modelKey) ? 0 : 1
      if (pa !== pb) return pa - pb
      return String(a.modelName || '').localeCompare(String(b.modelName || ''), 'zh')
    })
  } else if (forTrack) {
    list = list.filter(
      (m) =>
        m.status === '0' &&
        m.filePath &&
        m.task === 'object-detection' &&
        (m.library || 'ultralytics').toLowerCase() === 'ultralytics',
    )
  }

  if (category) {
    list = list.filter((m) => m.category === category)
  }
  return list
}

/** 当前选中模型若不在过滤结果中，切到第一项 */
export function ensureModelInList(modelId, list) {
  if (!list?.length) return null
  if (modelId != null && list.some((m) => m.id === modelId)) return modelId
  return list[0].id
}

/** 从过滤后的模型列表提取分类 */
export function categoriesFromModels(models) {
  return [...new Set((models || []).map((m) => m.category).filter(Boolean))]
}
