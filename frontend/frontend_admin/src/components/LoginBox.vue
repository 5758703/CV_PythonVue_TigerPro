<template>
  <div class="login-box-track" :class="{ 'is-in': visible }">
    <section class="login-box" :class="{ shake: shaking }" aria-labelledby="login-box-title">
      <header class="box-head">
        <p class="box-eyebrow">控制台登录</p>
        <h2 id="login-box-title" class="box-title">欢迎回来</h2>
        <p class="box-desc">登录后进入模型管理、在线推理与训练任务工作台</p>
      </header>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        class="login-form"
        label-position="top"
        @submit.prevent="onSubmit"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="form.username"
            placeholder="请输入用户名"
            autocomplete="username"
            :prefix-icon="User"
            class="platform-input"
          />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            autocomplete="current-password"
            show-password
            :prefix-icon="Lock"
            class="platform-input"
            @keyup.enter="onSubmit"
          />
        </el-form-item>

        <button class="submit-btn" type="submit" :disabled="loading">
          <span v-if="!loading" class="btn-label">登录</span>
          <span v-else class="btn-spinner" aria-hidden="true" />
          <span v-if="loading" class="sr-only">登录中</span>
        </button>
      </el-form>

      <div class="box-meta">
        <span>没有账号？</span>
        <router-link to="/register" class="link">注册新账号</router-link>
      </div>

      <div class="box-tip">
        <span class="tip-label">演示账号</span>
        <button type="button" class="tip-key" @click="fill('admin', 'admin123')">admin / admin123</button>
        <button type="button" class="tip-key" @click="fill('tiger', '123456')">tiger / 123456</button>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'

import { login } from '../api/auth'
import { useUserStore } from '../store/user'

defineProps({
  visible: { type: Boolean, default: false },
})

const router = useRouter()
const route = useRoute()
const store = useUserStore()

/** 门户深链：仅允许站内相对路径（可含 query），防止开放重定向 */
function safeRedirect(raw) {
  const value = Array.isArray(raw) ? raw[0] : raw
  if (typeof value !== 'string') return '/index'
  let path = value.trim()
  try {
    path = decodeURIComponent(path)
  } catch {
    /* keep raw */
  }
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('://')) return '/index'
  return path
}

const formRef = ref(null)
const loading = ref(false)
const shaking = ref(false)

