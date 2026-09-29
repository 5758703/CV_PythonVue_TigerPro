/**
 * 选中模型详细说明解析：精确 key → 家族模式 → 分类/任务兜底，并合并 API description。
 */

const PAGE_TIPS = {
  image: '本页适合单张静态图核验：调置信度、看框与类别表，可配合 DeepSeek 报告。',
  video: '本页对整段视频逐帧/抽帧检测，输出叠加视频与统计；耗时与分辨率、模型体量相关。',
  camera: '本页实时拉流推理，优先选 nano/small 或 INT8 类轻量模型，保证帧率。',
  imgcls: '本页对单张图做 Top-K 分类；DNN 可切 FP32/INT8，ViT 偏精度对照。',
  livecls: '本页摄像头实时分类，默认 INT8；画面叠 Top-3 与耗时，适合现场演示。',
  ocr: '本页端到端读图出字；大模型 OCR 在 CPU 上较慢，复杂版面可开「格式化输出」。',
}

/** @type {Record<string, object>} */
const EXACT = {
  'yolo26n': {
    summary: 'Ultralytics YOLO26 Nano：COCO 80 类通用目标检测，体量小、推理快，是平台默认通用检测基线之一。',
    scenarios: ['安防巡检原型', '人车基础盘点', '课堂/实验室演示', '实时摄像头预览'],
    effects: ['输出带类别与置信度的检测框', '可叠加到图片/视频/监控画面', '配合告警规则触发烟火/PPE/越线等'],
    tips: ['实时场景优先选 n/s', '小目标可适当降低置信度', '专用场景（烟火/PPE/人脸）请换对应微调权重'],
  },
  'yolo26s': {
    summary: 'YOLO26 Small：比 Nano 更准、略慢，适合对召回率要求更高的通用检测。',
    scenarios: ['厂区通道监控', '仓库货品粗检', '视频离线复核'],
    effects: ['同类 COCO 检测能力，漏检相对更少', '仍可在中端 CPU/GPU 上较流畅运行'],
    tips: ['摄像头页若掉帧可回退到 yolo26n', '告警场景建议先在图片页标定阈值'],
  },
  'omdet-turbo-swin-tiny': {
    summary: 'OmDet-Turbo（开放词汇）：不局限于固定训练集类别，按你填写的英文类别列表做零样本检测。',
    scenarios: ['临时盘点未训练过的物品', '用文本快速试探「有没有某类物体」', '与固定类 YOLO 对照验证'],
    effects: ['按提示类别出框', '无需为新类重新训练即可试跑'],
    tips: ['类别用英文逗号分隔，如 person,hardhat,tomato', '留空则用内置默认类', '复杂场景召回可能不如专用微调 YOLO'],
  },
  'vlm-fo1-3b': {
    summary: 'VLM-FO1 多模态定位：用自然语言描述目标（或 REC），结合 YOLO 候选做细粒度筛选。',
    scenarios: ['「找出左侧红色灭火器」类指令', '细粒度指代定位', '多模态工作台演示'],
    effects: ['按语言描述定位目标区域', '适合解释型交互，不只是固定类别列表'],
    tips: ['需先运行 setup_vlm_fo1.py 并拉取约 9GB 权重', '建议 GPU', '可填自然语言或快捷类别'],
  },
  'rf-detr-medium': {
    summary: 'Roboflow RF-DETR Medium：基于 DETR 思路的现代检测器，COCO 80 类，精度与速度较均衡。',
    scenarios: ['通用目标检测对照实验', '需要更稳框质量的图片检测', '与 YOLO 系列做效果对比'],
    effects: ['标准检测框 + 类别', '对部分拥挤/遮挡场景框更稳'],
    tips: ['首次推理可能较慢（加载权重）', '实时页请关注帧率，必要时换 YOLO Nano'],
  },
  'detr-resnet-50': {
    summary: 'Facebook DETR（ResNet-50）：经典端到端检测，transformers 引擎，适合图片检测对照。',
    scenarios: ['学术/教学对比', '单张图精细检测', '不追求极致实时的离线分析'],
    effects: ['COCO 类别检测框', '端到端预测，后处理相对简洁'],
    tips: ['CPU 推理偏慢，不建议作为摄像头默认模型', '视频页耗时会明显增加'],
  },
  'ppe-detection': {
    summary: '个人防护装备（PPE）检测：识别安全帽、背心等劳保穿戴情况，常用于工地/厂区合规。',
    scenarios: ['工地入场检查', '厂区通道合规抽检', '配合「告警中心」PPE 规则'],
    effects: ['标出佩戴/未佩戴相关目标', '可驱动未戴帽等告警事件'],
    tips: ['启用告警后请到告警中心打开对应规则', '拍摄角度与光照影响很大，建议现场标定置信度'],
  },
  'fire-smoke-detection': {
    summary: '烟火检测专用权重：面向火焰与烟雾目标，适合消防预警演示与园区监控。',
    scenarios: ['仓库/厨房烟雾预警演示', '林区/园区烟火巡检原型', '告警中心烟火规则联调'],
    effects: ['检出火焰/烟雾区域并出框', '可叠加到视频与监控墙'],
    tips: ['反光、蒸汽易误报，请结合规则冷却时间', '实时页建议轻量烟火模型'],
  },
  'vit-base': {
    summary: 'Google ViT-Base：ImageNet-1000 图像分类，精度较好，适合单张图 Top-K 识别。',
    scenarios: ['物体类别对照', '教学演示 ImageNet 标签', '与 MobileNet 做精度对比'],
    effects: ['输出 Top-K 中英文类别与分数', '返回推理耗时等元信息'],
    tips: ['实时分类页更推荐 MobileNet INT8', '首次加载 transformers 权重较慢'],
  },
  'mobilenet-v2': {
    summary: 'MobileNet V2（OpenCV DNN）：ImageNet-1000，提供 FP32/INT8，专为实时与边缘场景优化。',
    scenarios: ['摄像头实时分类', '展台互动演示', '低算力设备预览'],
    effects: ['画面叠加 Top 类别与置信度', 'INT8 延迟更低，FP32 可作精度对照'],
    tips: ['实时分类默认 INT8', '需在模型管理绑定本地双 ONNX + labels'],
  },
  'yolo-master-cls-n': {
    summary: 'YOLO-Master 分类 Nano：轻量图像分类，适合快速验证分类链路。',
    scenarios: ['分类 API 联调', '轻量部署试验'],
    effects: ['输出类别与分数', '体量小、启动快'],
    tips: ['标签空间以模型自带类别为准', '与 ImageNet ViT 结果不可直接数值对比'],
  },
  'Falconsai-nsfw_image_detection': {
    summary: 'NSFW 图像安全分类：判断画面是否含不适宜内容，用于内容审核演示。',
    scenarios: ['UGC 预审演示', '内容安全巡检原型'],
    effects: ['输出安全/风险相关类别与置信度'],
    tips: ['阈值需按业务校准', '误杀/漏杀需人工复核，不能作为唯一依据'],
  },
  'stepfun-ai-GOT-OCR2_0': {
    summary: 'GOT-OCR2 端到端文字识别：整图读字，支持普通文本与一定结构化版面。',
    scenarios: ['单据/截图转文字', '白板/教材拍照录入', '需要格式化段落的 OCR'],
    effects: ['输出纯文本或格式化文本', '可复制/下载 .txt'],
    tips: ['CPU 推理较慢，请耐心等待', '复杂表格可再试「表格识别」页', '小字/模糊图先提高清晰度'],
  },
}

