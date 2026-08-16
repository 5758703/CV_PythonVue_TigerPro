<template>
  <div class="redirect-hint">正在跳转到目标追踪 · 车辆场景…</div>
</template>

<script setup>
/**
 * 兼容旧入口：独立「车辆追踪」页已并入「目标追踪」场景。
 * 路由层也会 redirect；本文件保留给可能的动态菜单 component 引用。
 */
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
onMounted(() => {
  router.replace({ path: '/ai/track', query: { scenario: 'vehicle' } })
})
</script>

<style scoped>
.redirect-hint {
  padding: 48px 16px;
  text-align: center;
  color: #8aa0c8;
}
</style>
