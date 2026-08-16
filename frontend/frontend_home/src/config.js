/**
 * 门户运行时配置与控制台跳转。
 * 本机统一使用 localhost（避免 127.0.0.1 与 localhost 不同源导致登录态丢失）。
 */

export const TOKEN_COOKIE = 'tiger_ai_token'
export const TOKEN_KEY = 'token'

const trimSlash = (url = '') => String(url || '').replace(/\/+$/, '')

function configuredAdminUrl() {
  return import.meta.env.VITE_ADMIN_URL || 'http://localhost:5173'
}

/**
 * 解析控制台根地址：本机访问时强制 hostname=localhost，保留配置中的端口。
 */
export function resolveAdminBase() {
  const fallback = 'http://localhost:5173'
  try {
    const raw = configuredAdminUrl()
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
    return trimSlash(fallback)
  }
}

/** 动态读取（本机打开时始终指向 localhost:端口） */
export function getAdminUrl() {
  return resolveAdminBase()
}

export const ADMIN_URL = resolveAdminBase()

export const GITHUB_URL =
  import.meta.env.VITE_GITHUB_URL || 'https://github.com/5758703/CV_PythonVue_TigerPro'
export const OPENAPI_DOCS_PATH = import.meta.env.VITE_OPENAPI_DOCS_PATH || '/openapi/v1/docs'

function readCookie(name) {
  if (typeof document === 'undefined') return ''
  const prefix = `${name}=`
  const hit = document.cookie.split(';').map((c) => c.trim()).find((c) => c.startsWith(prefix))
  if (!hit) return ''
  try {
    return decodeURIComponent(hit.slice(prefix.length))
  } catch {
    return hit.slice(prefix.length)
  }
}

/** 是否已在控制台登录（Cookie 跨端口可读；同源时也可读 localStorage） */
export function isConsoleLoggedIn() {
  if (typeof window === 'undefined') return false
  const fromCookie = readCookie(TOKEN_COOKIE)
  if (fromCookie) return true
  try {
    if (localStorage.getItem(TOKEN_KEY)) return true
  } catch {
    /* ignore */
  }
  return false
}

/** 拼接站内路径 + query */
export function joinPathQuery(path = '/index', query = {}) {
  let raw = String(path || '/index').trim()
  if (!raw.startsWith('/')) raw = `/${raw}`
  const qIndex = raw.indexOf('?')
  const pathname = qIndex >= 0 ? raw.slice(0, qIndex) : raw
  const params = new URLSearchParams(qIndex >= 0 ? raw.slice(qIndex + 1) : '')
  Object.entries(query || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    params.set(key, String(value))
  })
  const qs = params.toString()
  return qs ? `${pathname}?${qs}` : pathname
}

/** 控制台绝对地址 */
export function adminHref(path = '/index', query = {}) {
  const base = resolveAdminBase()
  const target = joinPathQuery(path, query)
  const url = new URL(target, `${base}/`)
  return url.toString()
}

/**
 * 按登录态生成入口：
 * - 已登录 → 直达目标页
 * - 未登录 → /login?redirect=目标路径
 */
export function consoleEntryHref(path = '/index', query = {}) {
  const redirect = joinPathQuery(path, query)
  if (isConsoleLoggedIn()) {
    return adminHref(redirect)
  }
  return adminHref('/login', { redirect })
}

/** @deprecated 使用 consoleEntryHref */
export function adminLoginHref(redirectPath = '/index') {
  return consoleEntryHref(redirectPath)
}

export function openApiDocsHref() {
  return OPENAPI_DOCS_PATH
}

/** 点击时再判定一次登录态后跳转（避免 href 缓存过期） */
export function goConsole(path = '/index', query = {}) {
  const href = consoleEntryHref(path, query)
  window.location.assign(href)
}

export function scrollToId(id) {
  const el = typeof document !== 'undefined' ? document.getElementById(id) : null
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