const FAMILY = [
  {
    test: (k) => /omdet/i.test(k),
    guide: EXACT['omdet-turbo-swin-tiny'],
  },
  {
    test: (k) => /vlm[-_]?fo1/i.test(k),
    guide: EXACT['vlm-fo1-3b'],
  },
  {
    test: (k) => /rf[-_]?detr/i.test(k),
    guide: {
      summary: 'RF-DETR 系列：Roboflow 检测/分割家族，适合通用目标检测与对照实验。',
      scenarios: ['通用检测', '与 YOLO 精度对照', '图片/视频检测页'],
      effects: ['稳定检测框与类别', '部分分割变体可出掩膜（请到分割页）'],
      tips: ['关注首次加载时间', '实时场景优先 YOLO Nano'],
    },
  },
  {
    test: (k) => /ppe|hard[-_]?hat|hardhat/i.test(k),
    guide: EXACT['ppe-detection'],
  },
  {
    test: (k) => /fire|smoke|火焰|烟火/i.test(k),
    guide: EXACT['fire-smoke-detection'],
  },
  {
    test: (k) => /face/i.test(k) && !/football/i.test(k),
    guide: {
      summary: '人脸/人体专用检测权重：侧重人脸或人框，适合门禁预检、客流与人脸后续链路前置。',
      scenarios: ['门禁/闸机前置检测', '人群中的人脸定位', '配合人脸识别页做 1:N'],
      effects: ['标出人脸或人体框', '为识别/追踪提供候选区域'],
      tips: ['纯身份核对请到「人脸识别」页', '侧脸/遮挡时建议降低置信度试跑'],
    },
  },
  {
    test: (k) => /yolo26n/i.test(k),
    guide: EXACT.yolo26n,
  },
  {
    test: (k) => /yolo26s/i.test(k),
    guide: EXACT.yolo26s,
  },
  {
    test: (k) => /yolo26|yolov8|yolov10|yolov11|yolo11|ultralytics/i.test(k),
    guide: {
      summary: 'YOLO 系列目标检测：业界常用实时检测家族，平台通过 Ultralytics 引擎跑推理与叠加。',
      scenarios: ['通用目标检测', '视频与摄像头实时预览', '告警规则联调'],
      effects: ['多类别检测框', '可统计类别数量并导出/告警'],
      tips: ['n/s 偏速度，m/l/x 偏精度', '专用场景优先选对应微调权重而非通用 COCO'],
    },
  },
  {
    test: (k) => /detr/i.test(k),
    guide: EXACT['detr-resnet-50'],
  },
  {
    test: (k) => /vit|nsfw/i.test(k),
    guide: EXACT['vit-base'],
  },
  {
    test: (k) => /mobilenet/i.test(k),
    guide: EXACT['mobilenet-v2'],
  },
  {
    test: (k) => /got[-_]?ocr|ocr/i.test(k),
    guide: EXACT['stepfun-ai-GOT-OCR2_0'],
  },
  {
    test: (k) => /cls|classif/i.test(k),
    guide: {
      summary: '图像分类模型：输出整图最可能的类别，而不是检测框。',
      scenarios: ['物品归类', '内容审核粗分', '实时展台分类'],
      effects: ['Top-K 类别与置信度', '可对比不同精度后端'],
      tips: ['分类≠检测：不会标出物体位置', '实时页优先轻量 DNN'],
    },
  },
]

