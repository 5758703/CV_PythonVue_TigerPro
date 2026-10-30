import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'

const STORAGE_KEY = 'tiger-admin-login-theme'

/** @type {import('vue').Ref<'dark' | 'light'>} */
const theme = ref('dark')
let media
let mediaHandler

function readStored() {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'light' || v === 'dark') return v
  } catch {
    /* ignore */
  }
  return null
}

function systemPrefersDark() {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? true
}

function resolveInitial() {
  return readStored() || (systemPrefersDark() ? 'dark' : 'light')
}

export function useLoginTheme() {
  const isDark = computed(() => theme.value === 'dark')
  const isLight = computed(() => theme.value === 'light')
  const label = computed(() => (isDark.value ? '切换到亮色' : '切换到暗色'))

  function setTheme(next) {
    theme.value = next === 'light' ? 'light' : 'dark'
  }

  function toggle() {
    setTheme(isDark.value ? 'light' : 'dark')
  }

  onMounted(() => {
    theme.value = resolveInitial()
    media = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!media) return
    mediaHandler = (e) => {
      if (readStored()) return
      theme.value = e.matches ? 'dark' : 'light'
    }
    media.addEventListener?.('change', mediaHandler)
  })

  onBeforeUnmount(() => {
    media?.removeEventListener?.('change', mediaHandler)
  })

  watch(
    theme,
    (v) => {
      try {
        localStorage.setItem(STORAGE_KEY, v)
      } catch {
        /* ignore */
      }
    },
    { flush: 'post' }
  )

  return { theme, isDark, isLight, label, setTheme, toggle }
}
