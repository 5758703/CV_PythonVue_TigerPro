const ROLE_LABELS = {
  personDetection: '人员检测',
  vehicleDetection: '车辆检测',
  personReid: '人员 ReID',
  personReidStrong: '人员 ReID（主）',
  personReidFallback: '人员 ReID（回退）',
  vehicleReid: '车辆 ReID',
  plateDetection: '车牌检测',
}

const valueOr = (primary, fallback) => primary == null ? fallback : primary

export function runtimeTone(status = {}) {
  if (status.degradedReason || status.degraded === true || status.ready === false) return 'danger'
  if (status.ready === true) return 'success'
  return 'info'
}

export function runtimeLabel(status = {}) {
  if (status.degradedReason || status.degraded === true) return '降级'
  if (status.ready === true) return '就绪'
  if (status.ready === false) return '不可用'
  return '等待探测'
}

export function runtimeRisk(status = {}) {
  if (status.degradedReason) return String(status.degradedReason)
  if (status.ready === false) return '后端不可用'
  return ''
}

function inputSizeLabel(value) {
  if (Array.isArray(value)) return value.join('×')
  return value == null || value === '' ? '—' : String(value).replace('x', '×')
}

export function runtimeModelRows(runtime = {}) {
  const models = runtime.models || {}
  const preferredRoles = [
    'personDetection', 'vehicleDetection', 'personReid', 'vehicleReid', 'plateDetection',
  ]
  const roles = preferredRoles.filter((role) => models[role])
  if (!models.personReid) {
    for (const role of ['personReidStrong', 'personReidFallback']) {
      if (models[role]) roles.push(role)
    }
  }
  return roles.map((role) => {
    const status = models[role] || {}
    return {
      role,
      roleLabel: ROLE_LABELS[role] || role,
      selectedModelKey: status.selectedModelKey || '—',
      modelVersion: status.modelVersion || '—',
      ready: status.ready,
      degraded: status.degraded,
      degradedReason: status.degradedReason || null,
      provider: status.provider || '—',
      inputSize: inputSizeLabel(status.inputSize),
      embeddingDim: status.embeddingDim ?? null,
      tone: runtimeTone(status),
      statusLabel: runtimeLabel(status),
    }
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

export function topologyPolicyText(policy = {}) {
  const direction = policy.directed ? '有向' : '无向'
  const authority = policy.authoritative ? '权威策略' : '默认时间窗'
  const missing = policy.missingEdgePolicy === 'reject' ? '缺边拒绝' : '缺边按时间窗'
  return `${direction}${authority} · ${missing} · ${(policy.edges || []).length} 条边`
}

export function runtimeRiskSummary(runtime = {}) {
  const risks = runtimeModelRows(runtime)
    .filter((row) => row.tone === 'danger')
    .map((row) => `${row.roleLabel}：${runtimeRisk(row)}`)
  const gallery = runtime.gallery || {}
  if (runtimeTone(gallery) === 'danger') {
    risks.push(`人员底库：${gallery.degradedReason || gallery.error || gallery.code || '后端不可用'}`)
  }
  return risks.join('；')
}