const form = reactive({ username: 'admin', password: 'admin123' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

function fill(username, password) {
  form.username = username
  form.password = password
}

async function onSubmit() {
  if (loading.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  loading.value = true
  try {
    const res = await login(form)
    store.setToken(res.data.token)
    await store.loadInfo()
    ElMessage.success('登录成功')
    router.push(safeRedirect(route.query.redirect))
  } catch {
    shaking.value = true
    setTimeout(() => (shaking.value = false), 600)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-box-track,
.login-box-track *,
.login-box-track *::before,
.login-box-track *::after {
  box-sizing: border-box;
}

.login-box-track {
  width: 100%;
  max-width: 400px;
  opacity: 0;
  transform: translateX(calc(-100% - 48px));
  transition:
    transform 0.9s cubic-bezier(0.16, 1, 0.3, 1),
    opacity 0.6s ease;
  pointer-events: none;
}
.login-box-track.is-in {
  opacity: 1;
  transform: translateX(0);
  pointer-events: auto;
}

.login-box {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 450px;
  padding: 28px 28px 22px;
  border: 1px solid var(--border, rgba(141, 163, 184, 0.16));
  border-radius: 16px;
  background: linear-gradient(
    180deg,
    var(--bg-elevated, rgba(23, 42, 64, 0.92)),
    var(--bg-elevated-2, rgba(16, 30, 47, 0.92))
  );
  box-shadow: var(--shadow, 0 24px 60px rgba(0, 0, 0, 0.35));
  color: var(--text, #e8f1f8);
  overflow: hidden;
  backdrop-filter: blur(12px);
  transition:
    background 0.35s ease,
    border-color 0.35s ease,
    color 0.35s ease,
    box-shadow 0.35s ease;
}
.login-box::before {
  content: '';
  position: absolute;
  left: 0;
  top: 28px;
  bottom: 28px;
  width: 2px;
  border-radius: 2px;
  background: linear-gradient(180deg, transparent, var(--accent, #34d1cf), transparent);
  opacity: 0.7;
}
.login-box.shake { animation: shake 0.5s cubic-bezier(0.36, 0.07, 0.19, 0.97); }

.box-head { margin-bottom: 18px; }
.box-eyebrow {
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 2px;
  color: var(--accent, #34d1cf);
}
.box-title {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  line-height: 1.2;
  color: var(--text-strong, #fff);
}
.box-desc {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-muted, #8da3b8);
}

.login-form :deep(.el-form-item) { margin-bottom: 16px; }
.login-form :deep(.el-form-item__label) {
  padding-bottom: 6px;
  font-size: 13px;
  line-height: 1.4;
  color: var(--text-label, #c4d3e0);
}
.login-form :deep(.el-form-item__error) {
  color: var(--danger, #ff8a80);
  padding-top: 2px;
}

.login-form :deep(.platform-input .el-input__wrapper) {
  height: 42px;
  padding: 0 14px;
  border-radius: 10px;
  background: var(--bg-input, #0b1624);
  box-shadow: 0 0 0 1px var(--border-strong, rgba(141, 163, 184, 0.22)) inset;
  transition: box-shadow 0.2s, background 0.2s;
}
.login-form :deep(.platform-input .el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent, #34d1cf) 45%, transparent) inset;
}
.login-form :deep(.platform-input .el-input__wrapper.is-focus) {
  box-shadow:
    0 0 0 1px var(--accent, #34d1cf) inset,
    0 0 0 4px var(--accent-soft, rgba(52, 209, 207, 0.14));
}
.login-form :deep(.is-error .platform-input .el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--danger, #ff8a80) inset;
}
.login-form :deep(.platform-input .el-input__inner) {
  font-size: 14px;
  color: var(--text, #e8f1f8);
}
.login-form :deep(.platform-input .el-input__inner::placeholder) {
  color: var(--placeholder, #5f7488);
}
.login-form :deep(.platform-input .el-input__prefix),
.login-form :deep(.platform-input .el-input__password) {
  color: var(--text-muted, #8da3b8);
}

.submit-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 44px;
  margin-top: 4px;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  background: var(--accent, #34d1cf);
  color: var(--btn-fg, #0b1624);
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 4px;
  box-shadow: 0 8px 24px var(--accent-soft, rgba(52, 209, 207, 0.22));
  transition: transform 0.2s, box-shadow 0.2s, background 0.2s, filter 0.2s;
}
.submit-btn:not(:disabled):hover {
  filter: brightness(1.06);
  transform: translateY(-1px);
  box-shadow: 0 10px 28px var(--accent-mid, rgba(52, 209, 207, 0.32));
}
.submit-btn:focus-visible {
  outline: 2px solid var(--text-strong, #fff);
  outline-offset: 3px;
}
.submit-btn:disabled { cursor: not-allowed; opacity: 0.75; }

.btn-spinner {
  width: 20px;
  height: 20px;
  border: 2px solid color-mix(in srgb, var(--btn-fg, #0b1624) 25%, transparent);
  border-top-color: var(--btn-fg, #0b1624);
  border-radius: 50%;
  animation: spin 0.65s linear infinite;
}

.box-meta {
  display: flex;
  justify-content: center;
  gap: 6px;
  margin-top: 14px;
  font-size: 13px;
  color: var(--text-muted, #8da3b8);
}
.link {
  color: var(--accent, #34d1cf);
  text-decoration: none;
  font-weight: 500;
}
.link:hover { text-decoration: underline; }

.box-tip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: auto;
  padding-top: 14px;
  border-top: 1px dashed var(--border, rgba(141, 163, 184, 0.2));
  font-size: 12px;
  color: var(--text-muted, #8da3b8);
}
.tip-key {
  padding: 3px 8px;
  border: 1px solid var(--accent-mid, rgba(52, 209, 207, 0.3));
  border-radius: 6px;
  background: var(--accent-soft, rgba(52, 209, 207, 0.08));
  color: var(--accent, #34d1cf);
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s;
}
.tip-key:hover {
  background: color-mix(in srgb, var(--accent, #34d1cf) 18%, transparent);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

@keyframes spin { to { transform: rotate(360deg); } }
@keyframes shake {
  10%, 90% { transform: translateX(-3px); }
  20%, 80% { transform: translateX(4px); }
  30%, 50%, 70% { transform: translateX(-5px); }
  40%, 60% { transform: translateX(5px); }
}

@media (max-width: 479px) {
  .login-box { padding: 24px 20px 18px; }
  .box-title { font-size: 22px; }
}

@media (prefers-reduced-motion: reduce) {
  .login-box-track { transition: opacity 0.3s ease; transform: none; }
  .login-box.shake { animation: none; }
  .login-box { transition: none; }
}
</style>
