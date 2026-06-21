import { ref, computed } from 'vue'

/**
 * 单次推理任务的估算式进度 + 预计剩余时间。
 * 单次任务无逐帧进度，按「该模型上次耗时」估算；首次无历史则平滑爬升到 ~90%。
 *
 * @param {import('vue').Ref<number>} modelIdRef 当前模型 id 的 ref
 */
export function useInferProgress(modelIdRef) {
  const running = ref(false)
  const elapsedMs = ref(0)
  const estByModel = {}
  let startTime = 0
  let timer = null

  const percent = computed(() => {
    const est = estByModel[modelIdRef.value]
    const e = elapsedMs.value
    if (est) return Math.min(99, Math.floor((e / est) * 100))
    return Math.floor(90 * (1 - Math.exp(-e / 2500)))
  })

  const fmtEta = (sec) => {
    if (!isFinite(sec) || sec < 0) return '--'
    const s = Math.round(sec)
    return s < 60 ? `${s} 秒` : `${Math.floor(s / 60)} 分 ${s % 60} 秒`
  }

  const etaText = computed(() => {
    const est = estByModel[modelIdRef.value]
    if (!est) return '首次任务加载模型，请稍候…'
    const remain = (est - elapsedMs.value) / 1000
    return remain > 0 ? fmtEta(remain) : '即将完成'
  })

  const elapsedText = computed(() => `${(elapsedMs.value / 1000).toFixed(1)} 秒`)

  const start = () => {
    running.value = true
    startTime = Date.now()
    elapsedMs.value = 0
    timer = setInterval(() => { elapsedMs.value = Date.now() - startTime }, 100)
  }

  const finish = () => {
    if (timer) { clearInterval(timer); timer = null }
    if (startTime) estByModel[modelIdRef.value] = Date.now() - startTime // 记录耗时供下次估算
    running.value = false
  }

  const stop = () => {
    if (timer) { clearInterval(timer); timer = null }
    running.value = false
  }

  return { running, elapsedMs, percent, etaText, elapsedText, start, finish, stop }
}
