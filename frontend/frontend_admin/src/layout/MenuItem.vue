<template>
  <el-sub-menu v-if="item.children && item.children.length" :index="fullPath">
    <template #title>
      <el-icon v-if="item.icon"><component :is="item.icon" /></el-icon>
      <span>{{ item.name }}</span>
    </template>
    <MenuItem v-for="child in item.children" :key="child.id" :item="child" :base-path="fullPath" />
  </el-sub-menu>

  <el-menu-item v-else :index="fullPath">
    <el-icon v-if="item.icon"><component :is="item.icon" /></el-icon>
    <template #title>{{ item.name }}</template>
  </el-menu-item>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  item: { type: Object, required: true },
  basePath: { type: String, default: '' }
})

const fullPath = computed(() => {
  const p = props.item.path || ''
  if (p.startsWith('/')) return p
  return `${props.basePath}/${p}`.replace(/\/+/g, '/')
})
</script>
