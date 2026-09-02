const ROLE_LABELS = {
  personDetection: '人员检测',
  vehicleDetection: '车辆检测',
  personReid: '人员 ReID',
  personReidStrong: '人员 ReID（主）',
  personReidFallback: '人员 ReID（回退）',
  vehicleReid: '车辆 ReID',
  plateDetection: '车牌检测',
  plateOcr: '车牌 OCR',
  localTracker: '本地跟踪器',
}

const valueOr = (primary, fallback) => primary == null ? fallback : primary

export function runtimeTone(status = {}) {
  if (status.ready === false || status.runtimeState === 'failed') return 'danger'
  if (status.degradedReason || status.degraded === true || status.runtimeState === 'degraded') return 'warning'
  if (status.ready === true) return 'success'
  return 'info'
}

export function runtimeLabel(status = {}) {
  if (status.ready === false || status.runtimeState === 'failed') return '失败'
  if (status.degradedReason || status.degraded === true || status.runtimeState === 'degraded') return '降级'
  if (status.ready === true) return '就绪'
  return '等待探测'
}

export function runtimeRisk(status = {}) {
  if (status.degradedReason) return String(status.degradedReason)
  if (status.ready === false) return '后端不可用'
  if (status.degraded === true || status.runtimeState === 'degraded') return '已降级'
  return ''
}

function inputSizeLabel(value) {
  if (Array.isArray(value)) return value.join('×')
  return value == null || value === '' ? '—' : String(value).replace('x', '×')
}

export function runtimeModelRows(runtime = {}) {
  const models = runtime.models || {}
  const preferredRoles = [
    'personDetection', 'vehicleDetection', 'personReid', 'vehicleReid',
    'plateDetection', 'plateOcr', 'localTracker',
  ]
  const roles = preferredRoles.filter((role) => models[role])
  if (!models.personReid) {
    for (const role of ['personReidStrong', 'personReidFallback']) {
      if (models[role]) roles.push(role)
    }
  }
  const makeRow = (role, status, cameraId = null) => {
    return {
      role,
      roleLabel: ROLE_LABELS[role] || role,
      cameraId,
      selectedModelKey: status.selectedModelKey || status.configuredModelKey || '—',
      modelVersion: status.modelVersion || '—',
      ready: status.ready,
      degraded: status.degraded,
      degradedReason: status.degradedReason || null,
      backend: status.backend || '—',
      provider: status.provider || '—',
      inputSize: inputSizeLabel(status.inputSize),
      embeddingDim: status.embeddingDim ?? null,
      tone: runtimeTone(status),
      statusLabel: runtimeLabel(status),
    }
  }
  return roles.flatMap((role) => {
    const status = models[role] || {}
    const byCamera = status.byCamera || {}
    if (status.mixed === true && Object.keys(byCamera).length) {
      return Object.entries(byCamera)
        .sort(([left], [right]) => Number(left) - Number(right))
        .map(([cameraId, cameraStatus]) => makeRow(role, cameraStatus || {}, cameraId))
    }
    return [makeRow(role, status)]
  })
}

export function associationScoreParts(row = {}) {
  const scores = row.scores || {}
  const evidence = row.evidence || {}
  return {
    appearance: valueOr(row.appearanceScore, valueOr(scores.reid, evidence.reid)),
    topology: valueOr(row.topologyScore, valueOr(scores.topology, evidence.topology)),
    time: valueOr(row.timeScore, valueOr(scores.time, evidence.time)),
    margin: valueOr(row.margin, evidence.matchMargin),
    final: valueOr(row.finalScore, valueOr(scores.final, evidence.final)),
  }
}

export function candidateScoreParts(row = {}) {
  const evidence = row.evidence || {}
  const best = valueOr(row.bestScore, valueOr(row.finalScore, valueOr(evidence.bestScore, evidence.final)))
  return {
    best,
    second: valueOr(row.secondBestScore, evidence.secondBestScore),
    margin: valueOr(row.matchMargin, evidence.matchMargin),
    appearance: valueOr(row.appearanceScore, valueOr(row.reidScore, evidence.reid)),
    topology: valueOr(row.topologyScore, evidence.topology),
    time: valueOr(row.timeScore, evidence.time),
    final: valueOr(row.finalScore, evidence.final),
  }
}

