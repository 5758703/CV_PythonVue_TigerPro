import request from './request'
import { useUserStore } from '../store/user'

function streamOrigin() {
  const fromEnv = (import.meta.env.VITE_API_ORIGIN || '').replace(/\/$/, '')
  if (fromEnv) return fromEnv
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
  stopSession: (id) => request.post(`/ai/mtmc/sessions/${id}/stop`),
  listEvents: (params) => request.get('/ai/mtmc/events', { params }),
  listPasses: (params) => request.get('/ai/mtmc/passes', { params }),
  trajectory: (gid) => request.get(`/ai/mtmc/trajectory/${gid}`),
  overlayUrl: (sessionId, cameraId, bust = '') => {
    const token = useUserStore().token
    const q = bust ? `&_=${encodeURIComponent(bust)}` : ''
    const origin = streamOrigin()
    return `${origin}/api/ai/mtmc/overlay/${sessionId}/${cameraId}/stream?jwt=${encodeURIComponent(token)}${q}`
  },
}
