const SUPPORTED_WORKBENCHES = new Set([
  'segmentation',
  'vehicle_reid',
  'plate_detection',
  'obb_detection',
  'plate_pose',
  'face_recognition',
  'object_detection',
  'image_inpainting',
  'image_classification',
  'multimodal_grounding',
  'body_pose',
  'squat_counting',
  'instance_segmentation',
  'person_reid',
  'hand_pose',
  'industrial_diagnosis',
  'document_ocr',
  'text_nlp',
  'speech_asr',
  'speech_tts',
  'talking_head',
])

export const SCENARIO_GROUP_ROUTE_KEYS = [
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
  'ppe-detection',
  'smoking-detection',
  'fall-detection',
  'fight-detection',
  'weapon-detection',
  'fire-smoke',
  'mobile-phone',
  'instance-segmentation',
  'open-vocab-detection',
  'general-detection',
  'sign-language',
  'hand-pose',
  'industrial-diagnosis',
  'person-reid',
  'fish-detection',
  'badminton-ball',
  'rocket-detect',
  'document-ocr',
  'ner',
  'text-classification',
  'zero-shot-text',
  'fill-mask',
  'summarization',
  'translation',
  'question-answering',
  'text-to-speech',
  'speech-recognition',
  'talking-head',
]

export const MODEL_TO_GROUP = {
  'efficient-sam': 'interactive-segmentation',
  'mobile-sam': 'interactive-segmentation',
  'clip-reid-vehicle': 'vehicle-reid',
  'transreid-vehicle': 'vehicle-reid',
  'vehicle-vit-reid': 'vehicle-reid',
  'keremberke-yolov5m-license-plate': 'plate-detection',
  'keremberke-yolov5n-license-plate': 'plate-detection',
  'yolo26n-p2-plate': 'plate-detection',
  'yolo26n-plate': 'plate-detection',
  'yolov11-license-plate-n': 'plate-detection',
  'yolov11-license-plate-s': 'plate-detection',
  'yolov8-license-plate': 'plate-detection',
  'sec-plate-yolov8': 'plate-detection',
  'yolo26n-obb': 'obb-detection',
  'yolo-master-obb-n': 'obb-detection',
  'yolo26s-plate-pose': 'plate-pose',
  'insightface-buffalo-l': 'face-recognition',
  'insightface-buffalo-s': 'face-recognition',
  'opencv-yunet-sface': 'face-recognition',
  'brain-tumor-yolo-opennoor': 'medical-detection',
  'inpainting-lama': 'image-inpainting',
  'mobilenet-v2': 'image-classification',
  'vit-base': 'image-classification',
  'yolo-master-cls-n': 'image-classification',
  'vlm-fo1-3b': 'multimodal-grounding',
  'dwpose-m': 'body-pose',
  'rtmo-m': 'body-pose',
  'rtmo-s': 'body-pose',
  'rtmpose-m': 'body-pose',
  'yolo-master-pose-n': 'body-pose',
  'yolo11n-pose': 'body-pose',
  'yolo26n-pose': 'body-pose',
  'ppe-detection': 'ppe-detection',
  'sec-helmet-yolov8s': 'ppe-detection',
  'sec-ppe-yolo': 'ppe-detection',
  'damoyolo-cigarette': 'smoking-detection',
  'yolo26-smoking-detection': 'smoking-detection',
  'yolo8-smoking-behavior': 'smoking-detection',
  'sec-fall-yolo11n': 'fall-detection',
  'sec-fight-nano': 'fight-detection',
  'sec-fight-small': 'fight-detection',
  'sec-weapon-yolov8': 'weapon-detection',
  'sec-fire-collision-yolo11': 'fire-smoke',
  'sec-fire-forest-yolov8': 'fire-smoke',
  'sec-fire-yolov8n': 'fire-smoke',
  'fire-smoke-detection': 'fire-smoke',
  'yolov8n-mobile-phone': 'mobile-phone',
  'rf-detr-seg-medium': 'instance-segmentation',
  'yolo-master-seg-n': 'instance-segmentation',
  'yoloe-26s-seg': 'instance-segmentation',
  'omdet-turbo-swin-tiny': 'open-vocab-detection',
  'sec-fall-coco-yolov12m': 'general-detection',
  'detr-resnet-50': 'general-detection',
  'rf-detr-medium': 'general-detection',
  'yolo-master-esmoe-n': 'general-detection',
  'yolo-master-esmoe-s': 'general-detection',
  'yolo-master-v01-n': 'general-detection',
  'yolo26n': 'general-detection',
  'yolo26s': 'general-detection',
  'chinese-sign-language-tigerhhzz-yolo11s': 'sign-language',
  'opencv-handpose-mediapipe': 'hand-pose',
  'qwen3-vl-seg-cloud': 'industrial-diagnosis',
  'clip-reid-person': 'person-reid',
  'opencv-person-reid-youtu': 'person-reid',
  'osnet-x1-0': 'person-reid',
  'yolo11-fish-detector-grayscale': 'fish-detection',
  'yolo11s-ball': 'badminton-ball',
  'rocket-detect-nasaspaceflight': 'rocket-detect',
  'PP-OCRv6_small_det_onnx': 'document-ocr',
  'PP-OCRv6_small_rec_onnx': 'document-ocr',
  'rapidtable-slanet-plus': 'document-ocr',
  'yolov8m-table-extraction': 'document-ocr',
  'bert-ner': 'ner',
  'bert-emotion': 'text-classification',
  'finbert': 'text-classification',
  'bart-mnli': 'zero-shot-text',
  'bert-fill-mask': 'fill-mask',
  'distilbart-cnn': 'summarization',
  'opus-mt-en-zh': 'translation',
  'distilbert-squad': 'question-answering',
  'melotts-zh-en': 'text-to-speech',
  'mms-tts-eng': 'text-to-speech',
  'vibevoice-realtime': 'text-to-speech',
  'fun-asr-nano': 'speech-recognition',
  'moonshine-tiny': 'speech-recognition',
  'moss-transcribe-diarize-0p9b': 'speech-recognition',
  'paraformer-zh': 'speech-recognition',
  'sensevoice-small': 'speech-recognition',
  'sensevoice-small-onnx': 'speech-recognition',
  'linly-talker': 'talking-head',
}

