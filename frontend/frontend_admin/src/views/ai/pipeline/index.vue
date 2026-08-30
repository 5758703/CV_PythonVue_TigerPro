<template>
  <div class="eva-studio">
    <header class="eva-topbar">
      <div class="eva-topbar-left">
        <div class="eva-brand">EVA</div>
        <div class="eva-title-block">
          <el-input
            v-model="form.name"
            class="eva-name-input"
            placeholder="流水线名称"
          />
          <span class="eva-sub">视频分析流水编排 · Phase {{ graphPhase }}</span>
        </div>
      </div>
      <div class="eva-topbar-actions">
        <el-select v-model="templateId" placeholder="选择模板" style="width: 160px" @change="applyTemplate">
          <el-option v-for="t in templates" :key="t.id" :label="t.name" :value="t.id" />
        </el-select>
        <el-button @click="compDialog = true">
          <el-icon><Plus /></el-icon>添加组件
        </el-button>
        <el-button @click="onValidate">校验</el-button>
        <el-button type="primary" v-permission="'ai:pipeline:edit'" :loading="busy" @click="onSave">
          {{ editId ? '保存新版本' : '保存' }}
        </el-button>
        <el-button @click="$router.push('/ai/pipeline/metrics')">流水线指标</el-button>
      </div>
    </header>

    <el-tabs v-model="mainTab" class="eva-tabs">
      <el-tab-pane label="业务流程" name="flow" />
      <el-tab-pane label="参数配置" name="params" />
      <el-tab-pane label="运行预览" name="run" />
    </el-tabs>

    <div v-show="mainTab === 'flow'" class="eva-body">
      <div
        ref="canvasRef"
        class="eva-canvas"
        @drop="onCanvasDrop"
        @dragover.prevent
        @contextmenu.capture.prevent="onCanvasContextMenu"
      >
        <VueFlow
          id="eva-pipeline"
          v-model:nodes="nodes"
          v-model:edges="edges"
          :node-types="nodeTypes"
          :edge-types="edgeTypes"
          fit-view-on-init
          :default-viewport="{ zoom: 0.9 }"
          :default-edge-options="defaultEdgeOptions"
          :connection-radius="20"
          :elevate-edges-on-select="true"
          @node-click="onNodeClick"
          @pane-click="onPaneClick"
          @edge-click="onEdgeClick"
          @connect="onConnect"
          @node-drag-stop="onNodeDragStop"
        >
          <Background :variant="bgVariant" pattern-color="#c5d4ea" :gap="22" />
          <Controls position="bottom-left" />
        </VueFlow>
        <button type="button" class="eva-fab" @click="compDialog = true" title="添加组件">
          <el-icon :size="22"><Plus /></el-icon>
        </button>
      </div>

      <aside class="eva-rail">
        <div class="rail-hd">
          <span>流水线列表</span>
          <el-button link type="primary" @click="loadList">刷新</el-button>
        </div>
        <div
          v-for="row in rows"
          :key="row.id"
          class="rail-card"
          :class="{ active: editId === row.id }"
          @click="onPick(row)"
        >
          <div class="rail-card-hd">
            <strong>{{ row.name }}</strong>
            <el-tag size="small" type="info">v{{ row.currentVersion }}</el-tag>
          </div>
          <div class="rail-card-meta">#{{ row.id }}</div>
          <div class="rail-card-acts" @click.stop>
            <el-button type="primary" size="small" v-permission="'ai:pipeline:edit'" @click="onStart(row)">
              查看运行
            </el-button>
            <el-button size="small" type="danger" plain v-permission="'ai:pipeline:edit'" @click="onRemove(row)">删除</el-button>
          </div>
        </div>
        <el-empty v-if="!rows.length" description="暂无流水线" :image-size="48" />
      </aside>
    </div>

    <div v-show="mainTab === 'params'" class="eva-params">
      <el-form label-width="110px" size="default" class="params-form">
        <el-form-item label="摄像头 ID">
          <el-input-number v-model="form.cameraId" :min="1" />
        </el-form-item>
        <el-form-item label="Webhook">
          <el-input v-model="form.webhookUrl" placeholder="模板用，可选" />
        </el-form-item>
        <el-form-item label="MQTT Topic">
          <el-input v-model="form.mqttTopic" placeholder="alerts/{site}/{ruleKey}" />
        </el-form-item>
        <el-form-item label="MTMC 相机">
          <el-input v-model="form.cameraIdsText" placeholder="1,2" />
        </el-form-item>
        <el-form-item label="DAG JSON">
          <el-switch v-model="showJson" />
        </el-form-item>
        <el-input v-if="showJson" :model-value="dagJson" type="textarea" :rows="14" class="mono" readonly />
      </el-form>
    </div>

    <div v-show="mainTab === 'run'" class="eva-run">
      <div class="run-toolbar">
        <span v-if="runKey" class="hint">runKey: {{ runKey }}</span>
        <el-button size="small" :disabled="!runKey" @click="goWall">监控墙</el-button>
        <el-button size="small" type="danger" :disabled="!runKey" v-permission="'ai:pipeline:edit'" @click="onStop">
          停止
        </el-button>
      </div>
      <img v-if="runKey" :src="overlaySrc" class="preview" @error="bust++" />
      <el-empty v-else description="从右侧列表启动流水线后显示标注画面" />
      <pre v-if="liveStats" class="stats">{{ liveStats }}</pre>
    </div>

    <!-- 组件管理弹窗 -->
    <el-dialog
      v-model="compDialog"
      title="添加组件"
      width="420px"
      class="eva-comp-dialog"
      align-center
      draggable
      destroy-on-close
      :close-on-click-modal="true"
    >
      <div v-for="group in componentGroups" :key="group.key" class="comp-group">
        <div class="comp-group-hd">{{ group.label }} · {{ group.items.length }}</div>
        <div class="comp-grid">
          <button
            v-for="nt in group.items"
            :key="nt.type"
            type="button"
            class="comp-btn"
            :style="{ borderLeftColor: nt.color || '#409eff' }"
            @click="addComponent(nt.type)"
          >
            <span class="comp-dot" :style="{ background: nt.color || '#409eff' }" />
            <span class="comp-label">{{ nt.label }}</span>
          </button>
        </div>
      </div>
    </el-dialog>

    <!-- 节点编辑抽屉 -->
    <el-drawer
      v-model="drawerOpen"
      :title="`配置 · ${selectedMetaLabel}`"
      size="360px"
      destroy-on-close
    >
      <el-form v-if="selected" label-position="top" size="default">
        <el-form-item v-if="selectedNodeType === 'source.rtsp'" label="cameraId">
          <el-input-number v-model="editConfig.cameraId" :min="1" @change="applyEditConfig" />
        </el-form-item>
        <template v-else-if="selectedNodeType === 'detect.yolo'">
          <el-form-item label="modelKey">
            <el-input v-model="editConfig.modelKey" @change="applyEditConfig" />
          </el-form-item>
          <el-form-item label="conf">
            <el-input-number v-model="editConfig.conf" :min="0.05" :max="0.95" :step="0.05" @change="applyEditConfig" />
          </el-form-item>
          <el-form-item label="sampleFps">
            <el-input-number v-model="editConfig.sampleFps" :min="0.5" :max="15" :step="0.5" @change="applyEditConfig" />
          </el-form-item>
        </template>
        <template v-else-if="selectedNodeType === 'logic.alert'">
          <el-form-item label="ruleIds（空=全部启用）">
            <el-input v-model="ruleIdsText" placeholder="1,2,3" @change="applyRuleIds" />
          </el-form-item>
          <el-form-item label="persist">
            <el-switch v-model="editConfig.persist" @change="applyEditConfig" />
          </el-form-item>
        </template>
        <template v-else-if="selectedNodeType === 'sink.webhook'">
          <el-form-item label="url">
            <el-input v-model="editConfig.url" @change="applyEditConfig" />
          </el-form-item>
          <el-form-item label="secret">
            <el-input v-model="editConfig.secret" placeholder="可选 HMAC" @change="applyEditConfig" />
          </el-form-item>
        </template>
        <template v-else-if="selectedNodeType === 'sink.mqtt'">
          <el-form-item label="topic">
            <el-input v-model="editConfig.topic" placeholder="alerts/{site}/{ruleKey}" @change="applyEditConfig" />
          </el-form-item>
          <el-form-item label="qos">
            <el-input-number v-model="editConfig.qos" :min="0" :max="2" @change="applyEditConfig" />
          </el-form-item>
          <el-form-item label="site">
            <el-input v-model="editConfig.site" placeholder="default" @change="applyEditConfig" />
          </el-form-item>
        </template>
        <template v-else-if="selectedNodeType === 'logic.vlm_gate'">
          <el-form-item label="enabled">
            <el-switch v-model="editConfig.enabled" @change="applyEditConfig" />
          </el-form-item>
          <el-form-item label="timeoutSec">
            <el-input-number v-model="editConfig.timeoutSec" :min="5" :max="60" @change="applyEditConfig" />
          </el-form-item>
          <el-form-item label="useCrop">
            <el-switch v-model="editConfig.useCrop" @change="applyEditConfig" />
          </el-form-item>
          <el-form-item label="onBusy">
            <el-select v-model="editConfig.onBusy" @change="applyEditConfig">
              <el-option label="忙碌时放行" value="pass" />
              <el-option label="忙碌时丢弃" value="drop" />
            </el-select>
          </el-form-item>
          <el-form-item label="prompt">
            <el-input v-model="editConfig.prompt" type="textarea" :rows="3" @change="applyEditConfig" />
          </el-form-item>
        </template>
        <template v-else-if="selectedNodeType === 'composite.mtmc'">
          <el-form-item label="cameraIds">
            <el-input v-model="mtmcCamsText" placeholder="1,2,3" @change="applyMtmcCams" />
          </el-form-item>
          <el-form-item label="persistEvents">
            <el-switch v-model="editConfig.persistEvents" @change="applyEditConfig" />
          </el-form-item>
          <el-form-item label="enablePerson">
            <el-switch v-model="editConfig.enablePerson" @change="applyEditConfig" />
          </el-form-item>
          <el-form-item label="enableVehicle">
            <el-switch v-model="editConfig.enableVehicle" @change="applyEditConfig" />
          </el-form-item>
          <el-form-item label="appearThresh">
            <el-input-number v-model="editConfig.appearThresh" :min="0.2" :max="0.95" :step="0.02" @change="applyEditConfig" />
          </el-form-item>
        </template>
        <el-form-item v-else-if="selectedNodeType === 'track.bytetrack'" label="maxAge">
          <el-input-number v-model="editConfig.maxAge" :min="5" :max="120" @change="applyEditConfig" />
        </el-form-item>
        <el-button type="danger" plain @click="removeSelected">删除节点</el-button>
      </el-form>
    </el-drawer>

    <!-- 画布右键菜单 -->
    <Teleport to="body">
      <div
        v-if="ctxMenu.visible"
        class="eva-ctx-overlay"
        @click="closeCtxMenu"
        @contextmenu.prevent="closeCtxMenu"
      >
        <div
          class="eva-ctx-menu"
          :class="ctxMenu.target === 'pane' ? 'ctx-menu-add' : 'ctx-menu-node'"
          :style="ctxMenuStyle"
          @click.stop
          @contextmenu.prevent
        >
          <!-- 空白画布：仅添加节点 -->
          <template v-if="ctxMenu.target === 'pane'">
            <div class="ctx-section-hd">添加节点</div>
            <div class="ctx-picker">
              <button
                v-for="nt in paletteTypes"
                :key="nt.type"
                type="button"
                class="ctx-picker-item"
                @click="ctxAddComponent(nt.type)"
              >
                <span class="ctx-dot" :style="{ background: nt.color || '#409eff' }" />
                {{ nt.label }}
              </button>
              <div v-if="!paletteTypes.length" class="ctx-empty">加载中…</div>
            </div>
          </template>

          <!-- 节点上：仅编辑 / 删除 -->
          <template v-else>
            <button type="button" class="ctx-item" @click="ctxEditNode">编辑节点</button>
            <button type="button" class="ctx-item ctx-danger" @click="ctxDeleteNode">删除节点</button>
          </template>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, markRaw, nextTick, onBeforeUnmount, onMounted, provide, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { VueFlow, MarkerType, useVueFlow } from '@vue-flow/core'
