<template>
  <div class="track-scenario-root">
    <el-card shadow="never" class="scenario-card">
      <div class="scenario-header">
        <div class="scenario-title">目标追踪</div>
        <div class="scenario-sub">按任务场景切换工作台：通用追踪 / 车辆追踪（可扩展）</div>
      </div>
      <el-tabs v-model="scenario" class="scenario-tabs" @tab-change="onScenarioChange">
        <el-tab-pane
          v-for="s in TRACK_SCENARIOS"
          :key="s.key"
          :name="s.key"
          :disabled="isScenarioDisabled(s)"
        >
          <template #label>
            <span class="tab-label">
              {{ s.label }}
              <el-tooltip v-if="isScenarioDisabled(s)" :content="`缺少权限 ${s.perm}`" placement="top">
                <span class="tab-lock">（无权限）</span>
              </el-tooltip>
            </span>
          </template>
        </el-tab-pane>
      </el-tabs>
      <p class="scenario-desc">{{ currentDesc }}</p>
    </el-card>

    <el-alert
      v-if="scenario === 'vehicle' && !canUseVehicle"
      type="warning"
      :closable="false"
      show-icon
      title="当前账号无车辆追踪权限（ai:vehicle:list），请联系管理员授权，或切换到「通用追踪」。"
      class="perm-alert"
    />

    <GeneralTrackPanel v-if="scenario === 'general'" />
    <VehicleTrackPanel v-else-if="scenario === 'vehicle' && canUseVehicle" />
  </div>
</template>

<script setup>
import { computed, ref, watch, onMounted, defineAsyncComponent } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '../../../store/user'
import { TRACK_SCENARIOS, DEFAULT_SCENARIO, resolveScenario } from './scenarios'

const GeneralTrackPanel = defineAsyncComponent(() => import('./panels/GeneralTrackPanel.vue'))
const VehicleTrackPanel = defineAsyncComponent(() => import('./panels/VehicleTrackPanel.vue'))

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const scenario = ref(DEFAULT_SCENARIO)

const canUseVehicle = computed(() => userStore.hasPerm('ai:vehicle:list'))

const currentDesc = computed(() => {
  const hit = TRACK_SCENARIOS.find((s) => s.key === scenario.value)
  return hit?.desc || ''
})

const isScenarioDisabled = (s) => {
  if (!s.perm) return false
  return !userStore.hasPerm(s.perm)
}

const syncQuery = (key) => {
  const next = resolveScenario(key)
  if (route.query.scenario === next) return
  router.replace({ path: route.path, query: { ...route.query, scenario: next } })
}

const applyScenarioFromRoute = () => {
  let key = resolveScenario(route.query.scenario)
  if (key === 'vehicle' && !canUseVehicle.value) {
    key = DEFAULT_SCENARIO
  }
  scenario.value = key
  if (route.query.scenario !== key) {
    syncQuery(key)
  }
}

const onScenarioChange = (name) => {
  const s = TRACK_SCENARIOS.find((x) => x.key === name)
  if (s && isScenarioDisabled(s)) {
    scenario.value = DEFAULT_SCENARIO
    syncQuery(DEFAULT_SCENARIO)
    return
  }
  syncQuery(name)
}

onMounted(() => applyScenarioFromRoute())

watch(() => route.query.scenario, () => applyScenarioFromRoute())
watch(canUseVehicle, () => {
  if (scenario.value === 'vehicle' && !canUseVehicle.value) {
    scenario.value = DEFAULT_SCENARIO
    syncQuery(DEFAULT_SCENARIO)
  }
})
</script>

<style scoped>
.track-scenario-root { min-height: 360px; }
.scenario-card { margin-bottom: 12px; }
.scenario-header { margin-bottom: 4px; }
.scenario-title { font-size: 18px; font-weight: 650; color: #2c3e57; }
.scenario-sub { font-size: 13px; color: #7a8aa5; margin-top: 4px; }
.scenario-tabs { margin-top: 8px; }
.scenario-desc { margin: 0; font-size: 13px; color: #5a6b87; }
.tab-label { display: inline-flex; align-items: center; gap: 4px; }
.tab-lock { font-size: 12px; color: #c0c4cc; }
.perm-alert { margin-bottom: 12px; }
</style>
