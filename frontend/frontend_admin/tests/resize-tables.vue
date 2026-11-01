<template>
  <div style="padding: 20px; width: 850px">
    <button id="toggle" @click="visible = !visible">Mount / unmount</button>
    <button id="column" @click="extra = !extra">Dynamic column</button>
    <p>Selected {{ selection }} / sorted {{ sorts }} / row clicks {{ clicks }}</p>
    <el-table v-if="visible" data-testid="regular" :data="rows" :border="false" :allow-drag-last-column="false" @selection-change="selection = $event.length" @sort-change="sorts++" @row-click="clicks++">
      <el-table-column type="selection" width="48" />
      <el-table-column type="index" width="60" />
      <el-table-column prop="name" label="名称" sortable min-width="130" />
      <el-table-column v-if="extra" prop="detail" label="动态列" width="170" />
      <el-table-column label="操作" width="120" fixed="right"><template #default><button>Action</button></template></el-table-column>
    </el-table>
    <el-table data-testid="tree" :data="tree" row-key="id" default-expand-all border style="margin-top: 30px">
      <el-table-column prop="name" label="树形组织" />
      <el-table-column prop="id" label="ID" width="80" />
    </el-table>
    <div style="overflow:auto; margin-top:30px">
      <table data-testid="native" v-resizable-columns style="width:100%;border-collapse:collapse">
        <thead><tr><th>#</th><th>名称</th><th>内容</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.id" @click="clicks++"><td>{{ row.id }}</td><td>{{ row.name }}</td><td>{{ row.detail }}</td></tr></tbody>
      </table>
    </div>
  </div>
</template>
<script setup>
import { ref } from 'vue'
const visible = ref(true), extra = ref(false), selection = ref(0), sorts = ref(0), clicks = ref(0)
const rows = [{ id: 1, name: 'Beta', detail: 'First result' }, { id: 2, name: 'Alpha', detail: 'Second result' }]
const tree = [{ id: 1, name: 'Parent', children: [{ id: 2, name: 'Child' }] }]
window.resizeFixtureState = () => ({ selection: selection.value, sorts: sorts.value, clicks: clicks.value })
</script>
