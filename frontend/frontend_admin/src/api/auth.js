import request from './request'

export function login(data) {
  return request.post('/auth/login', data)
}

export function register(data) {
  return request.post('/auth/register', data)
}

// 当前用户身份：基本信息 + 角色标识 + 权限标识
export function getInfo() {
  return request.get('/auth/info')
}

// 侧边栏可见菜单树
export function getRouters() {
  return request.get('/auth/routers')
}

export function logout() {
  return request.post('/auth/logout')
}