import { Background, BackgroundVariant } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import { pipelineApi } from '../../../api/pipeline'
import PipelineNode from './PipelineNode.vue'
import PipelineEdge from './PipelineEdge.vue'
import { defaultHandlesForMeta, applyAutoRouteHandles } from './handleGeometry'

const router = useRouter()
const { screenToFlowCoordinate, updateNodeInternals } = useVueFlow({ id: 'eva-pipeline' })
const nodeTypes = { eva: markRaw(PipelineNode) }
const edgeTypes = { eva: markRaw(PipelineEdge) }
const bgVariant = BackgroundVariant.Dots
const defaultEdgeOptions = {
  type: 'eva',
  animated: true,
  selectable: true,
  interactionWidth: 24,
  style: { stroke: '#409eff', strokeWidth: 2.5 },
  markerEnd: { type: MarkerType.ArrowClosed, color: '#409eff' },
}

const rows = ref([])
const templates = ref([])
const templateId = ref('tpl_security_alert')
const nodeTypeMeta = ref([])
const editId = ref(null)
const busy = ref(false)
const runKey = ref('')
const bust = ref(0)
const liveStats = ref('')
const showJson = ref(false)
const selectedId = ref('')
const editConfig = reactive({})
const ruleIdsText = ref('')
const mtmcCamsText = ref('1,2')
const nodes = ref([])
const edges = ref([])
const canvasRef = ref(null)
const mainTab = ref('flow')
const compDialog = ref(false)
const drawerOpen = ref(false)
const ctxMenu = reactive({
  visible: false,
  x: 0,
  y: 0,
  target: 'pane',
  nodeId: '',
  flowPos: { x: 80, y: 160 },
})
let pollTimer = null
let nodeSeq = 1

