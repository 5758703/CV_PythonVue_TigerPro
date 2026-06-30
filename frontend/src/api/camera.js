import request from './request'
import { useUserStore } from '../store/user'

export const cameraApi = {
  list: (params) => request.get('/camera', { params }),
  get: (id) => request.get(`/camera/${id}`),
  add: (data) => request.post('/camera', data),
  update: (data) => request.put(`/camera/${data.id}`, data),
  remove: (id) => request.delete(`/camera/${id}`),
  batchRemove: (ids) => request.post('/camera/batch-delete', { ids }),
  upload: (formData) =>
    request.post('/camera/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  // MJPEG 预览：<img> 不能带 header，token 走 query
  streamUrl: (id) => {
    const token = useUserStore().token
    return `/api/camera/${id}/stream?jwt=${encodeURIComponent(token)}`
  },
}