const CATEGORY = {
  '安全帽检测': EXACT['ppe-detection'],
  '烟火检测': EXACT['fire-smoke-detection'],
  '人脸检测': FAMILY.find((f) => f.test('face')).guide,
  '通用目标检测': {
    summary: '通用目标检测类权重：通常面向 COCO 等常见类别（人、车、动物等），适合作为业务起步基线。',
    scenarios: ['园区人车盘点', '监控预览', '算法对照实验'],
    effects: ['多类检测框与置信度', '可接入告警与报告'],
    tips: ['业务专用类请换微调模型', '实时场景控制输入分辨率'],
  },
  '图像分类': {
    summary: '图像分类类模型：给整张图打标签，输出 Top-K 结果。',
    scenarios: ['场景理解', '内容标签', '实时分类演示'],
    effects: ['类别分数列表', '可显示耗时与后端'],
    tips: ['需要定位请改用检测页', 'DNN INT8 更适合摄像头'],
  },
  '文字识别': EXACT['stepfun-ai-GOT-OCR2_0'],
  '文档表格': {
    summary: '文档/表格相关检测：定位表格区域，便于后续结构识别。',
    scenarios: ['扫描件表格定位', '版面分析前置'],
    effects: ['标出表格区域框'],
    tips: ['完整结构化抽取请到「表格识别」页'],
  },
}

