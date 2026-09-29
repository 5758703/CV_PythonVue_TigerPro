<template>
  <section v-if="guide" class="model-guide" :class="{ collapsed: !expanded }">
    <header class="mg-head" @click="expanded = !expanded">
      <div class="mg-head-main">
        <el-icon class="mg-ico"><InfoFilled /></el-icon>
        <div class="mg-titles">
          <div class="mg-title-row">
            <span class="mg-title">选中模型说明</span>
            <el-tag size="small" effect="dark" type="primary">{{ guide.meta.modelName }}</el-tag>
            <el-tag size="small" effect="plain">{{ taskLabel(guide.meta.task) }}</el-tag>
            <el-tag v-if="guide.meta.library && guide.meta.library !== '—'" size="small" effect="plain">
              {{ guide.meta.library }}
            </el-tag>
          </div>
          <p class="mg-sub">{{ headSummary }}</p>
        </div>
      </div>
      <div class="mg-head-actions" @click.stop>
        <el-button
          v-if="guide.meta.sourceUrl"
          link
          type="primary"
          :icon="Link"
          @click="openSource"
        >
          来源
        </el-button>
        <el-button link type="primary" @click="expanded = !expanded">
          {{ expanded ? '收起' : '展开详情' }}
          <el-icon class="mg-chevron" :class="{ open: expanded }"><ArrowDown /></el-icon>
        </el-button>
      </div>
    </header>

    <div v-show="expanded" class="mg-body">
      <div class="mg-overview">
        <div class="mg-label">模型概述</div>
        <p class="mg-text" v-for="(para, i) in summaryParas" :key="i">{{ para }}</p>
        <div class="mg-meta">
          <span><b>标识</b>{{ guide.meta.modelKey }}</span>
          <span><b>分类</b>{{ guide.meta.category }}</span>
          <span><b>版本</b>{{ guide.meta.version }}</span>
          <span v-if="guide.meta.filePath"><b>权重</b>{{ guide.meta.filePath }}</span>
        </div>
      </div>

      <div class="mg-cols">
        <article class="mg-card scenarios">
          <h4><el-icon><Aim /></el-icon>适用场景</h4>
          <ul>
            <li v-for="(item, i) in guide.scenarios" :key="'s' + i">{{ item }}</li>
          </ul>
        </article>
        <article class="mg-card effects">
          <h4><el-icon><CircleCheck /></el-icon>预期效果</h4>
          <ul>
            <li v-for="(item, i) in guide.effects" :key="'e' + i">{{ item }}</li>
          </ul>
        </article>
        <article class="mg-card tips">
          <h4><el-icon><Warning /></el-icon>使用要点</h4>
          <ul>
            <li v-for="(item, i) in guide.tips" :key="'t' + i">{{ item }}</li>
          </ul>
        </article>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Aim, ArrowDown, CircleCheck, InfoFilled, Link, Warning } from '@element-plus/icons-vue'
import { resolveModelGuide, taskLabel } from '../../../utils/modelGuides'

const props = defineProps({
  model: { type: Object, default: null },
  /** image | video | camera | imgcls | livecls | ocr */
  page: { type: String, default: '' },
  /** 切换模型时是否自动展开 */
  autoExpand: { type: Boolean, default: true },
})

const expanded = ref(true)

const guide = computed(() => resolveModelGuide(props.model, props.page))

const summaryParas = computed(() => {
  const text = guide.value?.summary || ''
  return text.split(/\n+/).map((s) => s.trim()).filter(Boolean)
})

const headSummary = computed(() => {
  const first = summaryParas.value[0] || ''
  return first.length > 96 ? `${first.slice(0, 96)}…` : first
})

watch(
  () => props.model?.id ?? props.model?.modelKey,
  () => {
    if (props.autoExpand && props.model) expanded.value = true
  },
)

function openSource() {
  const url = guide.value?.meta?.sourceUrl
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}
</script>

<style scoped>
.model-guide {
  margin-top: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background:
    linear-gradient(135deg, color-mix(in srgb, var(--el-color-primary) 6%, #fff) 0%, #fff 42%),
    #fff;
  overflow: hidden;
}

.mg-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  cursor: pointer;
  user-select: none;
}

.mg-head:hover {
  background: color-mix(in srgb, var(--el-color-primary) 4%, transparent);
}

.mg-head-main {
  display: flex;
  gap: 10px;
  min-width: 0;
  flex: 1;
}

.mg-ico {
  margin-top: 2px;
  color: var(--el-color-primary);
  font-size: 18px;
  flex: none;
}

.mg-titles {
  min-width: 0;
}

.mg-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.mg-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.mg-sub {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.55;
  color: var(--el-text-color-secondary);
}

.mg-head-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: none;
}

.mg-chevron {
  margin-left: 2px;
  transition: transform 0.2s ease;
}

.mg-chevron.open {
  transform: rotate(180deg);
}

.mg-body {
  padding: 0 14px 14px;
  border-top: 1px dashed var(--el-border-color-lighter);
}

.mg-overview {
  padding-top: 12px;
}

.mg-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--el-color-primary);
  letter-spacing: 0.04em;
  margin-bottom: 6px;
}

.mg-text {
  margin: 0 0 8px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
  white-space: pre-wrap;
}

.mg-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.mg-meta b {
  margin-right: 4px;
  color: var(--el-text-color-primary);
  font-weight: 600;
}

.mg-cols {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.mg-card {
  border-radius: 8px;
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid #eef2f7;
  min-height: 120px;
}

.mg-card.scenarios {
  background: color-mix(in srgb, var(--el-color-primary) 5%, #f8fafc);
}

.mg-card.effects {
  background: color-mix(in srgb, var(--el-color-success) 6%, #f8fafc);
}

.mg-card.tips {
  background: color-mix(in srgb, var(--el-color-warning) 7%, #f8fafc);
}

.mg-card h4 {
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.mg-card ul {
  margin: 0;
  padding-left: 16px;
}

.mg-card li {
  font-size: 12px;
  line-height: 1.65;
  color: var(--el-text-color-regular);
  margin-bottom: 4px;
}

.mg-card li:last-child {
  margin-bottom: 0;
}

@media (max-width: 960px) {
  .mg-cols {
    grid-template-columns: 1fr;
  }

  .mg-head {
    flex-direction: column;
  }
}
</style>
