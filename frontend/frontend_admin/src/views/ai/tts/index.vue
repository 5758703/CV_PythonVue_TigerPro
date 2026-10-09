<template>
  <div>
    <el-card shadow="never" class="cfg-card">
      <el-form :inline="true">
        <el-form-item label="模型分类">
          <el-select v-model="category" placeholder="全部分类" clearable style="width: 150px" @change="onCategoryChange">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="语音模型">
          <el-select
            v-model="modelId"
            placeholder="选择模型"
            filterable
            style="width: 340px"
            @change="onModelChange"
          >
            <el-option
              v-for="m in filteredModels"
              :key="m.id"
              :label="optionLabel(m)"
              :value="Number(m.id)"
            >
              <span>{{ m.modelName }}</span>
              <span class="opt-meta">{{ m.category || '未分类' }}</span>
              <el-tag v-if="isCloneRequiredModel(m)" size="small" type="warning" style="margin-left: 8px">需克隆</el-tag>
              <el-tag v-else-if="isCloneCapableModel(m)" size="small" type="success" style="margin-left: 8px">可克隆</el-tag>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item v-if="supportsClone && !cloneRequired" label="音色克隆">
          <el-switch v-model="useClone" />
        </el-form-item>
        <el-form-item v-if="!isClone && speakers.length" label="音色">
          <el-select v-model="speaker" placeholder="选择音色" style="width: 130px">
            <el-option v-for="s in speakers" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
      </el-form>

      <el-alert
        v-if="!modelOptions.length"
        type="warning"
        :closable="false"
        title="暂无可用语音合成模型：请到「模型管理」新增语音合成模型并拉取权重。"
      />
      <el-alert
        v-else-if="isClone"
        type="info"
        :closable="false"
        show-icon
        :title="cloneHint"
      />
      <el-alert
        v-else-if="hasCloneModels"
        type="warning"
        :closable="false"
        show-icon
        title="当前模型不支持音色克隆。请在「语音模型」中选择带「需克隆 / 可克隆」标签的模型（如 NeuTTS Air）。"
      />

      <div v-if="currentModel" class="current-tip">
        当前：{{ currentModel.modelName }}
        <span class="opt-meta">library={{ currentModel.library }} · key={{ currentModel.modelKey }}</span>
      </div>
    </el-card>

    <el-card shadow="never">
      <div v-if="isClone" class="clone-box">
        <div class="section-label">① 参考音频（克隆音色）</div>
        <div class="clone-row">
          <el-upload
            :show-file-list="false"
            :auto-upload="false"
            :on-change="onPickPrompt"
            accept="audio/*,.wav,.mp3,.flac,.ogg,.m4a"
          >
            <el-button type="primary" plain :icon="UploadFilled">上传参考音频</el-button>
          </el-upload>
          <span v-if="promptAudioFile" class="meta">{{ promptAudioFile.name }}</span>
          <span v-else class="meta hint">建议 mono · 16–44kHz · 3–15 秒 · 干净无噪</span>
        </div>
        <audio v-if="promptAudioSrc" :src="promptAudioSrc" controls class="prompt-player" />

        <div class="section-label">② 参考音频对应文本（必填，需与音频内容一致）</div>
        <el-input
          v-model="promptText"
          type="textarea"
          :rows="2"
          maxlength="1000"
          show-word-limit
          placeholder="把参考音频里说的话原样写在这里…"
        />
      </div>

      <div class="section-label">{{ isClone ? '③ 要合成的目标文本' : '待合成文本' }}</div>
      <el-input
        v-model="text"
        type="textarea"
        :rows="5"
        maxlength="500"
        show-word-limit
        :placeholder="textPlaceholder"
      />

      <div class="bar">
        <el-button type="primary" :icon="Microphone" :loading="running" :disabled="!canSubmit" @click="run">
          开始合成
        </el-button>
        <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        <span class="meta">目标文本：{{ text.length }} 字</span>
      </div>

      <div v-if="running" class="progress-box">
        <div class="progress-title">合成中… 预计剩余 {{ etaText }}</div>
        <el-progress
          :percentage="percent"
          :stroke-width="18"
          :text-inside="true"
          :status="percent >= 100 ? 'success' : ''"
        />
        <div class="progress-hint">已用 {{ elapsedText }}</div>
      </div>

      <div v-if="!running && audioUrl" class="result">
        <div class="res-title">
          合成结果（{{ resSpeaker || '—' }} · {{ sampleRate }} Hz）
          <el-button link type="primary" :icon="Download" @click="download">下载 WAV</el-button>
        </div>
        <audio :src="audioUrl" controls autoplay class="player" />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { Microphone, Refresh, Download, UploadFilled } from '@element-plus/icons-vue'

import { modelApi } from '../../../api/ai'
import { useInferProgress } from '../../../composables/useInferProgress'

