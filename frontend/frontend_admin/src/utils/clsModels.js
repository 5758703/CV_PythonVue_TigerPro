/** 拉取图像分类模型（分页拉全，避免 pageSize 截断漏掉 MobileNet 等）。 */
export async function loadImageClassificationModels(modelApi, {
  pageSize = 200,
  libraries = ['transformers', 'opencv-dnn', 'opencv_dnn', 'mobilenet', 'yolo-master'],
} = {}) {
  const libSet = new Set(libraries.map((x) => String(x).toLowerCase()))
  const byId = new Map()

  const ingest = (rows) => {
    for (const m of rows || []) {
      if (m?.id != null) byId.set(m.id, m)
    }
  }

  // 1) 按任务过滤（首选）
  let pageNum = 1
  let total = Infinity
  while (byId.size < total && pageNum <= 20) {
    const res = await modelApi.list({
      pageNum,
      pageSize,
      task: 'image-classification',
    })
    const rows = res.data?.rows || []
    total = Number(res.data?.total ?? rows.length)
    ingest(rows)
    if (!rows.length || rows.length < pageSize) break
    pageNum += 1
  }

  // 2) 按名称兜底：防止 task 过滤/分页异常漏掉 MobileNet
  if (![...byId.values()].some((m) => /mobilenet|opencv/i.test(`${m.library || ''}${m.modelKey || ''}${m.modelName || ''}`))) {
    const res = await modelApi.list({ pageNum: 1, pageSize: 50, modelName: 'MobileNet' })
    ingest(res.data?.rows || [])
  }

  const list = [...byId.values()].filter((m) => {
    if (!m.filePath) return false
    if (String(m.status) !== '0') return false
    const task = (m.task || '').toLowerCase()
    if (task && task !== 'image-classification') return false
    const lib = (m.library || '').toLowerCase()
    return !libSet.size || libSet.has(lib) || /opencv|mobilenet|dnn|yolo-master/i.test(lib)
  })

  // OpenCV DNN / MobileNet 排前面，便于实时分类默认选中
  list.sort((a, b) => {
    const rank = (m) => (/opencv|mobilenet|dnn/i.test(m.library || '') ? 0 : 1)
    return rank(a) - rank(b) || Number(a.id) - Number(b.id)
  })

  return list
}

export function pickPreferredClsModel(models, currentId) {
  if (currentId && models.some((m) => m.id === currentId)) return currentId
  const dnn = models.find((m) => /opencv|mobilenet|dnn/i.test(m.library || ''))
  return dnn?.id || models[0]?.id || null
}
