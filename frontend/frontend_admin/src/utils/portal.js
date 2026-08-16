/**
 * 项目门户地址（frontend_home）。
 * 本机统一 localhost，避免与 127.0.0.1 混用导致体验不一致。
 */
const trimSlash = (url = '') => String(url || '').replace(/\/+$/, '')

export function resolvePortalUrl() {
  const fallback = 'http://localhost:5174'
  try {
    const raw = import.meta.env.VITE_PORTAL_URL || fallback
    const base = new URL(raw, typeof window !== 'undefined' ? window.location.origin : fallback)
    if (typeof window !== 'undefined') {
      const host = window.location.hostname
      if (host === 'localhost' || host === '127.0.0.1') {
        base.hostname = 'localhost'
      }
    } else if (base.hostname === '127.0.0.1') {
      base.hostname = 'localhost'
    }
    return trimSlash(base.origin)
  } catch {
    return fallback
  }
}
