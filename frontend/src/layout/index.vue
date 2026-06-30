<template>
  <el-container class="layout">
    <el-aside :width="collapse ? '64px' : '220px'" class="aside">
      <div class="logo">
        <div class="logo-badge">CV</div>
        <span v-show="!collapse" class="logo-text">Tiger AI Platform</span>
      </div>
      <el-menu
        :default-active="$route.path"
        :collapse="collapse"
        :show-timeout="0"
        :hide-timeout="0"
        router
        background-color="transparent"
        text-color="#bcd0f5"
        active-text-color="#fff"
        class="side-menu"
      >
        <el-menu-item index="/index">
          <el-icon><HomeFilled /></el-icon>
          <template #title>首页</template>
        </el-menu-item>

        <!-- AI智能识别 / 系统管理 等均由后端菜单(sys_menu)驱动，受权限控制 -->
        <MenuItem v-for="m in store.routers" :key="m.id" :item="m" base-path="" />
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="header-left">
          <el-icon class="collapse-btn" @click="collapse = !collapse"><Fold /></el-icon>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/index' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item v-if="$route.meta.title">{{ $route.meta.title }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <el-dropdown @command="onCommand">
          <span class="user">
            <el-avatar :size="30" class="avatar">{{ store.nickname.charAt(0) }}</el-avatar>
            <span class="uname">{{ store.nickname }}</span>
            <el-tag v-if="store.isAdmin" size="small" type="danger" effect="dark">超管</el-tag>
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="home">首页</el-dropdown-item>
              <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>

      <el-main class="main">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'

import { useUserStore } from '../store/user'
import { logout as logoutApi } from '../api/auth'
import MenuItem from './MenuItem.vue'

const router = useRouter()
const store = useUserStore()
const collapse = ref(false)

const onCommand = async (cmd) => {
  if (cmd === 'home') {
    router.push('/index')
  } else if (cmd === 'logout') {
    await ElMessageBox.confirm('确定退出登录？', '提示', { type: 'warning' })
    try { await logoutApi() } catch (e) { /* ignore */ }
    store.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.layout {
  height: 100vh;
}
.aside {
  background: linear-gradient(180deg, #0c1733 0%, #0a1126 100%);
  border-right: 1px solid rgba(120, 170, 255, 0.12);
  overflow: hidden;
  transition: width 0.28s ease;
  height: 100vh;
  display: flex;
  flex-direction: column;
}
.logo {
  height: 60px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 18px;
  border-bottom: 1px solid rgba(120, 170, 255, 0.12);
}
.logo-badge {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(135deg, #409eff, #6a5acd);
}
.logo-text {
  color: #eaf2ff;
  font-weight: 700;
  font-size: 15px;
  letter-spacing: 0.5px;
  white-space: nowrap;
}
.side-menu {
  border-right: none;
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}
/* 菜单滚动条：暗色细滚动条，不占布局 */
.side-menu::-webkit-scrollbar {
  width: 6px;
}
.side-menu::-webkit-scrollbar-thumb {
  background: rgba(120, 170, 255, 0.25);
  border-radius: 3px;
}
.side-menu::-webkit-scrollbar-thumb:hover {
  background: rgba(120, 170, 255, 0.45);
}
.side-menu::-webkit-scrollbar-track {
  background: transparent;
}
.side-menu :deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(64, 158, 255, 0.25), transparent);
  border-right: 3px solid #409eff;
}
/* 子菜单内联展开/收起：实际走 el-collapse-transition(max-height 动画)，
   默认 var(--el-transition-duration)=0.3s 偏慢，缩短至 0.16s 更跟手 */
.side-menu :deep(.el-collapse-transition-enter-active),
.side-menu :deep(.el-collapse-transition-leave-active) {
  transition-duration: 0.16s !important;
}
/* 菜单项 hover/激活的过渡也压短，点击反馈更即时 */
.side-menu :deep(.el-menu-item),
.side-menu :deep(.el-sub-menu__title) {
  transition: background-color 0.12s, color 0.12s;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #eef1f6;
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.03);
}
.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}
.collapse-btn {
  font-size: 18px;
  cursor: pointer;
  color: #5a6b87;
}
.user {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: #3a4a63;
}
.avatar {
  background: linear-gradient(135deg, #409eff, #6a5acd);
  color: #fff;
}
.main {
  background: #f4f6fb;
  padding: 16px;
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
