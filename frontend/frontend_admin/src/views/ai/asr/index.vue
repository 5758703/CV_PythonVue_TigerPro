<template>
  <div class="asr-page">
    <div class="asr-layout">
      <!-- 左侧：上传 + 识别设置 -->
      <aside class="asr-side">
        <el-card shadow="never" class="side-card">
          <div class="step-title"><span class="step-num">1</span>上传媒体文件</div>
          <el-upload
            class="media-upload"
            drag
            :show-file-list="false"
            :auto-upload="false"
            :on-change="onPick"
            accept="audio/*,video/*,.mp4,.mov,.mkv,.avi,.webm,.wav,.mp3,.m4a,.flac,.ogg,.aac"
          >
            <el-icon class="upload-icon"><UploadFilled /></el-icon>
            <div class="upload-text">点击或拖拽上传音/视频</div>
            <div class="upload-hint">音频 WAV/MP3/M4A… · 视频 MP4/MOV/MKV/AVI/WebM</div>
          </el-upload>
          <div v-if="file" class="file-chip">
            <el-icon :size="18"><component :is="isVideo ? VideoCamera : Headset" /></el-icon>
            <div class="file-meta">
              <div class="file-name" :title="file.name">{{ file.name }}</div>
              <div class="file-sub">
                {{ fmtSize(mediaInfo?.size) }}
                <template v-if="mediaInfo?.duration"> · {{ fmtDuration(mediaInfo.duration) }}</template>
                <el-tag size="small" effect="plain" type="info">{{ isVideo ? '视频' : '音频' }}</el-tag>
              </div>
            </div>
            <el-button link type="danger" :icon="Close" @click="clearMedia" />
          </div>
        </el-card>

        <el-card shadow="never" class="side-card">
          <div class="step-title"><span class="step-num">2</span>识别设置</div>
          <el-form label-position="top" class="settings-form">
            <el-form-item label="语音模型">
              <el-select v-model="modelId" placeholder="选择模型" style="width: 100%">
                <el-option
                  v-for="m in filteredModels"
                  :key="m.id"
                  :label="`${m.modelName}`"
                  :value="m.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="模型分类">
              <el-select v-model="category" placeholder="全部分类" clearable style="width: 100%" @change="onCategoryChange">
                <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="isNanoModel" label="识别语言">
              <el-select v-model="asrLanguage" style="width: 100%">
                <el-option label="自动检测" value="auto" />
                <el-option label="中文" value="中文" />
                <el-option label="英文" value="英文" />
                <el-option label="日文" value="日文" />
              </el-select>
            </el-form-item>
            <el-form-item label="区分说话人">
              <div class="switch-row">
                <el-switch v-model="diarize" :disabled="!isMossModel" />
                <span class="switch-hint">{{ isMossModel ? 'MOSS 多人分段' : '需选用 MOSS-Transcribe-Diarize' }}</span>
              </div>
            </el-form-item>
            <el-form-item label="过滤词（可选）">
              <el-input v-model="filterWords" placeholder="例如: 嗯, 啊, 呢" clearable />
            </el-form-item>
          </el-form>
          <el-alert
            v-if="!modelOptions.length"
            type="warning"
            :closable="false"
            title="暂无可用语音模型，请到「模型管理」拉取。"
            class="mb8"
          />
          <el-button
            type="primary"
            size="large"
            class="run-btn"
            :icon="MagicStick"
            :loading="running"
            :disabled="!modelId || !file"
            @click="run"
          >
            开始识别
          </el-button>
          <el-button size="large" class="clear-btn" :icon="Refresh" @click="clearAll">清空</el-button>
        </el-card>
      </aside>

      <!-- 右侧主区 -->
      <main class="asr-main">
        <div class="preview-row">
          <el-card shadow="never" class="media-card">
            <template #header>
              <span>媒体预览</span>
              <el-tag v-if="isVideo && running" size="small" type="warning" effect="plain">视频将先抽音再转写</el-tag>
            </template>
            <div v-if="mediaSrc" class="media-stage">
              <video
                v-if="isVideo"
                ref="mediaEl"
                :src="mediaSrc"
                controls
                class="media-player"
                @timeupdate="onTimeUpdate"
                @loadedmetadata="onMediaMeta"
              />
              <audio
                v-else
                ref="mediaEl"
                :src="mediaSrc"
                controls
                class="audio-player"
                @timeupdate="onTimeUpdate"
                @loadedmetadata="onMediaMeta"
              />
            </div>
            <el-empty v-else description="上传音/视频后在此预览" :image-size="72" />
          </el-card>

          <el-card shadow="never" class="subtitle-card">
            <template #header>
              <span>字幕预览</span>
              <div class="header-actions">
                <el-tag v-if="speakerCount && diarize" size="small" type="success" effect="plain">说话人 {{ speakerCount }}</el-tag>
                <el-tag v-if="displaySegments.length" size="small" type="info" effect="plain">{{ displaySegments.length }} 段</el-tag>
                <el-button v-if="displaySegments.length" link type="primary" :icon="CopyDocument" @click="copySegments">复制</el-button>
              </div>
            </template>
            <div v-if="running" class="progress-box">
              <div class="progress-title">识别中… 预计剩余 {{ etaText }}</div>
              <el-progress :percentage="percent" :stroke-width="14" :text-inside="true" />
              <div class="progress-hint">已用 {{ elapsedText }}{{ isVideo ? '（含抽音）' : '' }}</div>
            </div>
            <div v-else-if="displaySegments.length" class="sub-list" ref="subListEl">
              <div
                v-for="(row, i) in displaySegments"
                :key="i"
                class="sub-item"
                :class="{ active: isActiveSeg(row) }"
                :style="{ '--spk': speakerColor(row.speaker) }"
                @click="seekTo(row.start)"
              >
                <div class="sub-head">
                  <span v-if="diarize && row.speaker" class="spk-badge">{{ displaySpeaker(row.speaker) }}</span>
                  <span class="sub-time">{{ fmtSrtTime(row.start) }} → {{ fmtSrtTime(row.end) }}</span>
                </div>
                <div class="sub-text">{{ row.text }}</div>
              </div>
            </div>
            <div v-else-if="result?.text" class="plain-text">{{ result.text }}</div>
            <el-empty v-else description="识别结果将显示在这里" :image-size="72" />
          </el-card>
        </div>

        <!-- 时间轴 -->
        <el-card v-if="displaySegments.length" shadow="never" class="timeline-card">
          <div class="tl-toolbar">
            <el-button-group>
              <el-button :icon="currentPlaying ? VideoPause : VideoPlay" @click="togglePlay" />
            </el-button-group>
            <span class="tl-clock">{{ fmtSrtTime(currentTime) }}</span>
            <el-slider v-model="tlZoom" :min="1" :max="8" :step="0.5" style="width: 140px" />
            <span class="tl-zoom-label">缩放</span>
            <el-checkbox v-model="showScale">显示时间轴刻度</el-checkbox>
          </div>
          <div class="tl-scroll" ref="tlScrollEl" @click="onTimelineClick">
            <div class="tl-inner" :style="{ width: timelineWidthPx + 'px' }">
              <div v-if="showScale" class="tl-ruler">
                <span v-for="t in rulerTicks" :key="t" class="tl-tick" :style="{ left: timeToX(t) + 'px' }">{{ fmtDuration(t) }}</span>
              </div>
              <div
                v-for="spk in timelineSpeakers"
                :key="spk"
                class="tl-track"
              >
                <div class="tl-track-label">{{ displaySpeaker(spk) }}</div>
                <div class="tl-track-lane">
                  <div
                    v-for="(row, i) in segmentsForSpeaker(spk)"
                    :key="i"
                    class="tl-block"
                    :style="blockStyle(row)"
                    :title="row.text"
                    @click.stop="seekTo(row.start)"
                  >
                    {{ row.text }}
                  </div>
                </div>
              </div>
              <div class="tl-playhead" :style="{ left: timeToX(currentTime) + 'px' }" />
            </div>
          </div>
        </el-card>

        <!-- 导出 -->
        <el-card shadow="never" class="export-card">
          <div class="step-title"><span class="step-num">3</span>导出字幕文件</div>
          <div class="export-row">
            <el-button class="exp-json" :disabled="!canExport" @click="exportJson">
              <span class="exp-ico">{ }</span> JSON
            </el-button>
            <el-button class="exp-srt" :disabled="!canExport" @click="exportSrt">
              <el-icon><Document /></el-icon> SRT
            </el-button>
            <el-button class="exp-ass" :disabled="!canExport" @click="exportAss">
              <el-icon><ChatDotRound /></el-icon> ASS
            </el-button>
            <el-button :disabled="!result?.text" :icon="CopyDocument" @click="copy">复制全文</el-button>
          </div>
        </el-card>
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  UploadFilled, MagicStick, Refresh, CopyDocument, Close,
  VideoCamera, Headset, VideoPlay, VideoPause, Document, ChatDotRound,
} from '@element-plus/icons-vue'

