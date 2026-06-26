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
          <el-select v-model="modelId" placeholder="选择模型" style="width: 240px" @change="loadSpeakers">
            <el-option
              v-for="m in filteredModels"
              :key="m.id"
              :label="`${m.modelName}（${m.category || '未分类'}）`"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="isVoxcpm" label="音色克隆">
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
        title="暂无可用语音合成模型：请到「模型管理」新增 CosyVoice 文本转语音模型并拉取权重。"
      />
      <el-alert
        v-else-if="isClone"
        type="info"
        :closable="false"
        show-icon
        title="零样本音色克隆：上传一段 3~10 秒参考音频并填写其文本，模型将用该音色朗读你的目标文本。"
      />
    </el-card>

    <el-card shadow="never">
      <div v-if="isClone" class="clone-box">
        <div class="clone-row">
          <el-upload :show-file-list="false" :auto-upload="false" :on-change="onPickPrompt" accept="audio/*">
            <el-button :icon="UploadFilled">选择参考音频</el-button>
          </el-upload>
          <span v-if="promptAudioFile" class="meta">{{ promptAudioFile.name }}</span>
          <audio v-if="promptAudioSrc" :src="promptAudioSrc" controls class="prompt-player" />
        </div>
        <el-input v-model="promptText" class="prompt-text" placeholder="参考音频对应的文本（必填，需与音频内容一致）" />
      </div>
      <el-input v-model="text" type="textarea" :rows="5" maxlength="500" show-word-limit :placeholder="isVoxcpm ? '输入文本；可在开头用括号描述音色，如「(年轻女声，温柔)你好…」' : '输入要合成的文本…'" />
      <div class="bar">
        <el-button type="primary" :icon="Microphone" :loading="running" :disabled="!modelId || !text.trim() || (isClone && (!promptAudioFile || !promptText.trim()))" @click="run">开始合成</el-button>
        <el-button :icon="Refresh" @click="clearAll">清空</el-button>
        <span class="meta">字符数：{{ text.length }}</span>
      </div>

      <div v-if="running" class="progress-box">
        <div class="progress-title">合成中… 预计剩余 {{ etaText }}</div>
        <el-progress :percentage="percent" :stroke-width="18" :text-inside="true" :status="percent >= 100 ? 'success' : ''" />
        <div class="progress-hint">已用 {{ elapsedText }}</div>
      </div>

      <div v-if="!running && audioUrl" class="result">
        <div class="res-title">
          合成结果（{{ resSpeaker }} · {{ sampleRate }} Hz）
          <el-button link type="primary" :icon="Download" @click="download">下载 WAV</el-button>
        </div>
        <audio :src="audioUrl" controls autoplay class="player" />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { Microphone, Refresh, Download, UploadFilled } from '@element-plus/icons-vue'

import { modelApi } from '../../../api/ai'
import { useInferProgress } from '../../../composables/useInferProgress'

const modelOptions = ref([])
const modelId = ref(null)
const category = ref('')
const text = ref('')
const speaker = ref('中文女')
const speakers = ref(['中文女', '中文男', '日语男', '粤语女', '英文女', '英文男', '韩语女'])
const audioUrl = ref('')
const sampleRate = ref(0)
const resSpeaker = ref('')
// 零样本克隆（CosyVoice2 / version v2）
const promptAudioFile = ref(null)
const promptAudioSrc = ref('')
const promptText = ref('')
const useClone = ref(false)  // 仅 voxcpm：是否启用音色克隆
const isVoxcpm = computed(() => currentModel.value?.library === 'voxcpm')

const { running, percent, etaText, elapsedText, start, finish } = useInferProgress(modelId)

const categories = computed(() => [...new Set(modelOptions.value.map((m) => m.category).filter(Boolean))])
const filteredModels = computed(() =>
  category.value ? modelOptions.value.filter((m) => m.category === category.value) : modelOptions.value
)
const currentModel = computed(() => modelOptions.value.find((m) => m.id === modelId.value) || null)
const isClone = computed(() =>
  (currentModel.value?.library === 'cosyvoice' && currentModel.value?.version === 'v2') ||
  (isVoxcpm.value && useClone.value)
)
const onCategoryChange = () => {
  modelId.value = filteredModels.value[0]?.id || null
  loadSpeakers()
}

// 首选语音合成模型：MeloTTS 中英混合（默认置顶并默认选中）
const PREFERRED_TTS_KEY = 'melotts-zh-en'

const loadModels = async () => {
  const res = await modelApi.list({ pageNum: 1, pageSize: 100 })
  const rows = (res.data.rows || []).filter(
    (m) => (m.library === 'cosyvoice' || m.library === 'transformers' || m.library === 'vibevoice' || m.library === 'sherpa-onnx' || m.library === 'voxcpm') &&
      m.task === 'text-to-speech' && m.filePath && m.status === '0'
  )
  rows.sort((a, b) => (b.modelKey === PREFERRED_TTS_KEY) - (a.modelKey === PREFERRED_TTS_KEY))
  modelOptions.value = rows
  if (modelOptions.value.length && !modelId.value) modelId.value = modelOptions.value[0].id
  loadSpeakers()
}

const loadSpeakers = async () => {
  if (!modelId.value) return
  useClone.value = false
  try {
    const res = await modelApi.ttsSpeakers(modelId.value)
    speakers.value = Array.isArray(res.data) ? res.data : []
    if (speakers.value.length && !speakers.value.includes(speaker.value)) speaker.value = speakers.value[0]
  } catch (e) { speakers.value = [] }
}

const revoke = () => { if (audioUrl.value) { URL.revokeObjectURL(audioUrl.value); audioUrl.value = '' } }
const revokePrompt = () => { if (promptAudioSrc.value) { URL.revokeObjectURL(promptAudioSrc.value); promptAudioSrc.value = '' } }

const onPickPrompt = (uploadFile) => {
  const raw = uploadFile.raw
  if (!raw || !raw.type.startsWith('audio/')) { ElMessage.error('请选择音频文件'); return }
  promptAudioFile.value = raw
  revokePrompt()
  promptAudioSrc.value = URL.createObjectURL(raw)
}

const run = async () => {
  start()
  try {
    let d
    if (isClone.value) {
      const fd = new FormData()
      fd.append('promptAudio', promptAudioFile.value)
      fd.append('promptText', promptText.value)
      fd.append('text', text.value)
      d = (await modelApi.ttsClone(modelId.value, fd)).data
    } else {
      d = (await modelApi.tts(modelId.value, text.value, speaker.value)).data
    }
    const bin = atob(d.audio)
    const bytes = new Uint8Array(bin.length)
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
    revoke()
    audioUrl.value = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }))
    sampleRate.value = d.sampleRate
    resSpeaker.value = d.speaker
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
onBeforeUnmount(() => { revoke(); revokePrompt() })
</script>

<style scoped>
.cfg-card {
  margin-bottom: 12px;
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
  margin-bottom: 14px;
  padding: 14px;
  background: #f4f6fb;
  border-radius: 8px;
}
.clone-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.prompt-player {
  height: 32px;
}
.prompt-text {
  margin-top: 2px;
}
</style>