const form = reactive({
  name: '安防检测告警',
  cameraId: 1,
  webhookUrl: '',
  mqttTopic: '',
  cameraIdsText: '1,2',
})

const paletteTypes = computed(() =>
  (nodeTypeMeta.value || []).filter((t) => (t.phase ?? 0) <= 3),
)

const componentGroups = computed(() => {
  const items = paletteTypes.value
  const buckets = [
    { key: 'in', label: '输入处理', pred: (t) => t.category === 'source' || String(t.type).startsWith('source.') },
    { key: 'algo', label: '算法动作', pred: (t) => ['detect', 'track', 'composite'].includes(t.category) || /^(detect|track|composite)\./.test(t.type) },
    { key: 'biz', label: '业务处理', pred: (t) => t.category === 'logic' || String(t.type).startsWith('logic.') },
    { key: 'out', label: '告警输出', pred: (t) => t.category === 'sink' || String(t.type).startsWith('sink.') },
  ]
  return buckets
    .map((b) => ({ ...b, items: items.filter(b.pred) }))
    .filter((b) => b.items.length)
})

const graphPhase = computed(() => {
  let p = 0
  for (const n of nodes.value) {
    const meta = metaOf(n.data?.nodeType)
    p = Math.max(p, Number(meta.phase || 0))
  }
  return Math.max(1, p)
})

