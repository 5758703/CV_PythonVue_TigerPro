import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

const QUIET_PROXY_CODES = new Set(['ECONNRESET', 'ECONNABORTED', 'EPIPE', 'ECONNREFUSED'])

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:5001'
  const port = Number(env.VITE_DEV_PORT || 5174)

  return {
    plugins: [vue()],
    server: {
      host: 'localhost',
      port,
      strictPort: true,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          timeout: 0,
          proxyTimeout: 0,
          configure: (proxy) => {
            proxy.on('error', (err, _req, res) => {
              if (QUIET_PROXY_CODES.has(err?.code)) {
                if (res && !res.headersSent && typeof res.writeHead === 'function') {
                  try {
                    res.writeHead(502)
                    res.end()
                  } catch (_) { /* ignore */ }
                }
                return
              }
              console.error(`[vite] http proxy error: ${err?.message || err}`)
            })
          },
        },
        '/openapi': {
          target: apiTarget,
          changeOrigin: true,
          timeout: 0,
          proxyTimeout: 0,
        },
      },
    },
  }
})
