import request from './request'

// ---------------- AI 检测模型
export const modelApi = {
  list: (params) => request.get('/ai/model', { params }),
  categories: () => request.get('/ai/model/categories'),
  tasks: () => request.get('/ai/model/tasks'),
  get: (id) => request.get(`/ai/model/${id}`),
  add: (data) => request.post('/ai/model', data),
  update: (data) => request.put(`/ai/model/${data.id}`, data),
  remove: (id) => request.delete(`/ai/model/${id}`),
  batchRemove: (ids) => request.post('/ai/model/batch-delete', { ids }),
  upload: (formData) =>
    request.post('/ai/model/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0
    }),
  // 下载本地权重到浏览器（返回 Blob）
  download: (id) =>
    request.get(`/ai/model/${id}/download`, { responseType: 'blob' }),
  // 从 HuggingFace 来源拉取权重到服务器（下载耗时长，关闭超时）
  fetchWeight: (id) => request.post(`/ai/model/${id}/fetch`, null, { timeout: 0 }),
  // 在线测试：上传图片做检测
  detect: (id, formData) =>
    request.post(`/ai/model/${id}/detect`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0
    }),
  // 视频检测：启动异步任务，返回 jobId
  detectVideo: (id, formData) =>
    request.post(`/ai/model/${id}/detect-video`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0
    }),
  // 查询视频检测进度（长任务，关闭超时）
  videoProgress: (id, jobId) =>
    request.get(`/ai/model/${id}/video-progress/${jobId}`, { timeout: 0 }),
  // 目标追踪：启动异步任务，返回 jobId（进度复用 videoProgress）
  trackVideo: (id, formData) =>
    request.post(`/ai/model/${id}/track-video`, formData, {
      timeout: 0,
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  // 摄像头实时追踪单帧（draw=0，前端叠画）
  trackFrame: (id, formData) =>
    request.post(`/ai/model/${id}/track-frame`, formData, {
      timeout: 0,
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  // 姿态估计（图片，同步）
  pose: (id, formData) =>
    request.post(`/ai/model/${id}/pose`, formData, {
      timeout: 0,
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  // 姿态估计（视频，异步，进度复用 videoProgress）
  poseVideo: (id, formData) =>
    request.post(`/ai/model/${id}/pose-video`, formData, {
      timeout: 0,
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  // 实例/交互分割（图片）
  segment: (id, formData) =>
    request.post(`/ai/model/${id}/segment`, formData, {
      timeout: 0,
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  // RF-DETR-Seg 视频分割（异步）
  segmentVideo: (id, formData) =>
    request.post(`/ai/model/${id}/segment-video`, formData, {
      timeout: 0,
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  // 拉取带框输出视频（返回 Blob）
  outputVideo: (name) =>
    request.get(`/ai/model/output/${name}`, { responseType: 'blob', timeout: 0 }),
  // 文本任务分析（transformers，如 FinBERT 情感分析）
  analyzeText: (id, text) =>
    request.post(`/ai/model/${id}/analyze-text`, { text }, { timeout: 0 }),
  // 图像分类（transformers，如 ViT/ResNet）
  classifyImage: (id, formData) =>
    request.post(`/ai/model/${id}/classify-image`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0
    }),
  // 文字识别 OCR（GOT-OCR2）
  ocr: (id, formData) =>
    request.post(`/ai/model/${id}/ocr`, formData, {
      timeout: 0,
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  // PaddleOCR（RapidOCR）：检测模型 + 识别模型 + 图片
  paddleOcr: (detId, recId, formData) => {
    formData.append('detId', detId)
    formData.append('recId', recId)
    return request.post('/ai/model/ocr-paddle', formData, {
      timeout: 0,
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  // 文本生成/翻译/摘要
  generateText: (id, text, maxNewTokens) =>
    request.post(`/ai/model/${id}/generate-text`, { text, maxNewTokens }, { timeout: 0 }),
  // 零样本分类
  zeroShot: (id, text, labels) =>
    request.post(`/ai/model/${id}/zero-shot`, { text, labels }, { timeout: 0 }),
  // 完形填空
  fillMask: (id, text, topK) =>
    request.post(`/ai/model/${id}/fill-mask`, { text, topK }, { timeout: 0 }),
  // 命名实体识别 NER
  extractEntities: (id, text) =>
    request.post(`/ai/model/${id}/extract-entities`, { text }, { timeout: 0 }),
  // 抽取式问答 QA
  answerQuestion: (id, question, context) =>
    request.post(`/ai/model/${id}/answer-question`, { question, context }, { timeout: 0 }),
  // 语音识别（funasr SenseVoice）：上传音频
  transcribe: (id, formData) =>
    request.post(`/ai/model/${id}/transcribe`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0
    }),
  // 数字人合成（Linly-Talker）：上传人像+音频，返回 jobId
  talkingHead: (id, formData) =>
    request.post(`/ai/model/${id}/talking-head`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0
    }),
  // 查询数字人合成进度
  talkingProgress: (id, jobId) => request.get(`/ai/model/${id}/talking-progress/${jobId}`),
  // 文本转语音：可用音色
  ttsSpeakers: (id) => request.get(`/ai/model/${id}/tts-speakers`),
  // 文本转语音：文本 + 音色 -> wav(base64)
  tts: (id, text, speaker) =>
    request.post(`/ai/model/${id}/tts`, { text, speaker }, { timeout: 0 }),
  // 零样本音色克隆（VoxCPM）：参考音频 + 参考文本 + 目标文本 -> wav(base64)
  ttsClone: (id, formData) =>
    request.post(`/ai/model/${id}/tts-clone`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0
    }),
  // 对检测结果做 DeepSeek AI 分析，生成正式报告
  analyzeReport: (id, payload) =>
    request.post(`/ai/model/${id}/analyze-report`, payload, { timeout: 0 }),
}

// ---------------- 水位检测
export const waterLevelApi = {
  detect: (formData) =>
    request.post('/ai/water-level/detect', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0
    }),
}

// ---------------- 羽毛球视频分析
export const badmintonApi = {
  extractFrame: (formData) =>
    request.post('/ai/badminton/extract-frame', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0
    }),
  detectCourt: (formData) =>
    request.post('/ai/badminton/detect-court', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0
    }),
  analyze: (formData) =>
    request.post('/ai/badminton/analyze', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0
    }),
  progress: (jobId) => request.get(`/ai/badminton/progress/${jobId}`),
  artifactBlob: (jobId, name) =>
    request.get(`/ai/badminton/artifact/${jobId}/${name}`, { responseType: 'blob', timeout: 0 }),
}

// ---------------- 模型训练
export const trainingApi = {
  // 数据集
  listDatasets: (params) => request.get('/ai/training/datasets', { params }),
  getDataset: (id) => request.get(`/ai/training/datasets/${id}`),
  addDataset: (data) => request.post('/ai/training/datasets', data),
  updateDataset: (id, data) => request.put(`/ai/training/datasets/${id}`, data),
  removeDataset: (id) => request.delete(`/ai/training/datasets/${id}`),
  uploadDatasetFiles: (id, formData) =>
    request.post(`/ai/training/datasets/${id}/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0
    }),
  buildDataset: (id) => request.post(`/ai/training/datasets/${id}/build`, null, { timeout: 0 }),
  datasetSamples: (id) => request.get(`/ai/training/datasets/${id}/samples`),
  datasetFormats: () => request.get('/ai/training/datasets/formats'),
  extractFrames: (id, formData) =>
    request.post(`/ai/training/datasets/${id}/extract-frames`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0
    }),
  annotateSamples: (id) => request.get(`/ai/training/datasets/${id}/annotate/samples`),
  annotateImage: (id, stem) =>
    request.get(`/ai/training/datasets/${id}/annotate/image/${encodeURIComponent(stem)}`, {
      responseType: 'blob',
      timeout: 0
    }),
  annotateLabels: (id, stem) =>
    request.get(`/ai/training/datasets/${id}/annotate/labels/${encodeURIComponent(stem)}`),
  saveAnnotateLabels: (id, stem, data) =>
    request.put(`/ai/training/datasets/${id}/annotate/labels/${encodeURIComponent(stem)}`, data),
  clearAnnotateLabels: (id, stem) =>
    request.delete(`/ai/training/datasets/${id}/annotate/labels/${encodeURIComponent(stem)}`),
  analyzeQuality: (id, data) =>
    request.post(`/ai/training/datasets/${id}/quality/analyze`, data, { timeout: 0 }),
  convertTypes: () => request.get('/ai/training/datasets/convert/types'),
  convertDataset: (id, data) =>
    request.post(`/ai/training/datasets/${id}/convert`, data, { timeout: 0 }),
  // 训练任务
  listJobs: (params) => request.get('/ai/training/jobs', { params }),
  getJob: (id) => request.get(`/ai/training/jobs/${id}`),
  jobProgress: (id) => request.get(`/ai/training/jobs/${id}/progress`),
  addJob: (data) => request.post('/ai/training/jobs', data),
  startJob: (id) => request.post(`/ai/training/jobs/${id}/start`, null, { timeout: 0 }),
  cancelJob: (id) => request.post(`/ai/training/jobs/${id}/cancel`),
  removeJob: (id) => request.delete(`/ai/training/jobs/${id}`),
  validateJob: (id) => request.post(`/ai/training/jobs/${id}/validate`, null, { timeout: 0 }),
  validateProgress: (id) => request.get(`/ai/training/jobs/${id}/validate-progress`),
  jobLogs: (id, params) => request.get(`/ai/training/jobs/${id}/logs`, { params }),
  testJob: (id, formData) =>
    request.post(`/ai/training/jobs/${id}/test`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0
    }),
  exportJob: (id, data) => request.post(`/ai/training/jobs/${id}/export`, data, { timeout: 0 }),
  deployJob: (id, data) => request.post(`/ai/training/jobs/${id}/deploy`, data),
  getArtifact: (id, name) =>
    request.get(`/ai/training/jobs/${id}/artifact/${name}`, { responseType: 'blob', timeout: 0 }),
  downloadExportFile: (id, file) =>
    request.get(`/ai/training/jobs/${id}/download-export`, { params: { file }, responseType: 'blob', timeout: 0 }),
}