const selected = computed(() => nodes.value.find((n) => n.id === selectedId.value) || null)
const selectedNodeType = computed(() => selected.value?.data?.nodeType || '')
const selectedMetaLabel = computed(() => metaOf(selectedNodeType.value).label || selectedNodeType.value)

const dagJson = computed(() => JSON.stringify(graphToDag(), null, 2))

const overlaySrc = computed(() => {
  if (!runKey.value) return ''
  return pipelineApi.overlayUrl(runKey.value, bust.value)
})

const ctxMenuStyle = computed(() => {
  const pad = 8
  const isPane = ctxMenu.target === 'pane'
  const menuW = isPane ? 176 : 132
  const menuH = isPane ? 168 : 76
  let x = ctxMenu.x
  let y = ctxMenu.y
  if (typeof window !== 'undefined') {
    x = Math.min(x, window.innerWidth - menuW - pad)
    y = Math.min(y, window.innerHeight - menuH - pad)
  }
  return { left: `${x}px`, top: `${y}px` }
})

const metaOf = (type) => (nodeTypeMeta.value || []).find((t) => t.type === type) || { label: type, color: '#409eff' }

function defaultConfig(type) {
  if (type === 'source.rtsp') return { cameraId: form.cameraId }
  if (type === 'detect.yolo') return { modelKey: 'yolo26n', conf: 0.35, sampleFps: 4 }
  if (type === 'track.bytetrack') return { maxAge: 30 }
  if (type === 'logic.alert') return { ruleIds: [], persist: true }
  if (type === 'logic.vlm_gate') {
    return {
      enabled: true,
      timeoutSec: 12,
      useCrop: true,
      onBusy: 'pass',
      onFail: 'pass',
      prompt: '请判断是否为真实安防告警。仅返回 JSON：{"confirm": true|false, "reason": "..."}',
    }
  }
  if (type === 'composite.mtmc') {
    const cams = String(form.cameraIdsText || '1,2')
      .split(',')
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isFinite(n) && n > 0)
    return {
      cameraIds: cams.length >= 2 ? cams : [1, 2],
      enablePerson: true,
      enableVehicle: true,
      persistEvents: true,
      ownSession: true,
      sampleFps: 4,
      appearThresh: 0.48,
    }
  }
  if (type === 'sink.webhook') return { url: form.webhookUrl || '', event: 'alert.fired', secret: '' }
  if (type === 'sink.mqtt') {
    return {
      topic: form.mqttTopic || 'alerts/{site}/{ruleKey}',
      qos: 1,
      event: 'alert.fired',
      site: 'default',
    }
  }
  if (type === 'sink.overlay') return { drawRegion: false }
  return {}
}

function makeFlowNode(id, type, config = {}, position = { x: 80, y: 160 }, extra = {}) {
  const meta = metaOf(type)
  const cfg = { ...defaultConfig(type), ...config }
  return {
    id,
    type: 'eva',
    position,
    data: {
      nodeType: type,
      config: cfg,
      color: meta.color || '#409eff',
      label: meta.label || type,
      portsIn: meta.portsIn || [],
      portsOut: meta.portsOut || [],
      handles: extra.handles || defaultHandlesForMeta(meta),
    },
  }
}

function graphToDag() {
  return {
    id: editId.value ? `pipeline_${editId.value}` : 'draft',
    version: 1,
    name: form.name,
    nodes: nodes.value.map((n) => ({
      id: n.id,
      type: n.data.nodeType,
      config: { ...(n.data.config || {}) },
      position: { x: n.position.x, y: n.position.y },
      handles: n.data.handles,
    })),
    edges: edges.value.map((e) => {
      const bend = e.data?.bend
      if (!bend) return [e.source, e.target]
      return {
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle || 'source',
        targetHandle: e.targetHandle || 'target',
        bend,
      }
    }),
  }
}

function dagToGraph(dag) {
  nodes.value = (dag.nodes || []).map((n, i) =>
    makeFlowNode(
      n.id,
      n.type,
      n.config || {},
      n.position || { x: 48 + i * 200, y: 180 },
      { handles: n.handles },
    ),
  )
  edges.value = (dag.edges || []).map((e, i) => {
    const pair = Array.isArray(e) ? e : [e.from || e.source, e.to || e.target]
    const [s, t] = pair
    const edgeData = !Array.isArray(e) && e.bend ? { bend: e.bend } : {}
    return {
      id: `e_${s}_${t}_${i}`,
      type: 'eva',
      source: s,
      target: t,
      sourceHandle: Array.isArray(e) ? 'source' : (e.sourceHandle || 'source'),
      targetHandle: Array.isArray(e) ? 'target' : (e.targetHandle || 'target'),
      data: edgeData,
      ...defaultEdgeOptions,
    }
  })
  selectedId.value = ''
  drawerOpen.value = false
  const src = nodes.value.find((n) => n.data.nodeType === 'source.rtsp')
  if (src?.data?.config?.cameraId) form.cameraId = src.data.config.cameraId
  if (dag.name) form.name = dag.name
  // 按相对位置自动排布连接点（阶梯布局：下→左 / 右→上）
  nextTick(() => autoRouteAllEdges())
}

