<template>
  <div>
    <el-tabs v-model="activeTab" type="border-card" class="alert-tabs" @tab-change="onTabChange">
      <el-tab-pane label="告警规则" name="rules">
        <div class="tab-toolbar">
          <span class="tab-desc">单项开关控制规则是否参与检测；总开关在各检测页。</span>
          <el-button size="small" @click="loadRules">刷新</el-button>
        </div>
        <el-table :data="rules" border stripe v-loading="rulesLoading" size="small">
          <el-table-column type="index" label="序号" width="64" align="center" />
          <el-table-column prop="name" label="规则" min-width="140" />
          <el-table-column prop="ruleType" label="类型" width="110">
            <template #default="{ row }">{{ ruleTypeLabel(row.ruleType) }}</template>
          </el-table-column>
          <el-table-column prop="severity" label="级别" width="80">
            <template #default="{ row }">
              <el-tag :type="severityType(row.severity)" size="small">{{ severityLabel(row.severity) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="阈值" min-width="180">
            <template #default="{ row }">{{ ruleThreshold(row) }}</template>
          </el-table-column>
          <el-table-column label="启用告警" width="100" align="center">
            <template #default="{ row }">
              <el-checkbox
                :model-value="row.status === '0'"
                :disabled="togglingId === row.id"
                v-permission="'ai:alert:edit'"
                @change="(val) => toggleRuleEnabled(row, val)"
              />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="88" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" v-permission="'ai:alert:edit'" @click="openEdit(row)">配置</el-button>
            </template>
          </el-table-column>
        </el-table>
        <p class="hint">
          每条规则右侧「启用告警」为单项开关（写入规则状态）。图片/视频/摄像头/追踪页的「启用告警」为总开关：总开关打开时，仅本页已启用的规则会生效。
        </p>
      </el-tab-pane>

      <el-tab-pane label="告警事件" name="events">
        <div class="tab-toolbar">
          <div class="tab-filters">
            <el-select v-model="query.status" clearable placeholder="全部状态" style="width: 120px" @change="loadEvents">
              <el-option label="未确认" value="0" />
              <el-option label="已确认" value="1" />
            </el-select>
            <el-button @click="loadEvents">刷新</el-button>
          </div>
        </div>
        <el-table :data="events" border stripe v-loading="eventsLoading" size="small">
          <el-table-column type="index" label="序号" width="64" align="center" :index="eventIndex" />
          <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
          <el-table-column prop="ruleName" label="规则" width="120" />
          <el-table-column label="级别" width="80">
            <template #default="{ row }">
              <el-tag :type="severityType(row.severity)" size="small">{{ severityLabel(row.severity) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="sourceKey" label="来源" min-width="120" show-overflow-tooltip />
          <el-table-column label="时间" width="168">
            <template #default="{ row }">{{ fmtTime(row.createTime) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="88">
            <template #default="{ row }">
              <el-tag :type="row.status === '0' ? 'danger' : 'success'" size="small">
                {{ row.status === '0' ? '未确认' : '已确认' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="showDetail(row)">详情</el-button>
              <el-button
                v-if="row.status === '0'"
                link
                type="success"
                v-permission="'ai:alert:edit'"
                @click="onAck(row)"
              >
                确认
              </el-button>
              <el-button link type="danger" v-permission="'ai:alert:remove'" @click="onRemove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination
            v-model:current-page="query.pageNum"
            v-model:page-size="query.pageSize"
            :total="total"
            layout="total, prev, pager, next"
            @current-change="loadEvents"
          />
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="detailDlg" title="告警详情" width="520px">
      <template v-if="detailRow">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="标题">{{ detailRow.title }}</el-descriptions-item>
          <el-descriptions-item label="规则">{{ detailRow.ruleName }}</el-descriptions-item>
          <el-descriptions-item label="说明">{{ detailRow.message }}</el-descriptions-item>
          <el-descriptions-item label="来源">{{ detailRow.sourceType }} / {{ detailRow.sourceKey }}</el-descriptions-item>
          <el-descriptions-item label="时间">{{ fmtTime(detailRow.createTime) }}</el-descriptions-item>
        </el-descriptions>
        <pre v-if="detailPayload" class="payload">{{ detailPayload }}</pre>
      </template>
    </el-dialog>

    <el-dialog v-model="editDlg" :title="`配置规则：${editForm.name || ''}`" width="760px" destroy-on-close>
      <el-form label-width="118px" size="small">
        <el-divider content-position="left">基本信息</el-divider>
        <el-form-item label="规则名称">
          <el-input v-model="editForm.name" maxlength="128" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="editForm.description" type="textarea" :rows="2" maxlength="500" />
        </el-form-item>
        <el-form-item label="级别">
          <el-radio-group v-model="editForm.severity">
            <el-radio value="high">高</el-radio>
            <el-radio value="medium">中</el-radio>
            <el-radio value="low">低</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="editEnabled" active-text="启用" inactive-text="停用" />
        </el-form-item>

        <el-divider content-position="left">触发条件</el-divider>
        <el-alert
          type="info"
          :closable="false"
          show-icon
          class="cfg-help-banner"
          title="以下参数决定何时判定为“满足条件”、何时弹窗记事件、何时在视频/摄像头画面叠加告警框。"
        />
        <template v-if="editForm.ruleType === 'class_presence'">
          <el-form-item label="目标类别">
            <el-input v-model="editCfg.classesText" placeholder="逗号分隔，如 fire,smoke 或 NO-Hardhat" />
            <div class="cfg-help">
              <p>检测框类别名命中列表中任意一项即算命中（不区分大小写，支持互相包含匹配）。</p>
              <p>烟火示例：<code>fire,smoke,flame</code>；PPE 未戴帽示例：<code>NO-Hardhat</code>（配合 PPE穿戴识别模型）。</p>
            </div>
          </el-form-item>
          <el-form-item label="最低置信度">
            <el-slider v-model="editCfg.min_confidence" :min="0.05" :max="0.95" :step="0.05" show-input />
            <div class="cfg-help">
              <p>仅统计置信度 ≥ 该值的目标。调高可减少误报，调低更灵敏但可能增多虚警。</p>
              <p>建议烟火/PPE：0.30～0.45。</p>
            </div>
          </el-form-item>
        </template>
        <template v-else-if="editForm.ruleType === 'count_threshold'">
          <el-form-item label="统计类别">
            <el-input v-model="editCfg.class_names_text" placeholder="逗号分隔，如 person,人,行人" />
            <div class="cfg-help">
              <p>参与人数统计的类别别名列表。命中任一名称即计入人数（系统还会自动兼容 person/people/human 等常见别名）。</p>
              <p>请使用含 <code>person</code> 的通用检测模型；烟火专用模型通常无法检出人员。</p>
            </div>
          </el-form-item>
          <el-form-item label="人数阈值">
            <el-input-number v-model="editCfg.min_count" :min="1" :max="200" />
            <div class="cfg-help">
              <p>单帧画面中，满足置信度要求的人数 ≥ 该值时，才认为“条件成立”，用于<strong>写告警事件 / 弹窗通知</strong>（还需满足连续帧与冷却）。</p>
              <p>例如设为 8：某一帧至少检出 8 人才可能记一条人员聚集事件。</p>
            </div>
          </el-form-item>
          <el-form-item label="视频叠加阈值">
            <el-input-number v-model="editCfg.video_min_count" :min="1" :max="200" />
            <div class="cfg-help">
              <p>仅影响<strong>视频检测输出画面 / 摄像头中央大图标</strong>的即时显示，不单独写事件。</p>
              <p>可设得比「人数阈值」更低，便于预览时更早看到黄色叠加（例如事件阈值 8、叠加阈值 3）。摄像头实时叠加默认跟随「人数阈值」。</p>
            </div>
          </el-form-item>
          <el-form-item label="最低置信度">
            <el-slider v-model="editCfg.min_confidence" :min="0.05" :max="0.95" :step="0.05" show-input />
            <div class="cfg-help">
              <p>统计人数时忽略置信度低于该值的框，避免把低置信误检算作人员。</p>
              <p>建议聚集：0.20～0.35；画面较糊或人较远时可略降。</p>
            </div>
          </el-form-item>
        </template>
        <template v-else-if="editForm.ruleType === 'line_crossing'">
          <el-form-item label="统计类别">
            <el-input v-model="editCfg.classesText" placeholder="逗号分隔，如 person,人" />
            <div class="cfg-help">
              <p>仅对这些类别的轨迹做越线判定。需检测结果带 <code>trackId</code>（目标追踪页 ByteTrack）。</p>
            </div>
          </el-form-item>
          <el-form-item label="默认警戒线">
            <el-input v-model="editCfg.lineText" placeholder="归一化 x1,y1,x2,y2，如 0.1,0.5,0.9,0.5" />
            <div class="cfg-help">
              <p>四点为画面宽高比例（0～1）。追踪页现场画线会覆盖本默认线。</p>
            </div>
          </el-form-item>
          <el-form-item label="方向">
            <el-radio-group v-model="editCfg.direction">
              <el-radio value="both">双向</el-radio>
              <el-radio value="in">仅进入(+)</el-radio>
              <el-radio value="out">仅离开(-)</el-radio>
            </el-radio-group>
            <div class="cfg-help">
              <p>与追踪页越线计数一致：从线负侧到正侧为进(+1)，反向为出(-1)。</p>
            </div>
          </el-form-item>
          <el-form-item label="最低置信度">
            <el-slider v-model="editCfg.min_confidence" :min="0.05" :max="0.95" :step="0.05" show-input />
          </el-form-item>
        </template>
        <template v-else-if="editForm.ruleType === 'unmatched_face'">
          <el-alert
            type="info"
            :closable="false"
            show-icon
            class="cfg-help-banner"
            title="当人脸识别结果 matched=false（姓名为 unknown）时条件成立。请在「人脸识别」页打开总开关，并在本页启用本规则。"
          />
          <el-form-item label="检测置信度下限">
            <el-slider v-model="editCfg.min_confidence" :min="0" :max="0.95" :step="0.05" show-input />
            <div class="cfg-help">
              <p>可选：过滤检测框置信度过低的人脸（字段 detConfidence）。陌生人匹配分通常很低，一般保持 0。</p>
            </div>
          </el-form-item>
        </template>
        <el-form-item label="连续帧数">
          <el-input-number v-model="editCfg.consecutive_frames" :min="1" :max="30" />
          <div class="cfg-help">
            <p>条件需<strong>连续满足</strong>这么多帧后，才触发一次告警事件/弹窗，用于抑制单帧抖动误报。</p>
            <p>例：设为 3 时，需连续 3 帧都达标才记事件。中央叠加显示不受此限制（满足叠加阈值即画）。</p>
          </div>
        </el-form-item>
        <el-form-item label="冷却(秒)">
          <el-input-number v-model="editCfg.cooldown_sec" :min="0" :max="3600" />
          <div class="cfg-help">
            <p>同一规则、同一检测来源（如某路摄像头）触发后，在冷却时间内不再重复记事件/弹窗。</p>
            <p>设为 0 表示不冷却（测试用）；生产环境建议烟火 20～60 秒、聚集 30～120 秒，避免刷屏。</p>
          </div>
        </el-form-item>

        <el-divider content-position="left">告警文案</el-divider>
        <el-form-item label="标题模板">
          <el-input v-model="editCfg.title_template" placeholder="可用 {count} {minCount} {classes} {name}" />
        </el-form-item>
        <el-form-item label="说明模板">
          <el-input v-model="editCfg.message_template" type="textarea" :rows="2" />
        </el-form-item>

        <el-divider content-position="left">中央叠加样式</el-divider>
        <el-row :gutter="16">
          <el-col :span="14">
            <el-form-item label="启用叠加">
              <el-switch v-model="editOv.enabled" />
            </el-form-item>
            <el-form-item label="填充色">
              <el-color-picker v-model="editOv.fillColor" />
              <el-input v-model="editOv.fillColor" style="width: 120px; margin-left: 8px" />
            </el-form-item>
            <el-form-item label="边框色">
              <el-color-picker v-model="editOv.borderColor" />
              <el-input v-model="editOv.borderColor" style="width: 120px; margin-left: 8px" />
            </el-form-item>
            <el-form-item label="文字色">
              <el-color-picker v-model="editOv.textColor" />
              <el-input v-model="editOv.textColor" style="width: 120px; margin-left: 8px" />
            </el-form-item>
            <el-form-item label="主标题行">
              <el-input
                v-model="editOv.titleLinesText"
                type="textarea"
                :rows="3"
                placeholder="每行一条，如 FIRE"
              />
            </el-form-item>
            <el-form-item label="副标题行">
              <el-input
                v-model="editOv.subtitleLinesText"
                type="textarea"
                :rows="3"
                placeholder="每行一条，如 注意安全"
              />
            </el-form-item>
            <el-form-item label="面板宽度">
              <el-slider v-model="editOv.panelWidthRatio" :min="0.3" :max="0.95" :step="0.01" show-input />
            </el-form-item>
            <el-form-item label="面板高度">
              <el-slider v-model="editOv.panelHeightRatio" :min="0.18" :max="0.8" :step="0.01" show-input />
            </el-form-item>
            <el-form-item label="透明度">
              <el-slider v-model="editOv.opacity" :min="0.15" :max="0.85" :step="0.01" show-input />
            </el-form-item>
            <el-form-item label="警示三角">
              <el-switch v-model="editOv.showTriangle" />
            </el-form-item>
            <el-form-item label="显示优先级">
              <el-input-number v-model="editOv.priority" :min="0" :max="100" />
              <span class="field-tip">数值越小越优先（烟火建议 0，聚集建议 10）</span>
            </el-form-item>
          </el-col>
          <el-col :span="10">
            <div class="preview-label">样式预览</div>
            <div
              class="style-preview"
              :style="{
                background: editOv.fillColor,
                borderColor: editOv.borderColor,
                color: editOv.textColor,
                opacity: editOv.opacity + 0.35,
              }"
            >
              <div v-if="editOv.showTriangle" class="preview-tri" :style="{ borderBottomColor: editOv.triangleFill || '#fff' }" />
              <div v-for="(ln, i) in previewTitleLines" :key="'t' + i" class="preview-title">{{ ln }}</div>
              <div v-for="(ln, i) in previewSubtitleLines" :key="'s' + i" class="preview-sub">{{ ln }}</div>
            </div>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="editDlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { alertApi } from '../../../api/ai'

const activeTab = ref('rules')
const rules = ref([])
const rulesLoading = ref(false)
const togglingId = ref(null)
const events = ref([])
const eventsLoading = ref(false)
const total = ref(0)
const query = reactive({ pageNum: 1, pageSize: 15, status: '' })

const detailDlg = ref(false)
const detailRow = ref(null)
const detailPayload = computed(() => {
  if (!detailRow.value?.payload) return ''
  return JSON.stringify(detailRow.value.payload, null, 2)
})

const editDlg = ref(false)
const saving = ref(false)
const editForm = reactive({
  id: null,
  name: '',
  description: '',
  severity: 'medium',
  status: '1',
  ruleType: '',
  ruleKey: '',
})
const editEnabled = computed({
  get: () => editForm.status === '0',
  set: (v) => { editForm.status = v ? '0' : '1' },
})
const editCfg = reactive({
  classesText: '',
  class_names_text: '',
  lineText: '0.1,0.5,0.9,0.5',
  direction: 'both',
  min_confidence: 0.3,
  min_count: 4,
  video_min_count: 3,
  consecutive_frames: 2,
  cooldown_sec: 30,
  title_template: '',
  message_template: '',
})
const editOv = reactive({
  enabled: true,
  priority: 10,
  fillColor: '#FFD400',
  borderColor: '#E6B800',
  textColor: '#1A1A1A',
  titleLinesText: '',
  subtitleLinesText: '',
  panelWidthRatio: 0.72,
  panelHeightRatio: 0.36,
  opacity: 0.45,
  showTriangle: true,
  triangleFill: '#1A1A1A',
  triangleMark: '#FFFFFF',
})

const splitLines = (text) =>
  String(text || '')
    .replace(/\r/g, '')
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)

const previewTitleLines = computed(() => splitLines(editOv.titleLinesText))
const previewSubtitleLines = computed(() => splitLines(editOv.subtitleLinesText))

const ruleTypeLabel = (t) =>
  ({
    class_presence: '类别出现',
    count_threshold: '数量阈值',
    line_crossing: '越线入侵',
    unmatched_face: '陌生人脸',
  }[t] || t)
const severityLabel = (s) => ({ high: '高', medium: '中', low: '低' }[s] || s)
const severityType = (s) => ({ high: 'danger', medium: 'warning', low: 'info' }[s] || 'info')

const ruleThreshold = (row) => {
  const c = row.config || {}
  if (row.ruleType === 'class_presence') {
    return `类别: ${(c.classes || []).join(' / ')}，≥${((c.min_confidence || 0) * 100).toFixed(0)}%`
  }
  if (row.ruleType === 'count_threshold') {
    const names = c.class_names || [c.class_name || 'person']
    return `${names[0]} ≥ ${c.min_count || 0}（视频≥${c.video_min_count ?? c.min_count ?? 0}）`
  }
  if (row.ruleType === 'line_crossing') {
    const dir = c.direction || 'both'
    const line = Array.isArray(c.line) ? c.line.map((n) => Number(n).toFixed(2)).join(',') : '-'
    return `线[${line}] 方向:${dir}`
  }
  if (row.ruleType === 'unmatched_face') {
    return `未匹配底库 · 连续${c.consecutive_frames ?? 2}帧 · 冷却${c.cooldown_sec ?? 60}s`
  }
  return '-'
}

const fmtTime = (iso) => {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleString()
  } catch (_) {
    return iso
  }
}

const loadRules = async () => {
  rulesLoading.value = true
  try {
    const res = await alertApi.listRules()
    const rows = res.data.rows || []
    // 按 id 升序，序号从 1 连续递增
    rules.value = [...rows].sort((a, b) => (a.id || 0) - (b.id || 0))
  } finally {
    rulesLoading.value = false
  }
}

/** 告警事件列表序号（跨分页连续，从 1 起） */
const eventIndex = (index) => (query.pageNum - 1) * query.pageSize + index + 1

/** 规则表单项开关：启用/停用本条规则（status 0/1） */
const toggleRuleEnabled = async (row, enabled) => {
  const next = enabled ? '0' : '1'
  if (row.status === next) return
  togglingId.value = row.id
  const prev = row.status
  row.status = next
  try {
    await alertApi.updateRule(row.id, { status: next })
    ElMessage.success(enabled ? `已启用「${row.name}」` : `已停用「${row.name}」`)
  } catch (_) {
    row.status = prev
    ElMessage.error('更新规则状态失败')
  } finally {
    togglingId.value = null
  }
}

const loadEvents = async () => {
  eventsLoading.value = true
  try {
    const res = await alertApi.listEvents({
      pageNum: query.pageNum,
      pageSize: query.pageSize,
      status: query.status || undefined,
    })
    events.value = res.data.rows || []
    total.value = res.data.total || 0
  } finally {
    eventsLoading.value = false
  }
}

const showDetail = (row) => {
  detailRow.value = row
  detailDlg.value = true
}

const openEdit = (row) => {
  const c = row.config || {}
  const ov = c.overlay || {}
  editForm.id = row.id
  editForm.name = row.name
  editForm.description = row.description || ''
  editForm.severity = row.severity || 'medium'
  editForm.status = row.status || '1'
  editForm.ruleType = row.ruleType
  editForm.ruleKey = row.ruleKey

  editCfg.classesText = (c.classes || []).join(',')
  editCfg.class_names_text = (c.class_names || [c.class_name || 'person']).join(',')
  editCfg.lineText = Array.isArray(c.line) ? c.line.join(',') : (c.line || '0.1,0.5,0.9,0.5')
  editCfg.direction = c.direction || 'both'
  editCfg.min_confidence = Number(c.min_confidence ?? 0.3)
  editCfg.min_count = Number(c.min_count ?? 4)
  editCfg.video_min_count = Number(c.video_min_count ?? c.min_count ?? 3)
  editCfg.consecutive_frames = Number(c.consecutive_frames ?? (row.ruleType === 'line_crossing' ? 1 : 2))
  editCfg.cooldown_sec = Number(c.cooldown_sec ?? (row.ruleType === 'unmatched_face' ? 60 : 30))
  editCfg.title_template = c.title_template || ''
  editCfg.message_template = c.message_template || ''

  const defaultPri = ({
    'fire-smoke': 0,
    'ppe-no-hardhat': 5,
    'stranger-face': 8,
    'crowd-gathering': 10,
    'line-intrusion': 15,
  })[row.ruleKey] ?? 20
  const defaultFill = ({
    'fire-smoke': '#FF1A1A',
    'ppe-no-hardhat': '#FF7A00',
    'stranger-face': '#409EFF',
    'crowd-gathering': '#FFD400',
    'line-intrusion': '#9254DE',
  })[row.ruleKey] || '#FFD400'
  editOv.enabled = ov.enabled !== false
  editOv.priority = Number(ov.priority ?? defaultPri)
  editOv.fillColor = ov.fillColor || defaultFill
  editOv.borderColor = ov.borderColor || defaultFill
  editOv.textColor = ov.textColor || (row.ruleKey === 'crowd-gathering' ? '#1A1A1A' : '#FFFFFF')
  editOv.titleLinesText = (ov.titleLines || []).join('\n')
  editOv.subtitleLinesText = (ov.subtitleLines || []).join('\n')
  editOv.panelWidthRatio = Number(ov.panelWidthRatio ?? 0.72)
  editOv.panelHeightRatio = Number(ov.panelHeightRatio ?? 0.36)
  editOv.opacity = Number(ov.opacity ?? 0.45)
  editOv.showTriangle = ov.showTriangle !== false
  editOv.triangleFill = ov.triangleFill || '#FFFFFF'
  editOv.triangleMark = ov.triangleMark || '#B00000'

  editDlg.value = true
}

const saveEdit = async () => {
  saving.value = true
  try {
    const config = {
      min_confidence: editCfg.min_confidence,
      consecutive_frames: editCfg.consecutive_frames,
      cooldown_sec: editCfg.cooldown_sec,
      title_template: editCfg.title_template,
      message_template: editCfg.message_template,
      overlay: {
        enabled: editOv.enabled,
        priority: editOv.priority,
        fillColor: editOv.fillColor,
        borderColor: editOv.borderColor,
        textColor: editOv.textColor,
        titleLines: splitLines(editOv.titleLinesText),
        subtitleLines: splitLines(editOv.subtitleLinesText),
        panelWidthRatio: editOv.panelWidthRatio,
        panelHeightRatio: editOv.panelHeightRatio,
        opacity: editOv.opacity,
        showTriangle: editOv.showTriangle,
        triangleFill: editOv.triangleFill,
        triangleMark: editOv.triangleMark,
      },
    }
    if (editForm.ruleType === 'class_presence') {
      config.classes = editCfg.classesText.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
    } else if (editForm.ruleType === 'count_threshold') {
      const names = editCfg.class_names_text.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
      config.class_names = names
      config.class_name = names[0] || 'person'
      config.min_count = editCfg.min_count
      config.video_min_count = editCfg.video_min_count
    } else if (editForm.ruleType === 'line_crossing') {
      config.classes = editCfg.classesText.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
      config.direction = editCfg.direction || 'both'
      const parts = String(editCfg.lineText || '')
        .split(/[,，\s]+/)
        .map((s) => s.trim())
        .filter(Boolean)
        .map(Number)
      if (parts.length === 4 && parts.every((n) => Number.isFinite(n))) {
        config.line = parts
      }
    } else {
      const names = editCfg.class_names_text.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
      config.class_names = names
      config.class_name = names[0] || 'person'
      config.min_count = editCfg.min_count
      config.video_min_count = editCfg.video_min_count
    }
    await alertApi.updateRule(editForm.id, {
      name: editForm.name,
      description: editForm.description,
      severity: editForm.severity,
      status: editForm.status,
      config,
    })
    ElMessage.success('规则已保存')
    editDlg.value = false
    await loadRules()
  } finally {
    saving.value = false
  }
}

const onAck = async (row) => {
  await alertApi.ackEvent(row.id)
  ElMessage.success('已确认')
  await loadEvents()
}

const onRemove = async (row) => {
  await ElMessageBox.confirm(`删除告警「${row.title}」？`, '提示', { type: 'warning' })
  await alertApi.removeEvent(row.id)
  ElMessage.success('已删除')
  await loadEvents()
}

const onTabChange = (name) => {
  if (name === 'rules') loadRules()
  else if (name === 'events') loadEvents()
}

onMounted(async () => {
  await Promise.all([loadRules(), loadEvents()])
})
</script>

<style scoped>
.alert-tabs :deep(.el-tabs__content) {
  padding: 16px;
}
.tab-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  min-height: 32px;
}
.tab-desc {
  font-size: 13px;
  color: #909399;
}
.tab-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}
.hint {
  margin: 12px 0 0;
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
}
.field-tip {
  margin-left: 8px;
  font-size: 12px;
  color: #909399;
}
.cfg-help-banner {
  margin: 0 0 14px;
}
.cfg-help {
  margin-top: 6px;
  padding: 8px 10px;
  background: #f5f7fa;
  border-radius: 6px;
  border-left: 3px solid #409eff;
  line-height: 1.55;
  font-size: 12px;
  color: #606266;
  width: 100%;
}
.cfg-help p {
  margin: 0 0 4px;
}
.cfg-help p:last-child {
  margin-bottom: 0;
}
.cfg-help code {
  padding: 0 4px;
  background: #e8eef7;
  border-radius: 3px;
  color: #3a4a63;
  font-size: 12px;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
.payload {
  margin-top: 12px;
  padding: 10px;
  background: #f5f7fa;
  border-radius: 6px;
  font-size: 12px;
  max-height: 200px;
  overflow: auto;
}
.preview-label {
  font-size: 13px;
  color: #606266;
  margin-bottom: 8px;
}
.style-preview {
  min-height: 220px;
  border: 3px solid;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 16px 12px;
  text-align: center;
}
.preview-tri {
  width: 0;
  height: 0;
  border-left: 16px solid transparent;
  border-right: 16px solid transparent;
  border-bottom: 28px solid #fff;
  margin-bottom: 6px;
}
.preview-title {
  font-size: 18px;
  font-weight: 700;
  line-height: 1.3;
}
.preview-sub {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
}
</style>