export const LEGACY_MODEL_ROUTE_KEYS = Object.keys(MODEL_TO_GROUP)

export const SCENARIO_MODEL_COUNT = LEGACY_MODEL_ROUTE_KEYS.length

const GROUP_ROUTE_META = [
  ['aiScenarioInteractiveSegmentation', '交互分割场景'],
  ['aiScenarioVehicleReid', '车辆 ReID 场景'],
  ['aiScenarioPlateDetection', '车牌检测场景'],
  ['aiScenarioObbDetection', '旋转框 OBB 场景'],
  ['aiScenarioPlatePose', '车牌四点场景'],
  ['aiScenarioFaceRecognition', '人脸识别场景'],
  ['aiScenarioMedicalDetection', '脑部影像病灶检测场景'],
  ['aiScenarioImageInpainting', '图像修复场景'],
  ['aiScenarioImageClassification', '图像分类场景'],
  ['aiScenarioMultimodalGrounding', '多模态定位场景'],
  ['aiScenarioBodyPose', '人体姿态估计场景'],
  ['aiScenarioSquatCounting', '健身蹲起计数场景'],
  ['aiScenarioPpeDetection', 'PPE 防护检测场景'],
  ['aiScenarioSmokingDetection', '吸烟行为检测场景'],
  ['aiScenarioFallDetection', '跌倒行为检测场景'],
  ['aiScenarioFightDetection', '打架检测场景'],
  ['aiScenarioWeaponDetection', '武器检测场景'],
  ['aiScenarioFireSmoke', '烟火检测场景'],
  ['aiScenarioMobilePhone', '手机使用检测场景'],
  ['aiScenarioInstanceSegmentation', '实例分割场景'],
  ['aiScenarioOpenVocabDetection', '开放词汇检测场景'],
  ['aiScenarioGeneralDetection', '通用目标检测场景'],
  ['aiScenarioSignLanguage', '手语识别场景'],
  ['aiScenarioHandPose', '手部姿态场景'],
  ['aiScenarioIndustrialDiagnosis', '工业缺陷诊断场景'],
  ['aiScenarioPersonReid', '行人 ReID 场景'],
  ['aiScenarioFishDetection', '鱼类检测场景'],
  ['aiScenarioBadmintonBall', '羽毛球检测场景'],
  ['aiScenarioRocketDetect', '火箭回收检测场景'],
  ['aiScenarioDocumentOcr', '文档 OCR 场景'],
  ['aiScenarioNer', '命名实体识别场景'],
  ['aiScenarioTextClassification', '文本分类场景'],
  ['aiScenarioZeroShotText', '零样本文本分类场景'],
  ['aiScenarioFillMask', '完形填空场景'],
  ['aiScenarioSummarization', '文本摘要场景'],
  ['aiScenarioTranslation', '机器翻译场景'],
  ['aiScenarioQuestionAnswering', '抽取式问答场景'],
  ['aiScenarioTextToSpeech', '语音合成场景'],
  ['aiScenarioSpeechRecognition', '语音识别场景'],
  ['aiScenarioTalkingHead', '数字人场景'],
]

export function resolveGroupKey(modelOrGroupKey) {
  if (typeof modelOrGroupKey !== 'string' || !modelOrGroupKey) return null
  if (SCENARIO_GROUP_ROUTE_KEYS.includes(modelOrGroupKey)) return modelOrGroupKey
  return MODEL_TO_GROUP[modelOrGroupKey] || null
}