export function cameraObservationSummary(row = {}) {
  return Object.entries(row.cameraObservations || {})
    .sort(([left], [right]) => Number(left) - Number(right))
    .map(([cameraId, state = {}]) => `#${cameraId} ${state.active ? '在线' : '丢失'}`)
    .join(' · ')
}

export function normalizeTopologyDraft(draft = {}) {
  const fromCameraId = Number(draft.fromCameraId)
  const toCameraId = Number(draft.toCameraId)
  const minTransitSec = Number(draft.minTransitSec)
  const maxTransitSec = Number(draft.maxTransitSec)
  const weight = draft.weight == null ? 1 : Number(draft.weight)
  const edgeType = String(draft.edgeType || 'non_overlap').trim().toLowerCase()
  if (!Number.isInteger(fromCameraId) || !Number.isInteger(toCameraId) || fromCameraId <= 0 || toCameraId <= 0) {
    return { ok: false, error: '请选择起点和终点相机' }
  }
  if (fromCameraId === toCameraId) return { ok: false, error: '起点和终点相机不能相同' }
  if (!Number.isFinite(minTransitSec) || !Number.isFinite(maxTransitSec) || minTransitSec < 0 || maxTransitSec <= 0) {
    return { ok: false, error: '通行时间必须为有效正数' }
  }
  if (minTransitSec > maxTransitSec) return { ok: false, error: '最短时间不能大于最长时间' }
  if (!['overlap', 'non_overlap'].includes(edgeType)) return { ok: false, error: '请选择有效的边类型' }
  if (!Number.isFinite(weight) || weight < 0) return { ok: false, error: '权重不能小于 0' }
  return {
    ok: true,
    value: { fromCameraId, toCameraId, minTransitSec, maxTransitSec, edgeType, weight },
  }
}

export function stopSessionOutcome(data = {}) {
  const status = String(data.status || 'failed')
  return {
    status,
    completed: status === 'stopped',
    retryable: Boolean(data.retryable),
  }
}

export function topologyPolicyText(policy = {}) {
  if (
    !policy
    || typeof policy !== 'object'
    || !Object.prototype.hasOwnProperty.call(policy, 'directed')
    || !Object.prototype.hasOwnProperty.call(policy, 'missingEdgePolicy')
    || !Array.isArray(policy.edges)
  ) return '等待策略快照'
  const direction = policy.directed ? '有向' : '无向'
  const authority = policy.authoritative ? '权威策略' : '默认时间窗'
  const missing = policy.missingEdgePolicy === 'reject' ? '缺边拒绝' : '缺边按时间窗'
  return `${direction}${authority} · ${missing} · ${(policy.edges || []).length} 条边`
}

export function runtimeBudgetRows(budgets = {}) {
  const labels = { personReid: '人员 ReID', vehicleReid: '车辆 ReID', plateOcr: '车牌 OCR' }
  return Object.entries(budgets).map(([role, value = {}]) => ({
    role,
    label: labels[role] || role,
    limitPerFrame: value.limitPerFrame ?? 0,
    considered: value.considered ?? 0,
    eligible: value.eligible ?? 0,
    queued: value.queued ?? 0,
    consumed: value.consumed ?? 0,
    budgetSkipped: value.budgetSkipped ?? 0,
    samplerSkipped: value.samplerSkipped ?? 0,
  }))
}

export function runtimeRiskSummary(runtime = {}) {
  const risks = runtimeModelRows(runtime)
    .filter((row) => row.tone === 'danger' || row.tone === 'warning')
    .map((row) => `${row.roleLabel}：${runtimeRisk(row)}`)
  const gallery = runtime.gallery || {}
  if (['danger', 'warning'].includes(runtimeTone(gallery))) {
    risks.push(`人员底库：${gallery.degradedReason || gallery.error || gallery.code || '后端不可用'}`)
  }
  return risks.join('；')
}

export function runtimeOverallStatus(runtime = {}) {
  const tones = runtimeModelRows(runtime).map((row) => row.tone)
  tones.push(runtimeTone(runtime.gallery || {}))
  if (tones.includes('danger')) return { tone: 'danger', label: '存在失败' }
  if (tones.includes('warning')) return { tone: 'warning', label: '存在降级' }
  if (tones.length > 1 && tones.slice(0, -1).every((tone) => tone === 'success')) {
    return { tone: 'success', label: '运行就绪' }
  }
  return { tone: 'info', label: '等待运行探测' }
}