const TASK_FALLBACK = {
  'object-detection': {
    summary: '目标检测模型：在图像中定位物体并给出类别与置信度。',
    scenarios: ['安防巡检', '质检抓拍', '视频/摄像头实时预览'],
    effects: ['检测框叠加', '类别统计', '可联动告警中心规则'],
    tips: ['先在本页选定模型并调置信度', '专用业务优先选对应微调权重'],
  },
  'image-classification': {
    summary: '图像分类模型：判断整图所属类别。',
    scenarios: ['标签标注辅助', '内容审核', '展台实时分类'],
    effects: ['Top-K 类别与分数'],
    tips: ['不输出检测框', '实时场景选轻量模型'],
  },
  ocr: {
    summary: 'OCR 文字识别模型：从图片中提取文字内容。',
    scenarios: ['单据录入', '截图转文字', '教材/白板数字化'],
    effects: ['输出可复制文本', '可选格式化排版'],
    tips: ['模糊图先增强清晰度', 'CPU 大模型请预留等待时间'],
  },
}

function cloneGuide(g) {
  if (!g) return null
  return {
    summary: g.summary || '',
    scenarios: [...(g.scenarios || [])],
    effects: [...(g.effects || [])],
    tips: [...(g.tips || [])],
  }
}

function mergeDescription(guide, description) {
  const desc = (description || '').trim()
  if (!desc) return guide
  if (!guide.summary) {
    guide.summary = desc
    return guide
  }
  if (!guide.summary.includes(desc.slice(0, Math.min(24, desc.length)))) {
    guide.summary = `${guide.summary}\n\n模型库说明：${desc}`
  }
  return guide
}

/**
 * @param {object|null|undefined} model
 * @param {string} [page]
 */
export function resolveModelGuide(model, page = '') {
  if (!model) return null
  const key = String(model.modelKey || model.model_key || '').trim()
  const category = String(model.category || '').trim()
  const task = String(model.task || '').trim()
  const library = String(model.library || '').trim()
  const name = String(model.modelName || model.model_name || '').trim()

  let guide = null
  if (key && EXACT[key]) guide = cloneGuide(EXACT[key])
  if (!guide && key) {
    const hit = FAMILY.find((f) => f.test(key) || f.test(name))
    if (hit) guide = cloneGuide(hit.guide)
  }
  if (!guide && category && CATEGORY[category]) guide = cloneGuide(CATEGORY[category])
  if (!guide && TASK_FALLBACK[task]) guide = cloneGuide(TASK_FALLBACK[task])
  if (!guide) {
    guide = {
      summary: (model.description || '').trim() || `${name || '当前模型'}：请结合任务类型在本页试跑验证效果。`,
      scenarios: ['按本页任务进行在线试跑', '与其它模型对照效果'],
      effects: ['完成本页推理并展示结果'],
      tips: ['可在「模型管理」查看/编辑描述与权重状态'],
    }
  } else {
    mergeDescription(guide, model.description)
  }

  const pageTip = PAGE_TIPS[page]
  if (pageTip && !guide.tips.includes(pageTip)) {
    guide.tips = [pageTip, ...guide.tips]
  }

  return {
    ...guide,
    meta: {
      modelName: name || key || '未命名模型',
      modelKey: key || '—',
      category: category || '未分类',
      task: task || '—',
      library: library || '—',
      version: model.version || '—',
      status: model.status,
      sourceUrl: model.sourceUrl || model.source_url || '',
      filePath: model.filePath || model.file_path || '',
      description: (model.description || '').trim(),
    },
  }
}

export function taskLabel(task) {
  const map = {
    'object-detection': '目标检测',
    'image-classification': '图像分类',
    ocr: '文字识别',
    'instance-segmentation': '实例分割',
    'pose-estimation': '姿态估计',
  }
  return map[task] || task || '—'
}