import { modelApi } from '../../../api/ai'
import { useInferProgress } from '../../../composables/useInferProgress'

const AUDIO_EXTS = new Set(['.wav', '.mp3', '.m4a', '.flac', '.ogg', '.aac'])
const VIDEO_EXTS = new Set(['.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.webm'])
const SPK_COLORS = ['#3b82f6', '#22c55e', '#f59e0b', '#a855f7', '#ef4444', '#06b6d4', '#ec4899']

const modelOptions = ref([])
const modelId = ref(null)
const category = ref('')
const file = ref(null)
const mediaSrc = ref('')
const mediaInfo = ref(null)
const isVideo = ref(false)
const result = ref(null)
const asrLanguage = ref('auto')
const diarize = ref(true)
const filterWords = ref('')
const currentTime = ref(0)
const tlZoom = ref(2)
const showScale = ref(true)
const mediaEl = ref(null)
const currentPlaying = ref(false)
const subListEl = ref(null)
const tlScrollEl = ref(null)

const { running, percent, etaText, elapsedText, start, finish } = useInferProgress(modelId)

const extOf = (name) => {
  const i = (name || '').lastIndexOf('.')
  return i >= 0 ? name.slice(i).toLowerCase() : ''
}

const fmtSize = (bytes) => {
  if (!bytes) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let n = bytes
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`
}
const fmtDuration = (s) => {
  if (s == null || !isFinite(s)) return '00:00'
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}
const fmtSrtTime = (s) => {
  if (s == null || !Number.isFinite(Number(s))) return '00:00:00,000'
  const v = Math.max(0, Number(s))
  const h = Math.floor(v / 3600)
  const m = Math.floor((v % 3600) / 60)
  const sec = Math.floor(v % 60)
  const ms = Math.round((v - Math.floor(v)) * 1000)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')},${String(ms).padStart(3, '0')}`
}
const fmtAssTime = (s) => {
  if (s == null || !Number.isFinite(Number(s))) return '0:00:00.00'
  const v = Math.max(0, Number(s))
  const h = Math.floor(v / 3600)
  const m = Math.floor((v % 3600) / 60)
  const sec = Math.floor(v % 60)
  const cs = Math.round((v - Math.floor(v)) * 100)
  return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}.${String(cs).padStart(2, '0')}`
}

const selectedModel = computed(() => modelOptions.value.find((m) => m.id === modelId.value) || null)
const isNanoModel = computed(() => selectedModel.value?.library === 'funasr-nano')
const isMossModel = computed(() => (selectedModel.value?.modelKey || '').includes('moss-transcribe-diarize'))

watch(isMossModel, (v) => {
  if (v) diarize.value = true
})

const filterList = computed(() =>
  filterWords.value.split(/[,，、\s]+/).map((w) => w.trim()).filter(Boolean)
)

const applyFilter = (text) => {
  let t = (text || '').trim()
  for (const w of filterList.value) {
    if (!w) continue
    t = t.split(w).join('')
  }
  return t.replace(/\s{2,}/g, ' ').trim()
}

const rawSegments = computed(() => {
  const segs = result.value?.segments
  if (Array.isArray(segs) && segs.length) {
    return segs.map((s) => ({
      speaker: s.speaker || 'S01',
      start: Number(s.start) || 0,
      end: Number(s.end) || 0,
      text: applyFilter(s.text || ''),
    })).filter((s) => s.text)
  }
  const text = applyFilter(result.value?.text || '')
  if (!text) return []
  return [{ speaker: 'S01', start: 0, end: mediaInfo.value?.duration || 0, text }]
})

const displaySegments = computed(() => {
  if (!diarize.value) {
    return rawSegments.value.map((s) => ({ ...s, speaker: '' }))
  }
  return rawSegments.value
})

const speakerCount = computed(() =>
  new Set(rawSegments.value.map((s) => s.speaker).filter(Boolean)).size
)

const timelineSpeakers = computed(() => {
  if (!diarize.value) return ['字幕']
  const set = [...new Set(rawSegments.value.map((s) => s.speaker).filter(Boolean))]
  return set.length ? set : ['S01']
})

const duration = computed(() => {
  const fromMeta = mediaInfo.value?.duration || 0
  const fromSeg = displaySegments.value.reduce((m, s) => Math.max(m, Number(s.end) || 0), 0)
  return Math.max(fromMeta, fromSeg, 1)
})

const timelineWidthPx = computed(() => Math.max(600, duration.value * 40 * tlZoom.value))

const rulerTicks = computed(() => {
  const d = duration.value
  const step = d > 120 ? 30 : d > 60 ? 10 : d > 20 ? 5 : 2
  const ticks = []
  for (let t = 0; t <= d + 0.01; t += step) ticks.push(Math.round(t * 100) / 100)
  return ticks
})

const canExport = computed(() => displaySegments.value.length > 0)

const categories = computed(() => [...new Set(modelOptions.value.map((m) => m.category).filter(Boolean))])
const filteredModels = computed(() =>
  category.value ? modelOptions.value.filter((m) => m.category === category.value) : modelOptions.value
)
const onCategoryChange = () => {
  modelId.value = filteredModels.value[0]?.id || null
  result.value = null
}

const PREFERRED_ASR_KEYS = ['moss-transcribe-diarize-0p9b', 'paraformer-zh']
const asrRank = (key) => {
  const i = PREFERRED_ASR_KEYS.indexOf(key)
  return i === -1 ? 999 : i
}

const speakerColor = (spk) => {
  const list = [...new Set(rawSegments.value.map((s) => s.speaker).filter(Boolean))]
  const idx = Math.max(0, list.indexOf(spk))
  return SPK_COLORS[idx % SPK_COLORS.length]
}

const displaySpeaker = (spk) => {
  if (!spk || spk === '字幕') return '字幕'
  const m = String(spk).match(/(\d+)/)
  return m ? `说话人 ${Number(m[1])}` : spk
}

const segmentsForSpeaker = (spk) => {
  if (!diarize.value) return displaySegments.value
  return rawSegments.value.filter((s) => s.speaker === spk)
}

const timeToX = (t) => (Number(t) / duration.value) * timelineWidthPx.value

const blockStyle = (row) => {
  const left = timeToX(row.start)
  const width = Math.max(8, timeToX(row.end) - left)
  return {
    left: `${left}px`,
    width: `${width}px`,
    background: diarize.value ? speakerColor(row.speaker) : SPK_COLORS[0],
  }
}

const isActiveSeg = (row) => {
  const t = currentTime.value
  return t >= row.start && t < (row.end || row.start + 0.01)
}

const onMediaMeta = (e) => {
  const d = e?.target?.duration
  if (d && isFinite(d)) {
    mediaInfo.value = { ...(mediaInfo.value || {}), size: file.value?.size || 0, duration: d }
  }
}
const onTimeUpdate = (e) => {
  currentTime.value = e?.target?.currentTime || 0
  currentPlaying.value = !e?.target?.paused
}

const seekTo = (t) => {
  const el = mediaEl.value
  if (!el || t == null) return
  el.currentTime = Math.max(0, Number(t))
  currentTime.value = el.currentTime
}

const togglePlay = () => {
  const el = mediaEl.value
  if (!el) return
  if (el.paused) el.play()
  else el.pause()
}

const onTimelineClick = (e) => {
  const sc = tlScrollEl.value
  if (!sc) return
  const rect = sc.getBoundingClientRect()
  const x = e.clientX - rect.left + sc.scrollLeft
  const t = (x / timelineWidthPx.value) * duration.value
  seekTo(t)
}

const ASR_LIBS = new Set(['funasr', 'funasr-onnx', 'funasr-nano', 'transformers'])
const loadModels = async () => {
  const res = await modelApi.options({ task: 'automatic-speech-recognition' })
  const rows = (res.data || []).filter(
    (m) => ASR_LIBS.has(m.library) && m.filePath && m.status === '0'
  )
  rows.sort((a, b) => asrRank(a.modelKey) - asrRank(b.modelKey))
  modelOptions.value = rows
  if (modelOptions.value.length && !modelId.value) {
    const moss = modelOptions.value.find((m) => (m.modelKey || '').includes('moss-transcribe-diarize'))
    modelId.value = moss?.id || modelOptions.value[0].id
  }
}

const onPick = (uploadFile) => {
  const raw = uploadFile.raw
  if (!raw) return
  const ext = extOf(raw.name)
  const okAudio = AUDIO_EXTS.has(ext) || (raw.type || '').startsWith('audio/')
  const okVideo = VIDEO_EXTS.has(ext) || (raw.type || '').startsWith('video/')
  if (!okAudio && !okVideo) {
    ElMessage.error('请选择音频或视频文件')
    return
  }
  clearMedia(false)
  file.value = raw
  isVideo.value = VIDEO_EXTS.has(ext) || ((raw.type || '').startsWith('video/') && !AUDIO_EXTS.has(ext))
  mediaSrc.value = URL.createObjectURL(raw)
  mediaInfo.value = { size: raw.size, duration: 0 }
  result.value = null
}

const clearMedia = (resetResult = true) => {
  if (mediaSrc.value) URL.revokeObjectURL(mediaSrc.value)
  file.value = null
  mediaSrc.value = ''
  mediaInfo.value = null
  isVideo.value = false
  currentTime.value = 0
  if (resetResult) result.value = null
}

const run = async () => {
  start()
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    if (isNanoModel.value) fd.append('language', asrLanguage.value)
    const res = await modelApi.transcribe(modelId.value, fd)
    result.value = res.data
    await nextTick()
  } finally {
    finish()
  }
}

const downloadBlob = (content, filename, mime) => {
  const blob = content instanceof Blob ? content : new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

const baseName = computed(() => {
  const n = file.value?.name || 'subtitle'
  return n.replace(/\.[^.]+$/, '') || 'subtitle'
})

const exportJson = () => {
  const payload = {
    media: file.value?.name || null,
    diarize: diarize.value,
    language: result.value?.language || null,
    text: result.value?.text || '',
    segments: displaySegments.value,
  }
  downloadBlob(JSON.stringify(payload, null, 2), `${baseName.value}.json`, 'application/json')
  ElMessage.success('已导出 JSON')
}

const exportSrt = () => {
  const lines = displaySegments.value.map((s, i) => {
    const head = diarize.value && s.speaker ? `${displaySpeaker(s.speaker)}: ${s.text}` : s.text
    return `${i + 1}\n${fmtSrtTime(s.start)} --> ${fmtSrtTime(s.end)}\n${head}\n`
  })
  downloadBlob(lines.join('\n'), `${baseName.value}.srt`, 'text/plain;charset=utf-8')
  ElMessage.success('已导出 SRT')
}

const exportAss = () => {
  const header = `[Script Info]
