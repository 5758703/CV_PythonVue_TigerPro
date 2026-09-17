import request from './request'
import { useUserStore } from '../store/user'

function apiOrigin() {
  const configured = (import.meta.env.VITE_API_ORIGIN || '').replace(/\/$/, '')
  if (configured) return configured
  if (import.meta.env.DEV) return 'http://127.0.0.1:5001'
  return ''
}

export const squatApi = {
  startVideo: (formData) => request.post('/ai/squat/video', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }, timeout: 0,
  }),
  videoProgress: (jobId) => request.get(`/ai/squat/video-progress/${jobId}`),
  createSession: (data) => request.post('/ai/squat/sessions', data),
  submitFrame: (sessionId, formData) => request.post(
    `/ai/squat/sessions/${sessionId}/frames`, formData,
    { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 15000 },
  ),
  session: (sessionId) => request.get(`/ai/squat/sessions/${sessionId}`),
  stopSession: (sessionId) => request.delete(`/ai/squat/sessions/${sessionId}`),
  streamUrl: (sessionId) => {
    const token = useUserStore().token
    return `${apiOrigin()}/api/ai/squat/sessions/${sessionId}/stream?jwt=${encodeURIComponent(token)}`
  },
  outputUrl: (name) => {
    const token = useUserStore().token
    return `${apiOrigin()}/api/ai/squat/output/${encodeURIComponent(name)}?jwt=${encodeURIComponent(token)}`
  },
}
