const KEY = 'tiger_work_org'
const normalize = value => {
  const id = Number(value)
  return Number.isSafeInteger(id) && id > 0 ? id : null
}

export function getContextOrgId() {
  try { return normalize(sessionStorage.getItem(KEY)) } catch { return null }
}

export function setContextOrgId(value) {
  const id = normalize(value)
  try {
    if (id) sessionStorage.setItem(KEY, String(id))
    else sessionStorage.removeItem(KEY)
  } catch { /* Session storage can be unavailable in private environments. */ }
}

export function retainValidContext(selected, contexts) {
  return contexts.some(c => c.orgId === selected) ? selected : null
}

export function matchesPermission(owned = [], requested) {
  const needs = Array.isArray(requested) ? requested : [requested]
  return needs.some(need => owned.some(p => p === '*:*:*' || p === need || (
    typeof need === 'string' && p.split(':').length === need.split(':').length &&
    p.split(':').every((v, i) => v === '*' || v === need.split(':')[i])
  )))
}