function autoRouteAllEdges() {
  if (!nodes.value.length || !edges.value.length) return
  // 仅自动更新仍为 auto 的连接点；手动拖过的端点保留
  const routed = applyAutoRouteHandles(nodes.value, edges.value)
  nodes.value = nodes.value.map((n, i) => {
    const r = routed[i]
    if (!r) return n
    const prev = n.data?.handles || {}
    const next = { ...r.data.handles }
    if (prev.source?.auto === false) next.source = prev.source
    if (prev.target?.auto === false) next.target = prev.target
    return { ...n, data: { ...n.data, handles: next } }
  })
}

function onNodeDragStop() {
  autoRouteAllEdges()
}

function syncCameraIntoGraph() {
  nodes.value = nodes.value.map((n) => {
    if (n.data.nodeType !== 'source.rtsp') return n
    return {
      ...n,
      data: { ...n.data, config: { ...n.data.config, cameraId: form.cameraId } },
    }
  })
}

function applyEditConfig() {
  if (!selectedId.value) return
  nodes.value = nodes.value.map((n) => {
    if (n.id !== selectedId.value) return n
    return { ...n, data: { ...n.data, config: { ...editConfig } } }
  })
}

function applyRuleIds() {
  editConfig.ruleIds = String(ruleIdsText.value || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .map(Number)
  applyEditConfig()
}

function applyMtmcCams() {
  editConfig.cameraIds = String(mtmcCamsText.value || '')
    .split(',')
    .map((s) => Number(s.trim()))
    .filter((n) => Number.isFinite(n) && n > 0)
  applyEditConfig()
}

function onCanvasDrop(ev) {
  const type = ev.dataTransfer.getData('application/vueflow')
  if (!type || !canvasRef.value) return
  const bounds = canvasRef.value.getBoundingClientRect()
  const position = { x: ev.clientX - bounds.left - 40, y: ev.clientY - bounds.top - 20 }
  addNodeAt(type, position)
}

function addComponent(type) {
  const n = nodes.value.length
  addNodeAt(type, { x: 60 + (n % 4) * 200, y: 140 + Math.floor(n / 4) * 120 })
  compDialog.value = false
}

function addNodeAt(type, position) {
  const id = `n_${type.split('.').pop()}_${nodeSeq++}`
  nodes.value = [...nodes.value, makeFlowNode(id, type, defaultConfig(type), position)]
}

function patchNodeHandle(nodeId, role, handle) {
  nodes.value = nodes.value.map((n) => {
    if (n.id !== nodeId) return n
    return {
      ...n,
      data: {
        ...n.data,
        handles: {
          ...(n.data.handles || {}),
          [role]: { ...handle, auto: false },
        },
      },
    }
  })
  // Handle 的 CSS 位置改变后，显式刷新 Vue Flow 缓存的端口坐标，
  // 否则连线端点可能要等到下一次节点移动才会跟上。
  nextTick(() => updateNodeInternals([nodeId]))
}

provide('patchNodeHandle', patchNodeHandle)

function patchEdgeBend(edgeId, bend) {
  edges.value = edges.value.map((e) => {
    if (e.id !== edgeId) return e
    const prev = { ...(e.data?.bend || {}) }
    const next = { ...prev }
    if ('centerX' in bend) {
      if (Number.isFinite(bend.centerX)) next.centerX = bend.centerX
      else delete next.centerX
    }
    if ('centerY' in bend) {
      if (Number.isFinite(bend.centerY)) next.centerY = bend.centerY
      else delete next.centerY
    }
    const hasBend = Number.isFinite(next.centerX) || Number.isFinite(next.centerY)
    return {
      ...e,
      data: {
        ...(e.data || {}),
        bend: hasBend ? next : undefined,
      },
    }
  })
}

provide('patchEdgeBend', patchEdgeBend)
provide('getFlowNode', (id) => nodes.value.find((n) => n.id === id))

function onEdgeClick() {
  // 保持连线可交互，避免 vue-flow 将 edge 标记为 inactive
}

function onConnect(params) {
  const id = `e_${params.source}_${params.target}_${Date.now()}`
  edges.value = [...edges.value, {
    ...params,
    id,
    type: 'eva',
    sourceHandle: params.sourceHandle || 'source',
    targetHandle: params.targetHandle || 'target',
    ...defaultEdgeOptions,
  }]
  nextTick(() => autoRouteAllEdges())
}

function selectNode(node) {
  selectedId.value = node.id
  Object.keys(editConfig).forEach((k) => delete editConfig[k])
  Object.assign(editConfig, { ...(node.data?.config || {}) })
  ruleIdsText.value = (editConfig.ruleIds || []).join(',')
  mtmcCamsText.value = (editConfig.cameraIds || []).join(',')
}

function onNodeClick({ node }) {
  selectNode(node)
  drawerOpen.value = false
}

function onPaneClick() {
  closeCtxMenu()
  selectedId.value = ''
  drawerOpen.value = false
}

function flowPosFromEvent(event) {
  try {
    return screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  } catch (_) {
    if (!canvasRef.value) return { x: 80, y: 160 }
    const bounds = canvasRef.value.getBoundingClientRect()
    return { x: event.clientX - bounds.left, y: event.clientY - bounds.top }
  }
}

function openCtxMenu(event, target, nodeId = '') {
  ctxMenu.visible = true
  ctxMenu.target = target
  ctxMenu.nodeId = nodeId
  ctxMenu.x = event.clientX
  ctxMenu.y = event.clientY
  ctxMenu.flowPos = flowPosFromEvent(event)
}

function closeCtxMenu() {
  ctxMenu.visible = false
}

function onCanvasContextMenu(event) {
  const nodeWrap = event.target?.closest?.('.vue-flow__node')
  if (nodeWrap) {
    const nodeId = nodeWrap.getAttribute('data-id')
    const node = nodes.value.find((n) => n.id === nodeId)
    if (node) {
      selectNode(node)
      openCtxMenu(event, 'node', node.id)
      return
    }
  }
  if (selectedId.value) {
    openCtxMenu(event, 'node', selectedId.value)
    return
  }
  openCtxMenu(event, 'pane')
}

function ctxAddComponent(type) {
  addNodeAt(type, { ...ctxMenu.flowPos })
  closeCtxMenu()
}

function ctxEditNode() {
  if (!ctxMenu.nodeId) return
  const node = nodes.value.find((n) => n.id === ctxMenu.nodeId)
  if (node) selectNode(node)
  drawerOpen.value = true
  closeCtxMenu()
}

function ctxDeleteNode() {
  if (!ctxMenu.nodeId) return
  removeNode(ctxMenu.nodeId)
  closeCtxMenu()
}

function removeNode(id) {
  nodes.value = nodes.value.filter((n) => n.id !== id)
  edges.value = edges.value.filter((e) => e.source !== id && e.target !== id)
  if (selectedId.value === id) {
    selectedId.value = ''
    drawerOpen.value = false
  }
}

function removeSelected() {
  if (!selectedId.value) return
  removeNode(selectedId.value)
}

async function applyTemplate() {
  const params = {
    cameraId: form.cameraId,
    webhookUrl: form.webhookUrl || undefined,
    mqttTopic: form.mqttTopic || undefined,
  }
  if (templateId.value === 'tpl_mtmc_composite') {
    params.cameraIds = form.cameraIdsText || '1,2'
  }
  const res = await pipelineApi.getTemplate(templateId.value, params)
  dagToGraph(res.data)
  ElMessage.success('已加载模板')
}

async function onValidate() {
  try {
    syncCameraIntoGraph()
    await pipelineApi.validate({ dag: graphToDag(), phase: graphPhase.value })
    ElMessage.success(`DAG 校验通过（Phase ${graphPhase.value}）`)
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e.message || '校验失败')
  }
}

