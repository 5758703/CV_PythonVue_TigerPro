import request from './request'

export const radarApi = {
  status: () => request.get('/ai/radar/status'),
  infer: (formData) =>
    request.post('/ai/radar/infer', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0,
    }),
  report: (data) => request.post('/ai/radar/report', data, { timeout: 0 }),
}
