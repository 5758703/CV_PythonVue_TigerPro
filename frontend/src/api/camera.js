import request from './request'
import { useUserStore } from '../store/user'

/** MJPEG 长连接开发态直连后端，避免经 Vite 代理断流时刷 ECONNRESET */
function streamOrigin() {
  const fromEnv = (import.meta.env.VITE_API_ORIGIN || '').replace(/\/$/, '')
  if (fromEnv) return fromEnv
  if (import.meta.env.DEV) return 'http://127.0.0.1:5001'
  return ''
}

export const cameraApi = {
  list: (params) => request.get('/camera', { params }),
  get: (id) => request.get(`/camera/${id}`),
  add: (data) => request.post('/camera', data),
  update: (data) => request.put(`/camera/${data.id}`, data),
  remove: (id) => request.delete(`/camera/${id}`),
  batchRemove: (ids) => request.post('/camera/batch-delete', { ids }),
  devices: () => request.get('/camera/devices'),
  upload: (formData) =>
    request.post('/camera/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  // MJPEG 预览：<img> 不能带 header，token 走 query
  streamUrl: (id, bust = '', check = false) => {
    const token = useUserStore().token
    const q = bust ? `&_=${encodeURIComponent(bust)}` : ''
    const chk = check ? '&check=1' : ''
    return `${streamOrigin()}/api/camera/${id}/stream?jwt=${encodeURIComponent(token)}${q}${chk}`
  },
}
