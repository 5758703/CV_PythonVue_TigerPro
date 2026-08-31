import request from './request'
import { useUserStore } from '../store/user'

function streamOrigin() {
  const fromEnv = (import.meta.env.VITE_API_ORIGIN || '').replace(/\/$/, '')
  if (fromEnv) return fromEnv
  // MJPEG 长连接开发态直连后端，避免经 Vite 代理断流
  if (import.meta.env.DEV) return 'http://127.0.0.1:5001'
  return ''
}

export const mtmcApi = {
  listTopology: () => request.get('/ai/mtmc/topology'),
  addTopology: (data) => request.post('/ai/mtmc/topology', data),
  removeTopology: (id) => request.delete(`/ai/mtmc/topology/${id}`),
  listSessions: () => request.get('/ai/mtmc/sessions'),
  getSession: (id) => request.get(`/ai/mtmc/sessions/${id}`),
  /** 探活：会话不存在或未运行时 active=false，不弹错误 toast */
  sessionAlive: (id) => request.get(`/ai/mtmc/sessions/${id}/alive`),
  startSession: (data) => request.post('/ai/mtmc/sessions/start', data),
  /** 上传本地视频/图片启动（multipart，至少 1 个文件） */
  startSessionVideos: (formData) =>
    request.post('/ai/mtmc/sessions/start-videos', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,
    }),
  /** 服务器已有视频路径（免上传，适合大文件 / docs/test_data） */
  startSessionVideoPaths: (data) =>
    request.post('/ai/mtmc/sessions/start-video-paths', data, { timeout: 120000 }),
  /** 混合源：file/path/image/rtsp/device */
  startSessionSources: (data) =>
    request.post('/ai/mtmc/sessions/start-sources', data, { timeout: 120000 }),
  stopSession: (id) => request.post(`/ai/mtmc/sessions/${id}/stop`),
  listEvents: (params) => request.get('/ai/mtmc/events', { params }),
  listPasses: (params) => request.get('/ai/mtmc/passes', { params }),
  listTracklets: (params) => request.get('/ai/mtmc/tracklets', { params }),
  listAssociations: (params) => request.get('/ai/mtmc/associations', { params }),
  listGlobalPersons: (params) => request.get('/ai/mtmc/globals/person', { params }),
  listGlobalVehicles: (params) => request.get('/ai/mtmc/globals/vehicle', { params }),
  listCandidates: (sid, params) => request.get(`/ai/mtmc/sessions/${sid}/candidates`, { params }),
  listCandidatesDb: (params) => request.get('/ai/mtmc/candidates', { params }),
  promoteCandidate: (data) => request.post('/ai/mtmc/candidates/promote', data),
  rejectCandidate: (data) => request.post('/ai/mtmc/candidates/reject', data),
  listCrossEvents: (params) => request.get('/ai/mtmc/cross-events', { params }),
  submitSearchJob: (data) => {
    const isForm = typeof FormData !== 'undefined' && data instanceof FormData
    return request.post('/ai/mtmc/search/jobs', data, isForm ? { timeout: 120000 } : undefined)
  },
  listSearchJobs: (params) => request.get('/ai/mtmc/search/jobs', { params }),
  getSearchJob: (jobId) => request.get(`/ai/mtmc/search/jobs/${jobId}`),
  trajectory: (gid) => request.get(`/ai/mtmc/trajectory/${gid}`),
  overlayUrl: (sessionId, cameraId, bust = '') => {
    const token = useUserStore().token
    const q = bust ? `&_=${encodeURIComponent(bust)}` : ''
    const origin = streamOrigin()
    return `${origin}/api/ai/mtmc/overlay/${sessionId}/${cameraId}/stream?jwt=${encodeURIComponent(token)}${q}`
  },
  rawUrl: (sessionId, cameraId, bust = '') => {
    const token = useUserStore().token
    const q = bust ? `&_=${encodeURIComponent(bust)}` : ''
    const origin = streamOrigin()
    return `${origin}/api/ai/mtmc/raw/${sessionId}/${cameraId}/stream?jwt=${encodeURIComponent(token)}${q}`
  },
}
