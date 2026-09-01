const textOf = (model) => [
  model?.modelKey,
  model?.modelName,
  model?.category,
  model?.version,
  model?.filePath,
].filter(Boolean).join(' ').toLowerCase()

const SCENE_RULES = {
  general: [
    [/yolo26s/, 0],
    [/yolo26n/, 10],
    [/yolo11s/, 20],
    [/yolo11n/, 30],
    [/yolov8s/, 40],
    [/yolov8n/, 50],
  ],
  vehicle: [
    [/(vehicle|traffic|车辆|交通).*(yolo26s|yolo11s|yolov8s)/, -30],
    [/(yolo26s|yolo11s|yolov8s).*(vehicle|traffic|车辆|交通)/, -30],
    [/(vehicle|traffic|车辆|交通)/, -20],
    [/yolo26s/, 0],
    [/yolo26n/, 10],
    [/yolo11s/, 20],
    [/yolo11n/, 30],
  ],
  person: [
    [/(person|people|pedestrian|人员|行人).*(yolo26s|yolo11s)/, -30],
    [/(yolo26s|yolo11s).*(person|people|pedestrian|人员|行人)/, -30],
    [/yolo26s/, 0],
    [/yolo26n/, 10],
    [/yolo11s/, 20],
    [/yolo11n/, 30],
  ],
  face: [
    [/(buffalo[-_ ]?l)/, 0],
    [/(buffalo[-_ ]?s)/, 10],
    [/(insightface|arcface)/, 20],
  ],
}

const scoreModel = (model, scene) => {
  const text = textOf(model)
  const rules = SCENE_RULES[scene] || SCENE_RULES.general
  const hit = rules.find(([pattern]) => pattern.test(text))
  return hit ? hit[1] : 1000
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
