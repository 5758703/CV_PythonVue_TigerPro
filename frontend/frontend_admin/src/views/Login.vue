<template>
  <main
    class="login-root"
    :class="{ ready: logoReady }"
    :data-theme="theme"
  >
    <LoginTechBg :theme="theme" />

    <header class="hud-top">
      <span class="status-dot" aria-hidden="true" />
      <span class="status-text">SYSTEM READY</span>
      <span class="mono status-time">{{ hudTime }}</span>
      <div class="hud-actions">
        <button
          type="button"
          class="theme-toggle"
          :aria-label="themeLabel"
          :title="themeLabel"
          @click="toggleTheme"
        >
          <el-icon :size="16">
            <Sunny v-if="isDark" />
            <Moon v-else />
          </el-icon>
          <span class="theme-toggle-text">{{ isDark ? '亮色' : '暗色' }}</span>
        </button>
        <a
          class="github-link"
          :href="GITHUB_URL"
          target="_blank"
          rel="noopener noreferrer"
          title="在 GitHub 上查看本项目"
        >
          <svg class="github-icon" viewBox="0 0 16 16" aria-hidden="true">
            <path
              fill="currentColor"
              d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38
              0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52
              -.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2
              -3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82
              .64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12
              .51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93
              -.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"
            />
          </svg>
          <span>GitHub</span>
        </a>
      </div>
    </header>

    <div class="hero">
      <section class="brand" aria-labelledby="brand-title">
        <BrandAssemble :size="logoSize" @assembled="logoReady = true" />
        <div class="brand-copy">
          <h1 id="brand-title" class="brand-name">Tiger <span class="accent">AI</span></h1>
          <p class="brand-sub">多任务 / 多模态 AI 模型管理与测试学习平台</p>
          <ul class="brand-pills" aria-label="平台能力">
            <li>视觉检测</li>
            <li>语音合成</li>
            <li>文档 OCR</li>
            <li>训练闭环</li>
          </ul>
        </div>
      </section>

      <div class="auth-slot">
        <LoginBox :visible="logoReady" />
      </div>
    </div>

    <footer class="hud-foot">视觉 · 文本 · 语音 · 训练闭环</footer>
  </main>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { Sunny, Moon } from '@element-plus/icons-vue'

import BrandAssemble from '../components/BrandAssemble.vue'
import LoginBox from '../components/LoginBox.vue'
import LoginTechBg from '../components/LoginTechBg.vue'
import { useLoginTheme } from '../composables/useLoginTheme'

const { theme, isDark, label: themeLabel, toggle: toggleTheme } = useLoginTheme()

/** 与控制台首页右上角一致 */
const GITHUB_URL = 'https://github.com/5758703/CV_PythonVue_TigerPro'

const hudTime = ref('')
const logoReady = ref(false)
const logoSize = ref(200)

let clockTimer
function updateClock() {
  hudTime.value = new Date().toTimeString().slice(0, 8)
}

function updateLogoSize() {
  const w = window.innerWidth
  logoSize.value = w >= 1280 ? 240 : w >= 960 ? 200 : w >= 480 ? 140 : 112
}

onMounted(() => {
  updateClock()
  updateLogoSize()
  clockTimer = setInterval(updateClock, 1000)
  window.addEventListener('resize', updateLogoSize)
})

onBeforeUnmount(() => {
  clearInterval(clockTimer)
  window.removeEventListener('resize', updateLogoSize)
})
</script>

<style scoped>
.login-root {
  /* 暗色（默认） */
  --bg: #0b1624;
  --bg-elevated: rgba(23, 42, 64, 0.92);
  --bg-elevated-2: rgba(16, 30, 47, 0.92);
  --bg-input: #0b1624;
  --text: #e8f1f8;
  --text-strong: #ffffff;
  --text-muted: #8da3b8;
  --text-label: #c4d3e0;
  --accent: #34d1cf;
  --accent-soft: rgba(52, 209, 207, 0.14);
  --accent-mid: rgba(52, 209, 207, 0.3);
  --border: rgba(141, 163, 184, 0.16);
  --border-strong: rgba(141, 163, 184, 0.28);
  --grid: rgba(141, 163, 184, 0.07);
  --glow-a: rgba(52, 209, 207, 0.14);
  --glow-b: rgba(23, 42, 64, 0.55);
  --shadow: 0 24px 60px rgba(0, 0, 0, 0.35);
  --btn-fg: #0b1624;
  --danger: #ff8a80;
  --placeholder: #5f7488;

  position: fixed;
  inset: 0;
  display: flex;
  flex-direction: column;
  overflow-x: hidden;
  overflow-y: auto;
  background: var(--bg);
  color: var(--text);
  font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
  color-scheme: dark;
  transition: background-color 0.35s ease, color 0.35s ease;
  isolation: isolate;
}

