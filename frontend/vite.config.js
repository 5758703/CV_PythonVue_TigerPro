import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const QUIET_PROXY_CODES = new Set(['ECONNRESET', 'ECONNABORTED', 'EPIPE', 'ECONNREFUSED'])

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5001',
        changeOrigin: true,
        timeout: 0,
        proxyTimeout: 0,
        configure: (proxy) => {
          // 后端热重载 / 流结束时重置连接属预期，避免 vite 刷 error 栈
          proxy.on('proxyReq', (proxyReq, req) => {
            if (String(req.url || '').includes('/stream')) {
              proxyReq.setHeader('Connection', 'keep-alive')
            }
          })
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
    },
  },
})
