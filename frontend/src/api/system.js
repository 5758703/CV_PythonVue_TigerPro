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