const CLONE_LIBS = new Set(['voxcpm', 'neutts'])
const CLONE_REQUIRED_LIBS = new Set(['neutts'])
const PREFERRED_TTS_KEY = 'melotts-zh-en'
const PREFERRED_CLONE_KEY = 'neutts-air'

const modelOptions = ref([])
const modelId = ref(null)
const category = ref('')
const text = ref('')
const speaker = ref('中文女')
const speakers = ref(['中文女', '中文男', '日语男', '粤语女', '英文女', '英文男', '韩语女'])
const audioUrl = ref('')
const sampleRate = ref(0)
const resSpeaker = ref('')
const promptAudioFile = ref(null)
const promptAudioSrc = ref('')
const promptText = ref('')
const useClone = ref(false)

const { running, percent, etaText, elapsedText, start, finish } = useInferProgress(modelId)

const categories = computed(() => [...new Set(modelOptions.value.map((m) => m.category).filter(Boolean))])
const filteredModels = computed(() =>
  category.value ? modelOptions.value.filter((m) => m.category === category.value) : modelOptions.value
)

const currentModel = computed(() => {
  if (modelId.value == null || modelId.value === '') return null
  const id = Number(modelId.value)
  return modelOptions.value.find((m) => Number(m.id) === id) || null
})

function modelLibOf(m) {
  return String(m?.library || '').toLowerCase()
}
function modelKeyOf(m) {
  return String(m?.modelKey || '').toLowerCase()
}
function isCloneCapableModel(m) {
  if (!m) return false
  if (m.ttsClone === true) return true
  if (m.ttsClone === false) return false
  const lib = modelLibOf(m)
  const key = modelKeyOf(m)
  return CLONE_LIBS.has(lib) || key.includes('neutts') || key.includes('voxcpm')
}
function isCloneRequiredModel(m) {
  if (!m) return false
  if (m.ttsCloneRequired === true) return true
  if (m.ttsCloneRequired === false) return false
  const lib = modelLibOf(m)
  const key = modelKeyOf(m)
  return CLONE_REQUIRED_LIBS.has(lib) || key.includes('neutts')
}

const supportsClone = computed(() => isCloneCapableModel(currentModel.value))
const cloneRequired = computed(() => isCloneRequiredModel(currentModel.value))
const isClone = computed(() => !!(cloneRequired.value || (supportsClone.value && useClone.value)))
const hasCloneModels = computed(() => modelOptions.value.some((m) => isCloneCapableModel(m)))

const cloneHint = computed(() =>
  cloneRequired.value
    ? '已选中需克隆模型：请完成 ① 上传参考音频 ② 填写参考文本 ③ 填写目标合成文本（NeuTTS 建议英文）。'
    : '零样本音色克隆：上传参考音频并填写其文本，模型将用该音色朗读目标文本。'
)

const textPlaceholder = computed(() => {
  if (cloneRequired.value || modelLibOf(currentModel.value) === 'neutts') {
    return '输入要合成的英文目标文本，例如：Hello, my name is Dave…'
  }
  if (modelLibOf(currentModel.value) === 'voxcpm') {
    return '输入文本；可在开头用括号描述音色，如「(年轻女声，温柔)你好…」'
  }
  return '输入要合成的文本…'
})

const canSubmit = computed(() => {
  if (!modelId.value || !text.value.trim() || running.value) return false
  if (isClone.value) return !!(promptAudioFile.value && promptText.value.trim())
  return true
})

function optionLabel(m) {
  const tag = isCloneRequiredModel(m) ? ' · 需克隆' : isCloneCapableModel(m) ? ' · 可克隆' : ''
  return `${m.modelName}（${m.category || '未分类'}）${tag}`
}

function syncCloneMode() {
  if (cloneRequired.value) useClone.value = true
  else if (!supportsClone.value) useClone.value = false
}

function onCategoryChange() {
  const first = filteredModels.value[0]
  modelId.value = first ? Number(first.id) : null
  onModelChange()
}

async function onModelChange() {
  if (modelId.value != null) modelId.value = Number(modelId.value)
  await nextTick()
  syncCloneMode()
  await loadSpeakers()
}

function rankModel(m) {
  const key = modelKeyOf(m)
  if (key === PREFERRED_CLONE_KEY || key.includes('neutts')) return 0
  if (key === PREFERRED_TTS_KEY) return 1
  if (isCloneCapableModel(m)) return 2
  return 3
}

async function loadModels() {
  const res = await modelApi.options({ task: 'text-to-speech' })
  const rows = [...(res.data || [])].map((m) => ({ ...m, id: Number(m.id) }))
  rows.sort((a, b) => rankModel(a) - rankModel(b) || String(a.modelName || '').localeCompare(String(b.modelName || ''), 'zh'))
  modelOptions.value = rows

  // 优先选中 NeuTTS（有权重时）；否则 MeloTTS；否则第一项
  const neutts = rows.find((m) => modelKeyOf(m).includes('neutts') || modelLibOf(m) === 'neutts')
  const melo = rows.find((m) => modelKeyOf(m) === PREFERRED_TTS_KEY)
  if (!modelId.value) {
    modelId.value = Number((neutts || melo || rows[0])?.id || 0) || null
  } else if (!rows.some((m) => Number(m.id) === Number(modelId.value))) {
    modelId.value = Number((neutts || melo || rows[0])?.id || 0) || null
  }
  await onModelChange()
}