export function createScenarioRouteRecords(component) {
  return SCENARIO_GROUP_ROUTE_KEYS.map((groupKey, index) => ({
    path: `ai/scenarios/${groupKey}`,
    name: GROUP_ROUTE_META[index][0],
    component,
    props: { groupKey },
    meta: { title: GROUP_ROUTE_META[index][1], groupKey },
  }))
}

export function createLegacyScenarioRedirectRecords() {
  return LEGACY_MODEL_ROUTE_KEYS.map((modelKey) => {
    const groupKey = MODEL_TO_GROUP[modelKey]
    return {
      path: `ai/scenarios/${modelKey}`,
      redirect: (to) => ({
        path: `/ai/scenarios/${groupKey}`,
        query: { ...to.query, model: typeof to.query.model === 'string' ? to.query.model : modelKey },
      }),
    }
  })
}

export function createAsyncRequestGuard() {
  let generation = 0
  let active = true
  return {
    begin() {
      if (!active) return null
      generation += 1
      return generation
    },
    isCurrent(token) {
      return active && token !== null && token === generation
    },
    dispose() {
      active = false
      generation += 1
    },
  }
}

export function resolveWorkbench(type) {
  return SUPPORTED_WORKBENCHES.has(type) ? type : null
}

export function resolveFixedGroupKey(route) {
  return typeof route?.meta?.groupKey === 'string' ? route.meta.groupKey : null
}

export function resolveQueryModelKey(route) {
  const value = route?.query?.model
  return typeof value === 'string' && value ? value : null
}

export function pickScenarioModel(group, modelKey) {
  const models = Array.isArray(group?.models) ? group.models : []
  if (!models.length) return null
  return models.find((item) => item.modelKey === modelKey)
    || models.find((item) => item.modelKey === group?.selectedModelKey)
    || models.find((item) => item.modelKey === group?.defaultModelKey)
    || models[0]
    || null
}

