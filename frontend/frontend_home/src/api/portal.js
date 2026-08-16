/**
 * 门户公开接口（无需登录）。
 */

async function getJson(url) {
  const res = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

/** 后端存活 */
export async function fetchHealth() {
  const data = await getJson('/api/health')
  return data?.code === 0
}

/** OpenAPI 公开健康（含 uptime 等） */
export async function fetchOpenApiHealth() {
  const data = await getJson('/openapi/v1/health')
  return data?.data || data
}

/** 门户聚合统计 */
export async function fetchPortalSummary() {
  const data = await getJson('/api/portal/summary')
  if (data?.code !== 0) throw new Error(data?.message || 'summary failed')
  return data.data
}