Title: ${baseName.value}
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,20,20,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
`
  const events = displaySegments.value.map((s) => {
    const name = diarize.value && s.speaker ? displaySpeaker(s.speaker) : ''
    const text = (s.text || '').replace(/\n/g, '\\N')
    return `Dialogue: 0,${fmtAssTime(s.start)},${fmtAssTime(s.end)},Default,${name},0,0,0,,${text}`
  })
  downloadBlob(header + events.join('\n'), `${baseName.value}.ass`, 'text/plain;charset=utf-8')
  ElMessage.success('已导出 ASS')
}

const copy = async () => {
  await navigator.clipboard.writeText(result.value?.text || '')
  ElMessage.success('已复制全文')
}

const copySegments = async () => {
  const lines = displaySegments.value.map(
    (r, i) => `${i + 1}. [${fmtSrtTime(r.start)} → ${fmtSrtTime(r.end)}] ${diarize.value && r.speaker ? displaySpeaker(r.speaker) + ': ' : ''}${r.text}`
  )
  await navigator.clipboard.writeText(lines.join('\n'))
  ElMessage.success('已复制分段')
}

const clearAll = () => {
  clearMedia(true)
}

onMounted(loadModels)
onBeforeUnmount(() => {
  clearMedia(true)
})
</script>

<style scoped>
.asr-page {
  --asr-bg: #f0f2f5;
  --asr-card: #fff;
  --asr-border: #e5e7eb;
  --asr-text: #1f2937;
  --asr-muted: #6b7280;
  --asr-primary: #2563eb;
  min-height: calc(100vh - 120px);
}
.asr-layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}
.asr-side {
  display: flex;
  flex-direction: column;
  gap: 12px;
  position: sticky;
  top: 8px;
}
.side-card,
.media-card,
.subtitle-card,
.timeline-card,
.export-card {
  border-radius: 12px;
  border: 1px solid var(--asr-border);
}
.step-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  color: var(--asr-text);
  margin-bottom: 12px;
  font-size: 15px;
}
.step-num {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--asr-primary);
  color: #fff;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.media-upload :deep(.el-upload-dragger) {
  padding: 28px 16px;
  border-radius: 10px;
  border-color: #bfdbfe;
  background: #f8fbff;
}
.upload-icon {
  font-size: 36px;
  color: var(--asr-primary);
  margin-bottom: 6px;
}
.upload-text {
  font-size: 14px;
  color: var(--asr-text);
  font-weight: 600;
}
.upload-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--asr-muted);
  line-height: 1.5;
}
.file-chip {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid var(--asr-border);
}
.file-meta {
  flex: 1;
  min-width: 0;
}
.file-name {
  font-weight: 600;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.file-sub {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--asr-muted);
  margin-top: 2px;
}
.settings-form :deep(.el-form-item) {
  margin-bottom: 12px;
}
.switch-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.switch-hint {
  font-size: 12px;
  color: var(--asr-muted);
}
.run-btn {
  width: 100%;
  margin-top: 4px;
}
.clear-btn {
  width: 100%;
  margin-top: 8px;
  margin-left: 0 !important;
}
.mb8 {
  margin-bottom: 8px;
}
.asr-main {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}
.preview-row {
  display: grid;
  grid-template-columns: 1.1fr 1fr;
  gap: 12px;
}
.media-card :deep(.el-card__header),
.subtitle-card :deep(.el-card__header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  font-weight: 600;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.media-stage {
  background: #0f172a;
  border-radius: 8px;
  overflow: hidden;
  min-height: 220px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.media-player {
  width: 100%;
  max-height: 320px;
  display: block;
  background: #000;
}
.audio-player {
  width: 100%;
  margin: 24px 16px;
}
.sub-list {
  max-height: 320px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sub-item {
  border-left: 3px solid var(--spk, #3b82f6);
  background: #f8fafc;
  border-radius: 0 8px 8px 0;
  padding: 8px 10px;
  cursor: pointer;
  transition: background 0.15s;
}
.sub-item:hover,
.sub-item.active {
  background: #eff6ff;
}
.sub-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.spk-badge {
  font-size: 12px;
  font-weight: 700;
  color: var(--spk, #3b82f6);
}
.sub-time {
  font-size: 11px;
  color: var(--asr-muted);
  font-variant-numeric: tabular-nums;
}
.sub-text {
  font-size: 14px;
  line-height: 1.55;
  color: var(--asr-text);
}
.plain-text {
  white-space: pre-wrap;
  line-height: 1.8;
  font-size: 14px;
  color: var(--asr-text);
  max-height: 320px;
  overflow: auto;
}
.progress-box {
  padding: 20px 8px;
}
.progress-title {
  font-weight: 600;
  margin-bottom: 10px;
}
.progress-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--asr-muted);
}
.timeline-card {
  padding-bottom: 4px;
}
.tl-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.tl-clock {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: var(--asr-text);
  min-width: 110px;
}
.tl-zoom-label {
  font-size: 12px;
  color: var(--asr-muted);
}
.tl-scroll {
  overflow-x: auto;
  overflow-y: hidden;
  border: 1px solid var(--asr-border);
  border-radius: 8px;
  background: #fafafa;
  position: relative;
  cursor: crosshair;
}
.tl-inner {
  position: relative;
  min-height: 80px;
  padding: 8px 0 12px;
}
.tl-ruler {
  position: relative;
  height: 22px;
  border-bottom: 1px solid #e5e7eb;
  margin-bottom: 4px;
}
.tl-tick {
  position: absolute;
  top: 2px;
  transform: translateX(-50%);
  font-size: 10px;
  color: #9ca3af;
  white-space: nowrap;
}
.tl-track {
  display: grid;
  grid-template-columns: 72px 1fr;
  align-items: center;
  min-height: 36px;
  margin: 4px 0;
}
.tl-track-label {
  font-size: 12px;
  color: var(--asr-muted);
  padding-left: 8px;
  white-space: nowrap;
}
.tl-track-lane {
  position: relative;
  height: 28px;
}
.tl-block {
  position: absolute;
  top: 2px;
  height: 24px;
  border-radius: 4px;
  color: #fff;
  font-size: 11px;
  line-height: 24px;
  padding: 0 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  opacity: 0.92;
  cursor: pointer;
}
.tl-playhead {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--asr-primary);
  pointer-events: none;
  z-index: 2;
}
.export-card .step-title {
  margin-bottom: 14px;
}
.export-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.exp-json,
.exp-srt,
.exp-ass {
  min-width: 110px;
  font-weight: 600;
  color: #fff !important;
  border: none !important;
}
.exp-json {
  background: #7c3aed !important;
}
.exp-srt {
  background: #16a34a !important;
}
.exp-ass {
  background: #ea580c !important;
}
.exp-ico {
  font-family: ui-monospace, monospace;
  margin-right: 4px;
}
@media (max-width: 1100px) {
  .asr-layout {
    grid-template-columns: 1fr;
  }
  .asr-side {
    position: static;
  }
  .preview-row {
    grid-template-columns: 1fr;
  }
}
</style>