.login-root[data-theme='light'] {
  --bg: #eef3f8;
  --bg-elevated: rgba(255, 255, 255, 0.92);
  --bg-elevated-2: rgba(248, 251, 255, 0.96);
  --bg-input: #f3f7fb;
  --text: #243447;
  --text-strong: #0b1624;
  --text-muted: #5f7488;
  --text-label: #3d5166;
  --accent: #0f9e9c;
  --accent-soft: rgba(15, 158, 156, 0.12);
  --accent-mid: rgba(15, 158, 156, 0.28);
  --border: rgba(36, 52, 71, 0.1);
  --border-strong: rgba(36, 52, 71, 0.18);
  --grid: rgba(36, 52, 71, 0.06);
  --glow-a: rgba(15, 158, 156, 0.16);
  --glow-b: rgba(120, 160, 210, 0.2);
  --shadow: 0 24px 50px rgba(36, 52, 71, 0.12);
  --btn-fg: #ffffff;
  --danger: #d94841;
  --placeholder: #8da3b8;
  color-scheme: light;
}

.login-root *,
.login-root *::before,
.login-root *::after {
  box-sizing: border-box;
}

.hud-top,
.hud-foot,
.hero {
  position: relative;
  z-index: 1;
}

.hud-top,
.hud-foot {
  flex: 0 0 auto;
  padding: 24px 40px;
  opacity: 0;
  transition: opacity 0.7s ease 0.3s, color 0.35s ease;
}
.ready .hud-top,
.ready .hud-foot { opacity: 1; }

.hud-top {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  letter-spacing: 1.6px;
  color: var(--text-muted);
}
.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 8px color-mix(in srgb, var(--accent) 80%, transparent);
  animation: pulse 2s ease-in-out infinite;
}
.status-text { color: var(--accent); font-weight: 600; }
.status-time { margin-left: auto; }
.mono { font-family: Consolas, 'Courier New', monospace; }

.hud-actions {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-left: 12px;
}

.theme-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: color-mix(in srgb, var(--bg-elevated) 80%, transparent);
  color: var(--text);
  font-size: 12px;
  letter-spacing: 0.4px;
  cursor: pointer;
  backdrop-filter: blur(8px);
  transition: background 0.2s, border-color 0.2s, color 0.2s, transform 0.2s;
}
.theme-toggle:hover {
  border-color: var(--accent);
  color: var(--accent);
  transform: translateY(-1px);
}
.theme-toggle:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.theme-toggle-text { font-weight: 600; }

/* 对齐 Dashboard 首页右上角 GitHub 胶囊按钮 */
.github-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.2px;
  color: var(--text-strong);
  text-decoration: none;
  background: color-mix(in srgb, var(--bg-elevated) 75%, transparent);
  border: 1px solid var(--border-strong);
  backdrop-filter: blur(8px);
  transition: background 0.15s, border-color 0.15s, transform 0.15s, color 0.15s;
}
.github-link:hover {
  background: color-mix(in srgb, var(--accent) 16%, var(--bg-elevated));
  border-color: var(--accent);
  color: var(--accent);
  transform: translateY(-1px);
}
.github-link:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.github-icon {
  width: 16px;
  height: 16px;
  flex: none;
}

.hud-foot {
  margin: 0;
  text-align: center;
  font-size: 12px;
  letter-spacing: 1px;
  color: var(--text-muted);
}

.hero {
  flex: 1 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 72px;
  padding: 16px 40px;
}

.brand {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 32px;
  text-align: center;
}

.brand-copy {
  opacity: 0;
  transform: translateY(12px);
  transition: opacity 0.7s ease, transform 0.7s cubic-bezier(0.16, 1, 0.3, 1), color 0.35s ease;
}
.ready .brand-copy { opacity: 1; transform: none; }

.brand-name {
  margin: 0;
  font-size: 40px;
  font-weight: 800;
  letter-spacing: 0.5px;
  line-height: 1.1;
  color: var(--text-strong);
}
.accent { color: var(--accent); }
.brand-sub {
  margin: 12px 0 0;
  max-width: 320px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-muted);
  text-wrap: balance;
}

.brand-pills {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin: 16px 0 0;
  padding: 0;
  list-style: none;
}
.brand-pills li {
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: color-mix(in srgb, var(--bg-elevated) 70%, transparent);
  color: var(--text-muted);
  font-size: 11px;
  letter-spacing: 0.4px;
}

.auth-slot {
  flex: 0 0 auto;
  width: 448px;
  margin: -24px;
  padding: 24px;
  overflow: hidden;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.8); }
}

@media (max-width: 959px) {
  .hud-top { padding: 16px 20px; flex-wrap: wrap; }
  .hud-foot { padding: 16px 20px 24px; }
  .status-time { margin-left: 0; }
  .hud-actions { margin-left: auto; }
  .hero { flex-direction: column; gap: 36px; padding: 8px 20px; }
  .brand { gap: 20px; }
  .brand-name { font-size: 28px; }
  .brand-sub { margin-top: 8px; font-size: 13px; }
  .auth-slot { width: calc(100% + 48px); max-width: 448px; }
}

@media (prefers-reduced-motion: reduce) {
  .brand-copy, .hud-top, .hud-foot, .login-root { transition: none; }
  .status-dot { animation: none; }
  .theme-toggle { transition: none; }
}
</style>
