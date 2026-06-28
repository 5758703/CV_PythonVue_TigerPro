import request from './request'

// ---------------- AI 检测模型
export const modelApi = {
  list: (params) => request.get('/ai/model', { params }),
  categories: () => request.get('/ai/model/categories'),
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
  // 查询视频检测进度
  videoProgress: (id, jobId) => request.get(`/ai/model/${id}/video-progress/${jobId}`),
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
  // 文本转语音（CosyVoice）：可用音色
  ttsSpeakers: (id) => request.get(`/ai/model/${id}/tts-speakers`),
  // 文本转语音（CosyVoice）：文本 + 音色 -> wav(base64)
  tts: (id, text, speaker) =>
    request.post(`/ai/model/${id}/tts`, { text, speaker }, { timeout: 0 }),
  // 零样本音色克隆（CosyVoice2）：参考音频 + 参考文本 + 目标文本 -> wav(base64)
  ttsClone: (id, formData) =>
    request.post(`/ai/model/${id}/tts-clone`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0
    }),
  // 对检测结果做 DeepSeek AI 分析，生成正式报告
  analyzeReport: (id, payload) =>
    request.post(`/ai/model/${id}/analyze-report`, payload, { timeout: 0 }),
}
