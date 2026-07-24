import request from './request'

// ---------------- 用户
export const userApi = {
  list: (params) => request.get('/system/user', { params }),
  get: (id) => request.get(`/system/user/${id}`),
  add: (data) => request.post('/system/user', data),
  update: (data) => request.put(`/system/user/${data.id}`, data),
  remove: (id) => request.delete(`/system/user/${id}`)
}

// ---------------- 角色
export const roleApi = {
  list: (params) => request.get('/system/role', { params }),
  get: (id) => request.get(`/system/role/${id}`),
  add: (data) => request.post('/system/role', data),
  update: (data) => request.put(`/system/role/${data.id}`, data),
  remove: (id) => request.delete(`/system/role/${id}`)
}

// ---------------- 部门（树）
export const deptApi = {
  tree: (params) => request.get('/system/dept', { params }),
  get: (id) => request.get(`/system/dept/${id}`),
  add: (data) => request.post('/system/dept', data),
  update: (data) => request.put(`/system/dept/${data.id}`, data),
  remove: (id) => request.delete(`/system/dept/${id}`)
}

// ---------------- 岗位
export const jobApi = {
  list: (params) => request.get('/system/job', { params }),
  get: (id) => request.get(`/system/job/${id}`),
  add: (data) => request.post('/system/job', data),
  update: (data) => request.put(`/system/job/${data.id}`, data),
  remove: (id) => request.delete(`/system/job/${id}`)
}

// ---------------- 菜单（树）
export const menuApi = {
  tree: (params) => request.get('/system/menu', { params }),
  get: (id) => request.get(`/system/menu/${id}`),
  add: (data) => request.post('/system/menu', data),
  update: (data) => request.put(`/system/menu/${data.id}`, data),
  remove: (id) => request.delete(`/system/menu/${id}`)
}

// ---------------- 开放平台
export const openAppApi = {
  scopes: () => request.get('/system/open-app/scopes'),
  list: (params) => request.get('/system/open-app', { params }),
  get: (id) => request.get(`/system/open-app/${id}`),
  add: (data) => request.post('/system/open-app', data),
  update: (data) => request.put(`/system/open-app/${data.id}`, data),
  remove: (id) => request.delete(`/system/open-app/${id}`),
  createFromDomain: (data) => request.post('/system/open-app/from-domain', data),
  ensureDomains: () => request.post('/system/open-app/ensure-domains'),
  createKey: (id, data) => request.post(`/system/open-app/${id}/keys`, data || {}),
  updateKey: (id, kid, data) => request.put(`/system/open-app/${id}/keys/${kid}`, data),
  removeKey: (id, kid) => request.delete(`/system/open-app/${id}/keys/${kid}`),
  logs: (id, params) => request.get(`/system/open-app/${id}/logs`, { params }),
  usage: (id, params) => request.get(`/system/open-app/${id}/usage`, { params }),
  testWebhook: (id) => request.post(`/system/open-app/${id}/webhook/test`)
}