export function mergeSelectedScenario(group, modelKey) {
  if (!group || typeof group !== 'object') return null
  const selected = pickScenarioModel(group, modelKey)
  if (!selected) {
    return group.modelKey ? group : null
  }
  return {
    ...group,
    ...selected,
    groupKey: group.groupKey,
    name: group.name,
    project: group.project,
    description: group.description,
    workbenchType: group.workbenchType || selected.workbenchType,
    ability: group.ability || selected.ability,
    order: group.order,
    phase: group.phase ?? selected.phase,
    route: group.route,
    workflow: group.workflow,
    outputs: group.outputs,
    metrics: group.metrics,
    risks: group.risks,
    modelKey: selected.modelKey,
    modelName: selected.name,
    defaults: selected.defaults,
    adapter: selected.adapter,
    apiPath: selected.apiPath,
    input: selected.input ?? group.input,
    configured: selected.configured,
    enabled: selected.enabled,
    weightsPresent: selected.weightsPresent,
    runtimeAvailable: selected.runtimeAvailable,
    apiReady: selected.apiReady ?? selected.ready,
    ready: selected.apiReady ?? selected.ready,
    reason: selected.reason,
    models: group.models,
    modelCount: group.modelCount ?? group.models?.length,
    defaultModelKey: group.defaultModelKey,
    selectedModelKey: selected.modelKey,
    anyReady: group.anyReady,
  }
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

function classificationFields(scenario) {
  const fields = [
    { name: 'file', required: true, description: '待分类图片。' },
    { name: 'topK', required: false, description: `1—20 返回类别数，默认 ${scenario.defaults?.topK ?? 5}。` },
  ]
  if (scenario.modelKey === 'mobilenet-v2') {
    fields.push({
      name: 'precision',
      required: false,
      description: `ONNX 精度偏好，可选 fp32 或 int8，默认 ${scenario.defaults?.precision ?? 'fp32'}。`,
    })
  }
  if (scenario.modelKey === 'yolo-master-cls-n') {
    fields.push({
      name: 'conf',
      required: false,
      description: `0—1 置信度阈值，默认 ${scenario.defaults?.conf ?? 0.25}。`,
    })
  }
  return fields
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
  if (scenario.workbenchType === 'face_recognition') {
    return [
      { name: 'file', required: true, description: '待识别人脸图片。' },
      { name: 'threshold', required: false, description: `0—1 匹配阈值，默认 ${scenario.defaults?.threshold ?? 0.4}。` },
      { name: 'detThresh', required: false, description: `0—1 人脸检测阈值，默认 ${scenario.defaults?.detThresh ?? 0.5}。` },
    ]
  }
  if (scenario.workbenchType === 'image_inpainting') {
    return [
      { name: 'file', required: true, description: '待修复原图。' },
      { name: 'mask', required: true, description: '遮罩图，白色区域为修复区域。' },
      { name: 'dilatePx', required: false, description: `0—64 遮罩膨胀像素，默认 ${scenario.defaults?.dilatePx ?? 0}。` },
    ]
  }
  if (scenario.workbenchType === 'image_classification') {
    return classificationFields(scenario)
  }
  if (scenario.workbenchType === 'multimodal_grounding' || scenario.workbenchType === 'industrial_diagnosis') {
    return [
      { name: 'file', required: true, description: '待定位/诊断图片。' },
      { name: 'prompt', required: scenario.workbenchType === 'multimodal_grounding', description: `自然语言目标描述或诊断场景词，默认 ${scenario.defaults?.prompt ?? scenario.defaults?.scenario ?? 'person'}。` },
      { name: 'conf', required: false, description: `0—1 置信度阈值，默认 ${scenario.defaults?.conf ?? 0.25}。` },
    ]
  }
  if (scenario.workbenchType === 'body_pose' || scenario.workbenchType === 'hand_pose') {
    return [
      { name: 'file', required: true, description: '待估计姿态图片。' },
      { name: 'conf', required: false, description: `0—1 置信度阈值，默认 ${scenario.defaults?.conf ?? 0.25}。` },
    ]
  }
  if (scenario.workbenchType === 'person_reid') {
    return [
      { name: 'query', required: true, description: '查询行人图片。' },
      { name: 'gallery', required: true, description: '候选行人图片，可重复提交。' },
      { name: 'threshold', required: false, description: `0—1 相似度阈值，默认 ${scenario.defaults?.threshold ?? 0.7}。` },
    ]
  }
  if (scenario.workbenchType === 'text_nlp') {
    const ability = scenario.ability || ''
    if (ability === 'question-answering') {
      return [
        { name: 'question', required: true, description: '问题文本。' },
        { name: 'context', required: true, description: '上下文段落。' },
      ]
    }
    const fields = [{ name: 'text', required: true, description: '待处理文本。' }]
    if (ability === 'zero-shot-classification') {
      fields.push({ name: 'labels', required: true, description: '逗号分隔候选标签，至少两个。' })
    }
    if (ability === 'fill-mask') {
      fields.push({ name: 'topK', required: false, description: `返回候选数，默认 ${scenario.defaults?.topK ?? 5}。` })
    }
    return fields
  }
  if (scenario.workbenchType === 'speech_tts') {
    return [
      { name: 'text', required: true, description: '待合成文本。' },
      { name: 'speaker', required: false, description: `说话人标识，默认 ${scenario.defaults?.speaker ?? 'model-default'}。` },
    ]
  }
  if (scenario.workbenchType === 'speech_asr') {
    return [{ name: 'file', required: true, description: '待识别音频文件。' }]
  }
  if (scenario.workbenchType === 'talking_head') {
    return [
      { name: 'file', required: true, description: '人物图片。' },
      { name: 'audio', required: true, description: '驱动音频。' },
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
  if (scenario.workbenchType === 'vehicle_reid' || scenario.workbenchType === 'person_reid') {
    return [
      '-F "query=@query.jpg"',
      '-F "gallery=@candidate-01.jpg"',
      `-F "threshold=${scenario.defaults?.threshold ?? 0.7}"`,
    ]
  }
  if (scenario.workbenchType === 'text_nlp') {
    const ability = scenario.ability || ''
    if (ability === 'question-answering') {
      return ['-F "question=Who founded the company?"', '-F "context=..."']
    }
    const fields = ['-F "text=example input"']
    if (ability === 'zero-shot-classification') fields.push('-F "labels=positive,negative,neutral"')
    if (ability === 'fill-mask') fields.push(`-F "topK=${scenario.defaults?.topK ?? 5}"`)
    return fields
  }
  if (scenario.workbenchType === 'speech_tts') {
    return [
      '-F "text=Hello TigerPro"',
      `-F "speaker=${scenario.defaults?.speaker ?? 'en-Carter_man'}"`,
    ]
  }
  if (scenario.workbenchType === 'speech_asr') {
    return ['-F "file=@audio.wav"']
  }
  if (scenario.workbenchType === 'talking_head') {
    return ['-F "file=@portrait.jpg"', '-F "audio=@drive.wav"']
  }
  if (scenario.workbenchType === 'face_recognition') {
    return [
      '-F "file=@face.jpg"',
      `-F "threshold=${scenario.defaults?.threshold ?? 0.4}"`,
      `-F "detThresh=${scenario.defaults?.detThresh ?? 0.5}"`,
    ]
  }
  if (scenario.workbenchType === 'image_inpainting') {
    return [
      '-F "file=@input.jpg"',
      '-F "mask=@mask.png"',
      `-F "dilatePx=${scenario.defaults?.dilatePx ?? 0}"`,
    ]
  }
  if (scenario.workbenchType === 'image_classification') {
    const fields = [
      '-F "file=@input.jpg"',
      `-F "topK=${scenario.defaults?.topK ?? 5}"`,
    ]
    if (scenario.modelKey === 'mobilenet-v2') {
      fields.push(`-F "precision=${scenario.defaults?.precision ?? 'fp32'}"`)
    }
    if (scenario.modelKey === 'yolo-master-cls-n') {
      fields.push(`-F "conf=${scenario.defaults?.conf ?? 0.25}"`)
    }
    return fields
  }
  if (scenario.workbenchType === 'multimodal_grounding' || scenario.workbenchType === 'industrial_diagnosis') {
    return [
      '-F "file=@input.jpg"',
      `-F "prompt=${scenario.defaults?.prompt ?? scenario.defaults?.scenario ?? 'person'}"`,
      `-F "conf=${scenario.defaults?.conf ?? 0.25}"`,
    ]
  }
  if (scenario.workbenchType === 'body_pose' || scenario.workbenchType === 'hand_pose') {
    return [
      '-F "file=@input.jpg"',
      `-F "conf=${scenario.defaults?.conf ?? 0.25}"`,
    ]
  }
  return [
    '-F "file=@input.jpg"',
    `-F "conf=${scenario.defaults?.conf ?? 0.5}"`,
    `-F "imgsz=${scenario.defaults?.imgsz ?? 640}"`,
  ]
}

function detectionClassName(workbenchType) {
  if (workbenchType === 'segmentation') return 'segment'
  if (workbenchType === 'plate_detection' || workbenchType === 'plate_pose') return 'plate'
  if (workbenchType === 'face_recognition') return 'Alice'
  if (workbenchType === 'object_detection') return 'tumor'
  if (workbenchType === 'multimodal_grounding') return 'person'
  return 'vehicle'
}

function normalizedResult(workbenchType) {
  if (workbenchType === 'vehicle_reid' || workbenchType === 'person_reid') {
    return {
      query: 'query.jpg',
      backend: { backend: workbenchType === 'person_reid' ? 'person-reid' : 'vehicle-onnx', dim: 768, inputSize: '256x256' },
      matches: [{
        filename: 'candidate-01.jpg', similarity: 0.86, distance: 0.14,
        matched: true, sourceIndex: 0, rank: 1,
      }],
    }
  }
  if (workbenchType === 'image_inpainting') {
    return {
      imageBase64: '<BASE64_JPEG>',
      maskPreviewBase64: '<BASE64_PNG>',
      width: 1280,
      height: 720,
      dilatePx: 0,
      maskPixels: 12040,
    }
  }
  if (workbenchType === 'image_classification') {
    return {
      results: [
        { label: 'sports car', score: 0.82 },
        { label: 'convertible', score: 0.11 },
      ],
      top: { label: 'sports car', score: 0.82 },
      topK: 5,
    }
  }
  if (workbenchType === 'body_pose' || workbenchType === 'hand_pose') {
    return {
      persons: [{ bbox: [100, 40, 420, 680], score: 0.91, keypoints: [[160, 80, 0.95], [200, 120, 0.93]] }],
      count: 1,
      imageBase64: '<BASE64_JPEG>',
      width: 1280,
      height: 720,
      keypointCount: workbenchType === 'hand_pose' ? 21 : 17,
      poseType: workbenchType === 'hand_pose' ? 'hand' : 'body',
    }
  }
  if (workbenchType === 'text_nlp') {
    return { text: 'example', results: [{ label: 'ORG', score: 0.92 }] }
  }
  if (workbenchType === 'speech_asr') {
    return { text: 'transcribed speech', language: 'zh' }
  }
  if (workbenchType === 'speech_tts') {
    return { audioBase64: '<BASE64_WAV>', format: 'wav' }
  }
  if (workbenchType === 'talking_head') {
    return { videoBase64: '<BASE64_MP4>', format: 'mp4' }
  }
  const detection = {
    className: detectionClassName(workbenchType),
    classId: 0,
    confidence: workbenchType === 'obb_detection' ? 0.91 : 0.88,
    bbox: [120, 80, 420, 260],
  }
  if (workbenchType === 'segmentation') {
    detection.maskBase64 = '<BASE64_PNG>'
    detection.areaPixels = 48320
    detection.areaRatio = 0.0524
  }
  if (workbenchType === 'obb_detection' || workbenchType === 'plate_pose') {
    detection.quad = [[130, 70], [430, 100], [410, 270], [110, 240]]
  }
  if (workbenchType === 'obb_detection') {
    detection.angle = 5.71
    detection.angleUnit = 'degrees'
  }
  if (workbenchType === 'plate_pose') {
    detection.keypoints = [[130, 70, 0.98], [430, 100, 0.97], [410, 270, 0.96], [110, 240, 0.95]]
  }
  if (workbenchType === 'face_recognition') {
    detection.name = 'Alice'
    detection.score = 0.88
    detection.matched = true
    detection.confidence = 0.88
  }
  return {
    detections: [detection],
    count: 1,
    imageBase64: '<BASE64_JPEG>',
    width: 1280,
    height: 720,
    ...(workbenchType === 'multimodal_grounding' || workbenchType === 'industrial_diagnosis'
      ? { prompt: 'person' }
      : {}),
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
    '  -H "X-Timestamp: <UNIX_SECONDS>" \\',
    '  -H "X-Nonce: <UNIQUE_NONCE>" \\',
    '  -H "X-Signature: <HMAC_SHA256>" \\',
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

  if (type === 'vehicle_reid' || type === 'person_reid') {
    if (state.query) form.append('query', state.query)
    for (const file of state.gallery || []) form.append('gallery', file)
    appendValue(form, 'threshold', state.threshold)
    return form
  }

  if (type === 'text_nlp') {
    appendValue(form, 'text', state.text)
    appendValue(form, 'labels', state.labels)
    appendValue(form, 'question', state.question)
    appendValue(form, 'context', state.context)
    appendValue(form, 'topK', state.topK)
    return form
  }

  if (type === 'speech_tts') {
    appendValue(form, 'text', state.text)
    appendValue(form, 'speaker', state.speaker)
    return form
  }

  if (type === 'speech_asr') {
    if (state.file) form.append('file', state.file)
    appendValue(form, 'language', state.language)
    return form
  }

  if (type === 'talking_head') {
    if (state.file) form.append('file', state.file)
    if (state.audio) form.append('audio', state.audio)
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

  if (type === 'face_recognition') {
    appendValue(form, 'threshold', state.threshold)
    appendValue(form, 'detThresh', state.detThresh)
    return form
  }

  if (type === 'image_inpainting') {
    if (state.mask) form.append('mask', state.mask)
    appendValue(form, 'dilatePx', state.dilatePx)
    return form
  }

  if (type === 'image_classification') {
    appendValue(form, 'topK', state.topK)
    appendValue(form, 'precision', state.precision)
    appendValue(form, 'conf', state.conf)
    return form
  }

  if (type === 'multimodal_grounding' || type === 'industrial_diagnosis') {
    appendValue(form, 'prompt', state.prompt)
    appendValue(form, 'classes', state.classes)
    appendValue(form, 'conf', state.conf)
    return form
  }

  if (type === 'body_pose' || type === 'hand_pose') {
    appendValue(form, 'conf', state.conf)
    return form
  }

  if (
    type === 'plate_detection'
    || type === 'obb_detection'
    || type === 'plate_pose'
    || type === 'object_detection'
    || type === 'instance_segmentation'
    || type === 'document_ocr'
  ) {
    appendValue(form, 'conf', state.conf)
    appendValue(form, 'imgsz', state.imgsz)
    appendValue(form, 'classes', state.classes)
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
  if (type === 'vehicle_reid' || type === 'person_reid') {
    const subject = type === 'person_reid' ? '行人' : '车辆'
    if (!state.query) errors.push(`请选择查询${subject}图片。`)
    if (!Array.isArray(state.gallery) || state.gallery.length === 0) {
      errors.push(`请至少选择一张候选${subject}图片。`)
    }
    const maxGalleryImages = Number(inputPolicy.maxGalleryImages)
    if (maxGalleryImages > 0 && (state.gallery || []).length > maxGalleryImages) {
      errors.push(`候选图片最多 ${maxGalleryImages} 张。`)
    }
    const queryError = imagePolicyError(state.query, inputPolicy)
    if (queryError) errors.push(queryError)
    const galleryError = (state.gallery || []).map((file) => imagePolicyError(file, inputPolicy)).find(Boolean)
    if (galleryError) errors.push(galleryError)
    if (!validUnitInterval(Number(state.threshold))) errors.push('相似度阈值必须在 0 到 1 之间。')
    return errors
  }

  if (type === 'text_nlp') {
    const ability = state.ability || ''
    if (ability === 'question-answering') {
      if (!String(state.question || '').trim()) errors.push('请填写问题。')
      if (!String(state.context || '').trim()) errors.push('请填写上下文。')
    } else if (!String(state.text || '').trim()) {
      errors.push('请填写待处理文本。')
    }
    if (ability === 'zero-shot-classification') {
      const labels = String(state.labels || '').split(',').map((item) => item.trim()).filter(Boolean)
      if (labels.length < 2) errors.push('请至少填写两个候选标签（逗号分隔）。')
    }
    return errors
  }

  if (type === 'speech_tts') {
    if (!String(state.text || '').trim()) errors.push('请填写待合成文本。')
    return errors
  }

  if (type === 'speech_asr') {
    if (!state.file) errors.push('请选择音频文件。')
    return errors
  }

  if (type === 'talking_head') {
    if (!state.file) errors.push('请选择人物图片。')
    if (!state.audio) errors.push('请选择驱动音频。')
    return errors
  }

  if (type === 'image_inpainting') {
    if (!state.file) errors.push('请选择待修复图片。')
    if (!state.mask) errors.push('请选择遮罩图片。')
    const fileError = imagePolicyError(state.file, inputPolicy)
    if (fileError) errors.push(fileError)
    const maskError = imagePolicyError(state.mask, inputPolicy)
    if (maskError) errors.push(maskError)
    const dilate = Number(state.dilatePx)
    if (!Number.isInteger(dilate) || dilate < 0 || dilate > 64) {
      errors.push('遮罩膨胀必须是 0 到 64 的整数。')
    }
    return errors
  }

  if (!state.file) errors.push('请选择待处理图片。')
  const fileError = imagePolicyError(state.file, inputPolicy)
  if (fileError) errors.push(fileError)
  if (type === 'segmentation') {
    const points = Array.isArray(state.points) ? state.points : []
    const labels = Array.isArray(state.pointLabels) ? state.pointLabels : []
    if (points.length !== labels.length) errors.push('正负点标签必须与提示点一一对应。')
    const maxPrompts = Number(inputPolicy.maxPrompts)
    if (maxPrompts > 0 && points.length + (state.box ? 1 : 0) > maxPrompts) {
      errors.push(`提示最多 ${maxPrompts} 个。`)
    }
    if (state.mode !== 'auto' && points.length === 0 && !state.box) {
      errors.push('请添加至少一个提示点或框选区域。')
    }
    return errors
  }

  if (type === 'face_recognition') {
    if (!validUnitInterval(Number(state.threshold))) errors.push('匹配阈值必须在 0 到 1 之间。')
    if (!validUnitInterval(Number(state.detThresh))) errors.push('检测阈值必须在 0 到 1 之间。')
    return errors
  }

  if (type === 'image_classification') {
    const topK = Number(state.topK)
    if (!Number.isInteger(topK) || topK < 1 || topK > 20) {
      errors.push('Top-K 必须是 1 到 20 的整数。')
    }
    if (state.precision !== undefined && state.precision !== null && state.precision !== '') {
      if (!['fp32', 'int8'].includes(String(state.precision))) {
        errors.push('精度必须是 fp32 或 int8。')
      }
    }
    if (state.conf !== undefined && state.conf !== null && state.conf !== '') {
      if (!validUnitInterval(Number(state.conf))) errors.push('置信度阈值必须在 0 到 1 之间。')
    }
    return errors
  }

  if (type === 'multimodal_grounding' || type === 'industrial_diagnosis') {
    const prompt = typeof state.prompt === 'string' ? state.prompt.trim() : ''
    if (type === 'multimodal_grounding') {
      if (!prompt) errors.push('请填写定位提示词。')
      else if (prompt.length > 500) errors.push('定位提示词最多 500 个字符。')
    } else if (prompt.length > 500) {
      errors.push('诊断场景词最多 500 个字符。')
    }
    if (!validUnitInterval(Number(state.conf))) errors.push('置信度阈值必须在 0 到 1 之间。')
    return errors
  }

  if (type === 'body_pose' || type === 'hand_pose') {
    if (!validUnitInterval(Number(state.conf))) errors.push('置信度阈值必须在 0 到 1 之间。')
    return errors
  }

  if (!validUnitInterval(Number(state.conf))) errors.push('置信度阈值必须在 0 到 1 之间。')
  if (!Number.isInteger(Number(state.imgsz)) || Number(state.imgsz) < 32 || Number(state.imgsz) > 4096) {
    errors.push('推理尺寸必须是 32 到 4096 的整数。')
  }
  return errors
}

export function validateSquatParameters(state = {}) {
  const errors = []
  const standing = Number(state.standingAngle)
  const bottom = Number(state.bottomAngle)
  const confirmFrames = Number(state.confirmFrames ?? 3)
  if (!Number.isFinite(standing) || !Number.isFinite(bottom) || standing <= bottom) {
    errors.push('站立阈值必须大于下蹲阈值')
  }
  if (standing > 180 || bottom <= 0) errors.push('动作角度必须在 0 到 180 度之间')
  if (!Number.isInteger(confirmFrames) || confirmFrames < 1 || confirmFrames > 30) {
    errors.push('连续确认帧数必须是 1 到 30 的整数')
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

function normalizeKeypoints(value) {
  if (!Array.isArray(value) || !value.length) return undefined
  const points = value.map((point) => {
    if (!Array.isArray(point) || point.length < 2) return null
    const x = Number(point[0])
    const y = Number(point[1])
    if (!isFiniteNumber(x) || !isFiniteNumber(y)) return null
    if (point.length >= 3 && isFiniteNumber(Number(point[2]))) {
      return [x, y, Number(point[2])]
    }
    return [x, y]
  })
  return points.every(Boolean) ? points : undefined
}

function normalizeLandmarks(value) {
  if (!Array.isArray(value) || !value.length) return undefined
  const points = value.map((point) => normalizeNumberList(point, 2))
  return points.every(Boolean) ? points : undefined
}

function normalizeDetection(item) {
  if (!item || typeof item !== 'object') return {}
  const normalized = { ...item }
  const bbox = normalizeNumberList(item.bbox, 4)
  const quad = normalizeQuad(item.quad)
  const keypoints = normalizeKeypoints(item.keypoints)
  const landmarks = normalizeLandmarks(item.landmarks)
  if (bbox) normalized.bbox = bbox
  else delete normalized.bbox
  if (quad) normalized.quad = quad
  else delete normalized.quad
  if (keypoints) normalized.keypoints = keypoints
  else delete normalized.keypoints
  if (landmarks) normalized.landmarks = landmarks
  else delete normalized.landmarks
  if (!isFiniteNumber(item.confidence)) delete normalized.confidence
  if (!isFiniteNumber(item.score)) delete normalized.score
  if (!isFiniteNumber(item.angle)) delete normalized.angle
  if (typeof item.matched !== 'boolean') delete normalized.matched
  return normalized
}

export function normalizeWorkbenchResult(type, value) {
  const source = value && typeof value === 'object' ? value : {}
  if (type === 'vehicle_reid' || type === 'person_reid') {
    const sourceMatches = Array.isArray(source.matches) ? source.matches : []
    const hasServerRanks = sourceMatches.length > 0 && sourceMatches.every(
      (item) => Number.isInteger(item?.rank) && item.rank > 0,
    )
    const matches = sourceMatches
      .map((item, fallbackIndex) => {
        const match = item && typeof item === 'object' ? { ...item } : {}
        if (!isFiniteNumber(item?.similarity)) delete match.similarity
        if (!isFiniteNumber(item?.distance)) delete match.distance
        if (typeof item?.matched !== 'boolean') delete match.matched
        if (!Number.isInteger(item?.rank) || item.rank < 1) delete match.rank
        if (!Number.isInteger(item?.sourceIndex) || item.sourceIndex < 0) delete match.sourceIndex
        return {
          ...match,
          galleryIndex: Number.isInteger(match.sourceIndex) ? match.sourceIndex : fallbackIndex,
        }
      }).sort((left, right) => {
        if (hasServerRanks) return left.rank - right.rank
        const leftScore = isFiniteNumber(left.similarity) ? left.similarity : -Infinity
        const rightScore = isFiniteNumber(right.similarity) ? right.similarity : -Infinity
        return rightScore - leftScore || left.galleryIndex - right.galleryIndex
      })
    return { ...source, matches }
  }
  if (type === 'image_inpainting') {
    return { ...source }
  }
  if (type === 'image_classification') {
    const results = (Array.isArray(source.results) ? source.results : [])
      .map((item) => {
        if (!item || typeof item !== 'object') return null
        const entry = { ...item }
        if (typeof item.label !== 'string' || !item.label) return null
        if (!isFiniteNumber(item.score)) delete entry.score
        return entry
      })
      .filter(Boolean)
    return {
      ...source,
      results,
      top: results[0] || (source.top && typeof source.top === 'object' ? source.top : null),
    }
  }
  if (type === 'body_pose' || type === 'hand_pose') {
    const sourceEntries = Array.isArray(source.persons)
      ? source.persons
      : (Array.isArray(source.hands) ? source.hands : [])
    const persons = sourceEntries.map((item) => {
      if (!item || typeof item !== 'object') return {}
      const person = { ...item }
      const bbox = normalizeNumberList(item.bbox, 4)
      const keypoints = normalizeKeypoints(item.keypoints)
      if (bbox) person.bbox = bbox
      else delete person.bbox
      if (keypoints) person.keypoints = keypoints
      else delete person.keypoints
      if (!isFiniteNumber(item.score)) delete person.score
      if (!isFiniteNumber(item.confidence)) delete person.confidence
      return person
    })
    return {
      ...source,
      persons,
      hands: type === 'hand_pose' ? persons : source.hands,
      count: Number.isInteger(source.count) ? source.count : persons.length,
    }
  }
  if (type === 'text_nlp' || type === 'speech_asr' || type === 'speech_tts' || type === 'talking_head') {
    return { ...source }
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
    const keypoints = normalizeKeypoints(detection.keypoints)?.map((point) => {
      const scaled = [
        clamp(point[0] * scaleX, 0, targetWidth),
        clamp(point[1] * scaleY, 0, targetHeight),
      ]
      if (point.length >= 3) scaled.push(point[2])
      return scaled
    })
    const landmarks = normalizeLandmarks(detection.landmarks)?.map(([x, y]) => [
      clamp(x * scaleX, 0, targetWidth),
      clamp(y * scaleY, 0, targetHeight),
    ])
    const angle = isFiniteNumber(detection.angle) ? detection.angle : quadAngle(sourceQuad)
    return {
      index,
      ...(bbox ? { bbox } : {}),
      ...(quad ? { quad } : {}),
      ...(keypoints ? { keypoints } : {}),
      ...(landmarks ? { landmarks } : {}),
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
