/**
 * 项目门户地址（frontend_home）。
 * 支持绝对 URL 或同域相对路径（如 Docker 网关下的 "/"）。
 */
const trimSlash = (url = '') => String(url || '').replace(/\/+$/, '')

export function resolvePortalUrl() {
  const fallback = 'http://localhost:5174'
  const raw = (import.meta.env.VITE_PORTAL_URL || fallback).trim() || fallback
  try {
    if (typeof window !== 'undefined') {
      const u = new URL(raw, window.location.origin)
      const host = window.location.hostname
      if ((host === 'localhost' || host === '127.0.0.1') && u.hostname === '127.0.0.1') {
        u.hostname = 'localhost'
      }
      // 相对 "/" → 站点根；其它路径保留 pathname
      if (raw.startsWith('/') && !raw.startsWith('//')) {
        return raw === '/' ? `${u.origin}/` : `${u.origin}${trimSlash(u.pathname)}/`
      }
      return trimSlash(u.origin)
    }
    if (raw.startsWith('/')) return raw
    const u = new URL(raw)
    if (u.hostname === '127.0.0.1') u.hostname = 'localhost'
    return trimSlash(u.origin)
  } catch {
    return fallback
  }
}
