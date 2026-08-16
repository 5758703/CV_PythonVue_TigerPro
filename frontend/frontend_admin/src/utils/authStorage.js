/** 控制台登录态：localStorage + Cookie（同主机跨端口可被门户读取） */

export const TOKEN_KEY = 'token'
export const TOKEN_COOKIE = 'tiger_ai_token'
const COOKIE_MAX_AGE = 7 * 24 * 60 * 60

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

function writeCookie(name, value, maxAge = COOKIE_MAX_AGE) {
  if (typeof document === 'undefined') return
  const encoded = encodeURIComponent(value)
  document.cookie = `${name}=${encoded}; path=/; SameSite=Lax; max-age=${maxAge}`
}

function clearCookie(name) {
  if (typeof document === 'undefined') return
  document.cookie = `${name}=; path=/; SameSite=Lax; max-age=0`
}

/** 读取 token：优先 localStorage，其次 Cookie（跨 127.0.0.1/localhost 与跨端口） */
export function getStoredToken() {
  try {
    const fromLs = localStorage.getItem(TOKEN_KEY)
    if (fromLs) return fromLs
  } catch {
    /* ignore */
  }
  return readCookie(TOKEN_COOKIE)
}

export function setStoredToken(token) {
  const value = String(token || '')
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* ignore */
  }
  if (value) writeCookie(TOKEN_COOKIE, value)
  else clearCookie(TOKEN_COOKIE)
}

export function clearStoredToken() {
  try {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem('user')
  } catch {
    /* ignore */
  }
  clearCookie(TOKEN_COOKIE)
}
