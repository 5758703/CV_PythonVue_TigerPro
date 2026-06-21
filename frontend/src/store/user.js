import { defineStore } from 'pinia'

import { getInfo, getRouters } from '../api/auth'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('token') || '',
    userInfo: null,
    roles: [],
    perms: [],
    routers: []
  }),
  getters: {
    isAdmin: (state) => state.roles.includes('admin'),
    nickname: (state) => state.userInfo?.nickname || state.userInfo?.username || ''
  },
  actions: {
    setToken(token) {
      this.token = token
      localStorage.setItem('token', token)
    },
    // 拉取身份 + 权限 + 菜单树
    async loadInfo() {
      const info = await getInfo()
      this.userInfo = info.data.user
      this.roles = info.data.roles || []
      this.perms = info.data.permissions || []
      const routers = await getRouters()
      this.routers = routers.data || []
      return info.data
    },
    hasPerm(perm) {
      if (this.perms.includes('*:*:*')) return true
      const need = Array.isArray(perm) ? perm : [perm]
      return need.some((p) => this.perms.includes(p))
    },
    logout() {
      this.token = ''
      this.userInfo = null
      this.roles = []
      this.perms = []
      this.routers = []
      localStorage.removeItem('token')
      localStorage.removeItem('user')
    }
  }
})
