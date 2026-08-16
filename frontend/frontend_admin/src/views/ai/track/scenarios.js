/**
 * 目标追踪场景注册表。
 * 新增场景：在此追加一项，并在 track/index.vue 映射对应 Panel。
 */
export const TRACK_SCENARIOS = [
  {
    key: 'general',
    label: '通用追踪',
    desc: '人/车等目标 ByteTrack + 区域/线进出统计',
    perm: null, // 跟随目标追踪菜单 ai:track:list
  },
  {
    key: 'vehicle',
    label: '车辆追踪',
    desc: '车牌 OCR、测速、拥堵、运动轨迹与过车记录',
    perm: 'ai:vehicle:list',
  },
  {
    key: 'absence',
    label: '人员离岗检测',
    desc: 'ByteTrack 检人 + InsightFace/FAISS 识人，连续时间判定离岗',
    perm: 'ai:absence:list',
  },
]

export const DEFAULT_SCENARIO = 'general'

export function resolveScenario(key) {
  const hit = TRACK_SCENARIOS.find((s) => s.key === key)
  return hit ? hit.key : DEFAULT_SCENARIO
}