async function loadList() {
  const res = await pipelineApi.list({ pageNum: 1, pageSize: 50 })
  rows.value = res.data.rows || []
}

async function onPick(row) {
  editId.value = row.id
  const res = await pipelineApi.get(row.id)
  form.name = res.data.name
  dagToGraph(res.data.dag || {})
  mainTab.value = 'flow'
}

async function onSave() {
  busy.value = true
  try {
    syncCameraIntoGraph()
    const dag = graphToDag()
    await pipelineApi.validate({ dag, phase: graphPhase.value })
    if (editId.value) {
      await pipelineApi.update(editId.value, { name: form.name, dag, phase: graphPhase.value })
      ElMessage.success('已保存新版本')
    } else {
      const res = await pipelineApi.create({ name: form.name, dag, phase: graphPhase.value })
      editId.value = res.data.id
      ElMessage.success('已创建')
    }
    await loadList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e.message || '保存失败')
  } finally {
    busy.value = false
  }
}

async function onStart(row) {
  try {
    const res = await pipelineApi.start(row.id)
    runKey.value = res.data.runKey
    bust.value = Date.now()
    localStorage.setItem('pipeline-run-key', runKey.value)
    localStorage.setItem('pipeline-camera-id', String(res.data.cameraId || form.cameraId))
    ElMessage.success('已启动')
    mainTab.value = 'run'
    await refreshLive()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '启动失败')
  }
}

async function onStop() {
  if (!runKey.value) return
  await pipelineApi.stopRun(runKey.value)
  ElMessage.success('已停止')
  runKey.value = ''
  liveStats.value = ''
}

async function onRemove(row) {
  await ElMessageBox.confirm(`删除流水线 #${row.id}？`, '确认', { type: 'warning' })
  await pipelineApi.remove(row.id)
  if (editId.value === row.id) editId.value = null
  ElMessage.success('已删除')
  await loadList()
}

function goWall() {
  const cam = localStorage.getItem('pipeline-camera-id') || form.cameraId
  router.push({ path: '/camera/wall', query: { ai: 'pipeline', cameraId: cam } })
}

async function refreshLive() {
  if (!runKey.value) return
  try {
    const res = await pipelineApi.getRun(runKey.value)
    const live = res.data.live
    liveStats.value = live ? JSON.stringify({ stats: live.stats, lastEvents: live.lastEvents }, null, 2) : ''
  } catch (_) { /* ignore */ }
}

