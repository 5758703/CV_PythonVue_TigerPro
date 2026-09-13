import request from './request'

export const scenarioApi = {
  list: (params) => request.get('/ai/model-scenarios', { params }),
  get: (modelKey) => request.get(`/ai/model-scenarios/${modelKey}`),
  infer: (modelKey, formData) =>
    request.post(`/ai/model-scenarios/${modelKey}/infer`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0,
    }),
}
