import request from './request'
import { useUserStore } from '../store/user'

function streamOrigin() {
  const fromEnv = (import.meta.env.VITE_API_ORIGIN || '').replace(/\/$/, '')
  if (fromEnv) return fromEnv
  if (import.meta.env.DEV) return 'http://127.0.0.1:5001'
  return ''
}

export const pipelineApi = {
  nodeTypes: () => request.get('/ai/pipeline/node-types'),
  templates: () => request.get('/ai/pipeline/templates'),
  getTemplate: (tid, params) => request.get(`/ai/pipeline/templates/${tid}`, { params }),
  exampleDag: (params) => request.get('/ai/pipeline/example-dag', { params }),
  validate: (data) => request.post('/ai/pipeline/validate', data),
  list: (params) => request.get('/ai/pipeline', { params }),
  get: (id) => request.get(`/ai/pipeline/${id}`),
  create: (data) => request.post('/ai/pipeline', data),
  update: (id, data) => request.put(`/ai/pipeline/${id}`, data),
  remove: (id) => request.delete(`/ai/pipeline/${id}`),
  start: (id) => request.post(`/ai/pipeline/${id}/start`),
  stopRun: (runKey) => request.post(`/ai/pipeline/runs/${runKey}/stop`),
  listRuns: (params) => request.get('/ai/pipeline/runs', { params }),
  getRun: (runKey) => request.get(`/ai/pipeline/runs/${runKey}`),
  metrics: () => request.get('/ai/pipeline/metrics'),
  alive: (runKey) => request.get(`/ai/pipeline/runs/${runKey}/alive`),
  aliveByCamera: (cid) => request.get(`/ai/pipeline/by-camera/${cid}/alive`),
  overlayUrl: (runKey, bust = '') => {
    const token = useUserStore().token
    const q = bust ? `&_=${encodeURIComponent(String(bust))}` : ''
    return `${streamOrigin()}/api/ai/pipeline/runs/${encodeURIComponent(runKey)}/overlay/stream?jwt=${encodeURIComponent(token)}${q}`
  },
  overlayByCameraUrl: (cameraId, bust = '') => {
    const token = useUserStore().token
    const q = bust ? `&_=${encodeURIComponent(String(bust))}` : ''
    return `${streamOrigin()}/api/ai/pipeline/by-camera/${cameraId}/overlay/stream?jwt=${encodeURIComponent(token)}${q}`
  },
}