watch(() => form.cameraId, () => syncCameraIntoGraph())

function onCtxKeydown(ev) {
  if (ev.key === 'Escape') closeCtxMenu()
}

onMounted(async () => {
  const nt = await pipelineApi.nodeTypes()
  nodeTypeMeta.value = nt.data.rows || []
  const tpl = await pipelineApi.templates()
  templates.value = tpl.data.rows || []
  await applyTemplate()
  await loadList()
  pollTimer = setInterval(refreshLive, 2000)
  window.addEventListener('keydown', onCtxKeydown)
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  window.removeEventListener('keydown', onCtxKeydown)
})
</script>

<style scoped>
.eva-studio {
  --eva-blue: #409eff;
  --eva-blue-deep: #2f6fed;
  --eva-ink: #303133;
  --eva-muted: #909399;
  --eva-line: #e4eaf3;
  --eva-bg: #f3f6fb;
  height: calc(100vh - 108px);
  min-height: 560px;
  display: flex;
  flex-direction: column;
  margin: -4px;
  background: var(--eva-bg);
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}
.eva-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px 16px;
  background: #fff;
  border-bottom: 1px solid var(--eva-line);
}
.eva-topbar-left { display: flex; align-items: center; gap: 12px; min-width: 0; }
.eva-brand {
  width: 42px; height: 42px; border-radius: 12px;
  background: linear-gradient(145deg, var(--eva-blue), var(--eva-blue-deep));
  color: #fff; font-weight: 800; font-size: 13px;
  display: flex; align-items: center; justify-content: center;
  letter-spacing: 0.04em;
  box-shadow: 0 6px 16px rgba(64, 158, 255, 0.35);
}
.eva-title-block { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.eva-name-input :deep(.el-input__wrapper) {
  box-shadow: none !important;
  background: transparent;
  padding-left: 0;
}
.eva-name-input :deep(.el-input__inner) {
  font-size: 18px;
  font-weight: 700;
  color: var(--eva-ink);
}
.eva-sub { font-size: 12px; color: var(--eva-muted); }
.eva-topbar-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.eva-tabs {
  background: #fff;
  padding: 0 16px;
  border-bottom: 1px solid var(--eva-line);
}
.eva-tabs :deep(.el-tabs__header) { margin: 0; }
.eva-tabs :deep(.el-tabs__nav-wrap::after) { display: none; }
.eva-tabs :deep(.el-tabs__item.is-active) { color: var(--eva-blue); font-weight: 600; }
.eva-tabs :deep(.el-tabs__active-bar) { background: var(--eva-blue); }

.eva-body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 1fr 280px;
  gap: 0;
}
.eva-canvas {
  position: relative;
  min-height: 0;
  background:
    radial-gradient(circle at 12% 18%, rgba(64, 158, 255, 0.08), transparent 42%),
    #eef3fa;
  user-select: none;
}
.eva-canvas :deep(.vue-flow) { width: 100%; height: 100%; }
.eva-canvas :deep(.vue-flow__pane),
.eva-canvas :deep(.vue-flow__viewport),
.eva-canvas :deep(.vue-flow__background) {
  cursor: default;
}
.eva-canvas :deep(.vue-flow__node) {
  cursor: default;
}
.eva-canvas :deep(.vue-flow__node.selected),
.eva-canvas :deep(.vue-flow__node.selected.draggable),
.eva-canvas :deep(.vue-flow__node.selected .eva-node),
.eva-canvas :deep(.vue-flow__node.selected .eva-node *) {
  cursor: move !important;
}
.eva-canvas :deep(.vue-flow__node.selected.dragging),
.eva-canvas :deep(.vue-flow__node.selected.draggable.dragging) {
  cursor: move !important;
}
.eva-canvas :deep(.vue-flow__node.selected .eva-handle-ghost) {
  cursor: crosshair !important;
}
.eva-canvas :deep(.vue-flow__edge.eva) {
  pointer-events: all !important;
}
.eva-canvas :deep(.vue-flow__edge.eva.inactive) {
  pointer-events: all !important;
}
.eva-canvas :deep(.vue-flow__edge-interaction),
.eva-canvas :deep(.eva-edge-hit) {
  pointer-events: stroke !important;
  cursor: move !important;
}
.eva-canvas :deep(.eva-edge-joint),
.eva-canvas :deep(.eva-edge-joint-hit) {
  pointer-events: all !important;
  cursor: move !important;
}
.eva-canvas :deep(.vue-flow__edge.animated .vue-flow__edge-path) {
  stroke-dasharray: 8 6;
  animation: eva-edge-flow 0.55s linear infinite;
}
@keyframes eva-edge-flow {
  to { stroke-dashoffset: -14; }
}
.eva-fab {
  position: absolute;
  right: 18px;
  bottom: 18px;
  width: 48px;
  height: 48px;
  border: none;
  border-radius: 50%;
  background: var(--eva-blue);
  color: #fff;
  cursor: pointer;
  box-shadow: 0 8px 20px rgba(64, 158, 255, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 5;
}
.eva-fab:hover { filter: brightness(1.05); }

.eva-rail {
  background: #fff;
  border-left: 1px solid var(--eva-line);
  overflow: auto;
  padding: 12px;
}
.rail-hd {
  display: flex; justify-content: space-between; align-items: center;
  font-weight: 650; color: var(--eva-ink); margin-bottom: 10px;
}
.rail-card {
  border: 1px solid var(--eva-line);
  border-radius: 12px;
  padding: 12px;
  margin-bottom: 10px;
  cursor: pointer;
  background: #fafcff;
  transition: border-color .15s, box-shadow .15s;
}
.rail-card:hover, .rail-card.active {
  border-color: var(--eva-blue);
  box-shadow: 0 4px 14px rgba(64, 158, 255, 0.12);
}
.rail-card-hd { display: flex; justify-content: space-between; gap: 8px; align-items: center; }
.rail-card-meta { margin-top: 4px; font-size: 12px; color: var(--eva-muted); }
.rail-card-acts { margin-top: 10px; display: flex; gap: 6px; }

.eva-params, .eva-run {
  flex: 1;
  overflow: auto;
  padding: 16px 20px;
  background: #fff;
}
.params-form { max-width: 640px; }
.run-toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }
.hint { color: var(--eva-muted); font-size: 12px; margin-right: auto; }
.preview {
  width: 100%; max-height: 420px; object-fit: contain; background: #111; border-radius: 8px;
}
.stats {
  margin-top: 10px; font-size: 11px; background: #f6f8fa; padding: 10px;
  border-radius: 8px; max-height: 220px; overflow: auto;
}
.mono :deep(textarea) { font-family: ui-monospace, Consolas, monospace; font-size: 12px; }

