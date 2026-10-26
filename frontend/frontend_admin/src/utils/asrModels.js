const ASR_LIBS = new Set(['funasr', 'funasr-onnx', 'funasr-nano', 'transformers', 'confucius-r2t2'])

export function selectableAudioModels(rows) {
  return rows.filter((m) => m.status === '0' && (
    m.library === 'moss-music-gguf' ||
    (m.task === 'automatic-speech-recognition' && ASR_LIBS.has(m.library) &&
      (m.filePath || m.library === 'confucius-r2t2'))
  ))
}

export function hasSubtitleTimestamps(result) {
  return !!result && result.timestampsAvailable !== false
}
