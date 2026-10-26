const ASR_LIBS = new Set(['funasr', 'funasr-onnx', 'funasr-nano', 'transformers', 'confucius-r2t2',
  'sherpa-onnx-asr', 'faster-whisper', 'moonshine-streaming'])
const CATALOG_CPU_LIBS = new Set(['sherpa-onnx-asr', 'faster-whisper', 'moonshine-streaming'])

export function selectableAudioModels(rows) {
  return rows.filter((m) => m.status === '0' && (
    m.library === 'moss-music-gguf' ||
    (m.task === 'automatic-speech-recognition' && ASR_LIBS.has(m.library) &&
      (!CATALOG_CPU_LIBS.has(m.library) || m.asrCpu === true) &&
      (m.asrCpu === true || m.filePath || m.library === 'confucius-r2t2'))
  ))
}

export function hasSubtitleTimestamps(result) {
  return !!result && result.timestampsAvailable !== false
}

export function asrResultNotice(result) {
  if (!result) return ''
  if (!String(result.text || '').trim()) {
    return result.recognitionMessage || '未识别到文字。请确认录音中有人声且音量清晰，并使用模型支持的语言。'
  }
  return result.timestampsAvailable === false
    ? '识别完成；当前结果仅包含文字，没有可用的字幕时间戳。可复制全文或导出 JSON。' : ''
}

function subtitleClock(seconds, scale) {
  const value = Number(seconds)
  const total = Number.isFinite(value) ? Math.round(Math.max(0, value) * scale) : 0
  return [Math.floor(total / (3600 * scale)),
    String(Math.floor(total / (60 * scale)) % 60).padStart(2, '0'),
    String(Math.floor(total / scale) % 60).padStart(2, '0'), total % scale]
}

export function fmtSrtTime(seconds) {
  const [hours, minutes, secs, fraction] = subtitleClock(seconds, 1000)
  return `${String(hours).padStart(2, '0')}:${minutes}:${secs},${String(fraction).padStart(3, '0')}`
}

export function fmtAssTime(seconds) {
  const [hours, minutes, secs, fraction] = subtitleClock(seconds, 100)
  return `${hours}:${minutes}:${secs}.${String(fraction).padStart(2, '0')}`
}