async function loadSpeakers() {
  if (!modelId.value) return
  try {
    const res = await modelApi.ttsSpeakers(modelId.value)
    speakers.value = Array.isArray(res.data) ? res.data : []
    if (speakers.value.length && !speakers.value.includes(speaker.value)) speaker.value = speakers.value[0]
  } catch {
    speakers.value = []
  }
}

watch(
  () => [modelId.value, currentModel.value?.library, currentModel.value?.modelKey],
  () => { syncCloneMode() }
)

const revoke = () => {
  if (audioUrl.value) {
    URL.revokeObjectURL(audioUrl.value)
    audioUrl.value = ''
  }
}
const revokePrompt = () => {
  if (promptAudioSrc.value) {
    URL.revokeObjectURL(promptAudioSrc.value)
    promptAudioSrc.value = ''
  }
}

const onPickPrompt = (uploadFile) => {
  const raw = uploadFile.raw
  if (!raw) {
    ElMessage.error('未读取到音频文件')
    return
  }
  const okType = raw.type?.startsWith('audio/') || /\.(wav|mp3|flac|ogg|m4a)$/i.test(raw.name || '')
  if (!okType) {
    ElMessage.error('请选择音频文件（wav/mp3/flac 等）')
    return
  }
  promptAudioFile.value = raw
  revokePrompt()
  promptAudioSrc.value = URL.createObjectURL(raw)
}

const run = async () => {
  if (!canSubmit.value) {
    if (isClone.value && (!promptAudioFile.value || !promptText.value.trim())) {
      ElMessage.warning('请先上传参考音频，并填写参考音频对应文本与目标文本')
    }
    return
  }
  start()
  try {
    let d
    if (isClone.value) {
      const fd = new FormData()
      fd.append('promptAudio', promptAudioFile.value)
      fd.append('promptText', promptText.value.trim())
      fd.append('text', text.value.trim())
      d = (await modelApi.ttsClone(modelId.value, fd)).data
    } else {
      d = (await modelApi.tts(modelId.value, text.value.trim(), speaker.value)).data
    }
    const bin = atob(d.audio)
    const bytes = new Uint8Array(bin.length)
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
    revoke()
    audioUrl.value = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }))
    sampleRate.value = d.sampleRate
    resSpeaker.value = d.speaker
    ElMessage.success('合成完成')
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e?.message || '合成失败')
  } finally {
    finish()
  }
}

const download = () => {
  const prefix = currentModel.value?.modelKey || currentModel.value?.modelName || 'tts'
  const spk = resSpeaker.value ? `_${resSpeaker.value}` : ''
  const a = document.createElement('a')
  a.href = audioUrl.value
  a.download = `${prefix}${spk}_${Date.now()}.wav`
  a.click()
}

const clearAll = () => {
  text.value = ''
  revoke()
  sampleRate.value = 0
  resSpeaker.value = ''
  promptAudioFile.value = null
  promptText.value = ''
  revokePrompt()
}

onMounted(loadModels)
onBeforeUnmount(() => {
  revoke()
  revokePrompt()
})
</script>

<style scoped>
.cfg-card {
  margin-bottom: 12px;
}
.current-tip {
  margin-top: 10px;
  font-size: 12px;
  color: #5a6b87;
}
.opt-meta {
  margin-left: 8px;
  color: #909399;
  font-size: 12px;
}
.section-label {
  font-size: 13px;
  font-weight: 600;
  color: #3a4a63;
  margin: 4px 0 8px;
}
.bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 12px 0;
}
.meta {
  font-size: 13px;
  color: #5a6b87;
}
.meta.hint {
  color: #909399;
}
.progress-box {
  padding: 22px 4px;
}
.progress-title {
  font-weight: 600;
  color: #3a4a63;
  margin-bottom: 12px;
}
.progress-hint {
  margin-top: 10px;
  font-size: 12px;
  color: #909399;
}
.result {
  margin-top: 8px;
}
.res-title {
  display: flex;
  align-items: center;
  gap: 12px;
  font-weight: 600;
  color: #3a4a63;
  margin-bottom: 12px;
}
.player {
  width: 100%;
}
.clone-box {
  margin-bottom: 16px;
  padding: 14px 16px;
  background: #f4f6fb;
  border-radius: 8px;
  border: 1px solid #e8ecf4;
}
.clone-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 10px;
}
.prompt-player {
  display: block;
  width: 100%;
  height: 36px;
  margin: 0 0 12px;
}
</style>