.comp-group { margin-bottom: 10px; }
.comp-group:last-child { margin-bottom: 0; }
.comp-group-hd {
  font-weight: 600;
  font-size: 12px;
  color: var(--eva-muted);
  margin-bottom: 6px;
  padding-bottom: 4px;
  border-bottom: 1px dashed var(--eva-line);
}
.comp-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}
.comp-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  text-align: left;
  border: 1px solid var(--eva-line);
  border-left-width: 3px;
  border-radius: 6px;
  background: #fff;
  padding: 6px 8px;
  min-height: 32px;
  cursor: pointer;
  font-size: 12px;
  line-height: 1.25;
  color: var(--eva-ink);
  transition: background .12s, border-color .12s;
}
.comp-btn:hover {
  background: #f0f7ff;
  border-color: var(--eva-blue);
}
.comp-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.comp-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 960px) {
  .eva-body { grid-template-columns: 1fr; }
  .eva-rail { border-left: none; border-top: 1px solid var(--eva-line); max-height: 240px; }
  .eva-canvas { min-height: 420px; }
}

.eva-ctx-overlay {
  position: fixed;
  inset: 0;
  z-index: 3000;
}
.eva-ctx-menu {
  position: fixed;
  background: #fff;
  border: 1px solid var(--eva-line);
  border-radius: 6px;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.1);
  padding: 2px 0;
  font-size: 12px;
}
.eva-ctx-menu.ctx-menu-add {
  min-width: 176px;
}
.eva-ctx-menu.ctx-menu-node {
  min-width: 132px;
}
.ctx-section-hd {
  padding: 5px 10px 3px;
  font-size: 11px;
  font-weight: 600;
  color: var(--eva-muted);
}
.ctx-item {
  display: block;
  width: 100%;
  border: none;
  background: transparent;
  padding: 7px 10px;
  text-align: left;
  color: var(--eva-ink);
  cursor: pointer;
  font-size: 12px;
  line-height: 1.2;
}
.ctx-item:hover {
  background: #f0f7ff;
  color: var(--eva-blue);
}
.ctx-danger { color: #f56c6c; }
.ctx-danger:hover { background: #fef0f0; color: #f56c6c; }
.ctx-picker {
  max-height: min(140px, 25vh);
  overflow-y: auto;
  overflow-x: hidden;
  padding: 0 2px 4px;
}
.ctx-picker-item {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  border: none;
  background: transparent;
  padding: 4px 8px;
  text-align: left;
  font-size: 11px;
  color: var(--eva-ink);
  cursor: pointer;
  border-radius: 4px;
  line-height: 1.25;
}
.ctx-picker-item:hover {
  background: #f0f7ff;
  color: var(--eva-blue);
}
.ctx-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  flex-shrink: 0;
}
.ctx-empty {
  padding: 8px 10px;
  font-size: 11px;
  color: var(--eva-muted);
  text-align: center;
}
</style>

<style>
/* 弹窗紧凑：挂到 body，需非 scoped */
.eva-comp-dialog.el-dialog {
  border-radius: 10px;
  margin-top: 12vh !important;
}
.eva-comp-dialog .el-dialog__header {
  padding: 12px 14px 8px;
  margin-right: 0;
  cursor: move;
  user-select: none;
}
.eva-comp-dialog .el-dialog__title {
  font-size: 15px;
  font-weight: 650;
}
.eva-comp-dialog .el-dialog__headerbtn {
  top: 12px;
  right: 12px;
}
.eva-comp-dialog .el-dialog__body {
  padding: 4px 14px 14px;
  max-height: min(52vh, 420px);
  overflow: auto;
}
</style>
