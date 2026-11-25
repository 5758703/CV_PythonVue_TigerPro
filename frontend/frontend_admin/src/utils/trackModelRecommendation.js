/**
 * 目标追踪等场景的默认模型推荐。
 * 原则：优先场景专用权重 → 官方通用检测（yolo26s 等）→ 避开吸烟/烟火/羽毛球等专用微调。
 */

const textOf = (model) => [
  model?.modelKey,
  model?.modelName,
  model?.category,
  model?.version,
  model?.filePath,
].filter(Boolean).join(' ').toLowerCase()

/** 不宜作为通用/车辆/人员追踪默认的专用微调（仍可手动选择） */
export const SPECIALIZED_DETECT_RE = new RegExp([
  'plate', 'license', '车牌',
  '\\bppe\\b', 'helmet', 'hard[-_ ]?hat', '安全帽',
  '\\bfire\\b', 'smoke', 'smoking', 'cigarette', '烟火', '吸烟', '香烟',
  'badminton', 'tennis[-_ ]?ball', '羽毛球',
  'tumor', 'brain', 'crack',
  '\\bpose\\b', '\\bobb\\b', '\\bseg\\b', '[-_]seg\\b', 'segment',
  'sign[-_ ]?language', '手语',
  '\\bfall\\b', '跌倒',
  'mobile[-_ ]?phone', '手机使用', '手机检测',
  'rocket', '火箭',
  '[-_]ball\\b', '\\bball[-_]',
].join('|'), 'i')

/** 官方/平台通用检测标识（精确 key 或名称含「通用检测」） */
const GENERAL_DETECT_KEYS = [
  'yolo26s',
  'yolo26n',
  'yolo11s',
  'yolo11n',
  'yolov8s',
  'yolov8n',
  'yolo26m',
  'yolo11m',
]

const exactKey = (model) => String(model?.modelKey || '').trim().toLowerCase()

const isSpecializedDetect = (model) => SPECIALIZED_DETECT_RE.test(textOf(model))

const isGeneralCocoDetect = (model) => {
  const key = exactKey(model)
  if (GENERAL_DETECT_KEYS.includes(key)) return true
  const name = String(model?.modelName || '')
  return /通用检测/.test(name) && !isSpecializedDetect(model)
}

const SCENE_RULES = {
  general: [
    [(m, t) => exactKey(m) === 'yolo26s' || (/yolo26s/.test(t) && /通用检测/.test(t)), -50],
    [(m, t) => exactKey(m) === 'yolo26n' || (/yolo26n/.test(t) && /通用检测/.test(t)), -40],
    [(m) => isGeneralCocoDetect(m), -30],
    [(m, t) => /yolo26s/.test(t) && !isSpecializedDetect(m), -10],
    [(m, t) => /yolo26n/.test(t) && !isSpecializedDetect(m), 0],
    [(m, t) => /yolo11s/.test(t) && !isSpecializedDetect(m), 10],
    [(m, t) => /yolo11n/.test(t) && !isSpecializedDetect(m), 20],
    [(m, t) => /yolov8s/.test(t) && !isSpecializedDetect(m), 30],
    [(m, t) => /yolov8n/.test(t) && !isSpecializedDetect(m), 40],
  ],
  vehicle: [
    [(m, t) => /(vehicle|traffic|车辆|交通)/.test(t) && /(yolo26s|yolo11s|yolov8s)/.test(t) && !isSpecializedDetect(m), -70],
    [(m, t) => /(vehicle|traffic|车辆|交通)/.test(t) && !isSpecializedDetect(m), -55],
    [(m, t) => exactKey(m) === 'yolo26s' || (/yolo26s/.test(t) && /通用检测/.test(t)), -50],
    [(m, t) => exactKey(m) === 'yolo26n' || (/yolo26n/.test(t) && /通用检测/.test(t)), -35],
    [(m) => isGeneralCocoDetect(m), -25],
    [(m, t) => /yolo26s/.test(t) && !isSpecializedDetect(m), -5],
    [(m, t) => /yolo26n/.test(t) && !isSpecializedDetect(m), 5],
    [(m, t) => /yolo11s/.test(t) && !isSpecializedDetect(m), 15],
    [(m, t) => /yolo11n/.test(t) && !isSpecializedDetect(m), 25],
  ],
  person: [
    [(m, t) => /(person|people|pedestrian|人员|行人)/.test(t) && /(yolo26s|yolo11s)/.test(t) && !isSpecializedDetect(m), -70],
    [(m, t) => /(person|people|pedestrian|人员|行人)/.test(t) && !isSpecializedDetect(m), -55],
    [(m, t) => exactKey(m) === 'yolo26s' || (/yolo26s/.test(t) && /通用检测/.test(t)), -50],
    [(m, t) => exactKey(m) === 'yolo26n' || (/yolo26n/.test(t) && /通用检测/.test(t)), -35],
    [(m) => isGeneralCocoDetect(m), -25],
    [(m, t) => /yolo26s/.test(t) && !isSpecializedDetect(m), -5],
    [(m, t) => /yolo26n/.test(t) && !isSpecializedDetect(m), 5],
    [(m, t) => /yolo11s/.test(t) && !isSpecializedDetect(m), 15],
    [(m, t) => /yolo11n/.test(t) && !isSpecializedDetect(m), 25],
  ],
  face: [
    [(m, t) => /(buffalo[-_ ]?l)/.test(t), 0],
    [(m, t) => /(buffalo[-_ ]?s)/.test(t), 10],
    [(m, t) => /(insightface|arcface)/.test(t), 20],
  ],
}

const scoreModel = (model, scene) => {
  const text = textOf(model)
  const rules = SCENE_RULES[scene] || SCENE_RULES.general

  // 专用微调大幅降权（face 场景不套用检测排除）
  if (scene !== 'face' && isSpecializedDetect(model)) {
    return 800
  }

  for (const [test, score] of rules) {
    if (typeof test === 'function' ? test(model, text) : test.test(text)) {
      return score
    }
  }
  return 1000
}

export function pickRecommendedModel(models = [], scene = 'general') {
  const available = models.filter((model) => model && model.status !== '1' && model.filePath)
  return available
    .map((model, index) => ({ model, index, score: scoreModel(model, scene) }))
    .sort((a, b) => a.score - b.score || a.index - b.index)[0]?.model || null
}

export const recommendedModelId = (models, scene) => pickRecommendedModel(models, scene)?.id ?? null

export const isRecommendedModel = (model, models, scene) => (
  model?.id != null && model.id === recommendedModelId(models, scene)
)

/** 过滤掉不宜作为追踪默认的专用检测权重；若全被滤掉则回退原列表 */
export function filterTrackDetectModels(models = []) {
  const list = (models || []).filter((m) => m && m.status !== '1' && m.filePath)
  const general = list.filter((m) => !isSpecializedDetect(m))
  return general.length ? general : list
}

/**
 * 工作台默认检测模型：优先通用/场景适配权重，避开吸烟等专用微调。
 * @returns {number|string|null}
 */
export function pickDefaultDetectModelId(models = [], scene = 'general') {
  const pool = filterTrackDetectModels(models)
  return (
    recommendedModelId(pool, scene)
    ?? recommendedModelId(models, scene)
    ?? (pool[0] || models[0])?.id
    ?? null
  )
}
