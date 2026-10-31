import { defineStore } from 'pinia'

import { getInfo, getRouters, getContexts } from '../api/auth'
import { getContextOrgId, setContextOrgId, retainValidContext, matchesPermission } from '../utils/organizationContext'
import { clearStoredToken, getStoredToken, setStoredToken } from '../utils/authStorage'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: getStoredToken() || '',
    userInfo: null,
    roles: [],
    perms: [],
    routers: [],
    contexts: [], contextOrgId: getContextOrgId(), contextRevision: 0
  }),
  getters: {
    isAdmin: (state) => state.roles.includes('admin'),
    nickname: (state) => state.userInfo?.nickname || state.userInfo?.username || ''
  },
  actions: {
    setToken(token) {
      this.contextOrgId = null
      setContextOrgId(null)
      this.token = token
      setStoredToken(token)
    },
    // 拉取身份 + 权限 + 菜单树
    async loadInfo() {
      const available = await getContexts()
      this.contexts = available.data.contexts || []
      this.contextOrgId = retainValidContext(this.contextOrgId, this.contexts)
      setContextOrgId(this.contextOrgId)
      const info = await getInfo()
      this.userInfo = info.data.user
      this.roles = info.data.roles || []
      this.perms = info.data.permissions || []
      this.contextOrgId = info.data.contextOrgId || null
      setContextOrgId(this.contextOrgId)
      const routers = await getRouters()
      this.routers = routers.data || []
      return info.data
    },
    hasPerm(perm) {
      return matchesPermission(this.perms, perm)
    },
    async switchContext(orgId) {
      this.contextOrgId = orgId
      setContextOrgId(orgId)
      this.perms = []
      this.routers = []
      try {
        await this.loadInfo()
      } finally {
        this.contextRevision += 1
      }
    },
    logout() {
      this.token = ''
      this.userInfo = null
      this.roles = []
      this.perms = []
      this.routers = []
      this.contexts = []
      this.contextOrgId = null
      setContextOrgId(null)
      clearStoredToken()
    }
  }
})
