<template>
  <div class="tech-bg" :class="{ reduced: reducedMotion }" aria-hidden="true">
    <canvas ref="canvasRef" class="tech-canvas" />
    <div class="tech-grid" />
    <div class="tech-scan" />
    <div class="tech-crt" />
    <div class="tech-vignette" />
    <div class="tech-noise" />
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  /** 'dark' | 'light' */
  theme: { type: String, default: 'dark' },
})

const canvasRef = ref(null)
const reducedMotion = ref(false)

let raf = 0
let ctx = null
let w = 0
let h = 0
let dpr = 1
let t0 = 0
let nodes = []
let running = false
let resizeObs = null

const LINK_DIST = 140
const LINK_DIST_SQ = LINK_DIST * LINK_DIST

function palette(theme) {
  const dark = theme !== 'light'
  return {
    dark,
    accent: dark ? [52, 209, 207] : [15, 158, 156],
    accent2: dark ? [88, 140, 255] : [70, 130, 200],
    accent3: dark ? [120, 80, 220] : [90, 160, 210],
    particle: dark ? 'rgba(232,241,248,0.9)' : 'rgba(36,52,71,0.7)',
    link: dark ? 'rgba(52,209,207,' : 'rgba(15,158,156,',
    spark: dark ? 'rgba(141,163,184,0.55)' : 'rgba(95,116,136,0.45)',
  }
}

function nodeCount() {
  const area = w * h
  if (area < 500_000) return 28
  if (area < 1_200_000) return 42
  return 56
}

function spawnNodes() {
  const n = nodeCount()
  nodes = Array.from({ length: n }, () => ({
    x: Math.random() * w,
    y: Math.random() * h,
    vx: (Math.random() - 0.5) * 0.28,
    vy: (Math.random() - 0.5) * 0.28,
    r: 1 + Math.random() * 1.6,
    tw: Math.random() * Math.PI * 2,
    kind: Math.random() < 0.18 ? 'spark' : 'star',
  }))
}

function resize() {
  const el = canvasRef.value
  if (!el) return
  const parent = el.parentElement
  const rect = parent?.getBoundingClientRect() || { width: window.innerWidth, height: window.innerHeight }
  w = Math.max(1, Math.floor(rect.width))
  h = Math.max(1, Math.floor(rect.height))
  dpr = Math.min(window.devicePixelRatio || 1, 1.5)
  el.width = Math.floor(w * dpr)
  el.height = Math.floor(h * dpr)
  el.style.width = `${w}px`
  el.style.height = `${h}px`
  ctx = el.getContext('2d', { alpha: true })
  if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  spawnNodes()
}

function drawAurora(time, pal) {
  if (!ctx) return
  const bands = [
    { y: h * 0.22, amp: h * 0.08, thick: h * 0.28, rgb: pal.accent, a: pal.dark ? 0.16 : 0.1 },
    { y: h * 0.48, amp: h * 0.1, thick: h * 0.34, rgb: pal.accent2, a: pal.dark ? 0.12 : 0.08 },
    { y: h * 0.72, amp: h * 0.07, thick: h * 0.26, rgb: pal.accent3, a: pal.dark ? 0.1 : 0.06 },
  ]
  ctx.save()
  ctx.globalCompositeOperation = pal.dark ? 'screen' : 'multiply'
  for (let i = 0; i < bands.length; i += 1) {
    const b = bands[i]
    const phase = time * (0.18 + i * 0.04) + i * 1.7
    const g = ctx.createLinearGradient(0, b.y - b.thick, 0, b.y + b.thick)
    const [r, gch, bl] = b.rgb
    g.addColorStop(0, `rgba(${r},${gch},${bl},0)`)
    g.addColorStop(0.45, `rgba(${r},${gch},${bl},${b.a})`)
    g.addColorStop(0.55, `rgba(${r},${gch},${bl},${b.a * 0.85})`)
    g.addColorStop(1, `rgba(${r},${gch},${bl},0)`)
    ctx.fillStyle = g
    ctx.beginPath()
    ctx.moveTo(0, h)
    for (let x = 0; x <= w; x += 18) {
      const nx = x / w
      const y =
        b.y +
        Math.sin(nx * Math.PI * 2.2 + phase) * b.amp +
        Math.sin(nx * Math.PI * 5.1 - phase * 1.3) * b.amp * 0.35 +
        Math.cos(nx * 3 + i) * 8
      if (x === 0) ctx.moveTo(0, y)
      else ctx.lineTo(x, y)
    }
    ctx.lineTo(w, h)
    ctx.lineTo(0, h)
    ctx.closePath()
    ctx.fill()
  }
  // soft depth orbs (fake 3D parallax)
  for (let i = 0; i < 3; i += 1) {
    const px = w * (0.2 + i * 0.3) + Math.sin(time * 0.15 + i) * 40
    const py = h * (0.25 + (i % 2) * 0.35) + Math.cos(time * 0.12 + i * 1.4) * 30
    const rad = Math.min(w, h) * (0.18 + i * 0.04)
    const orb = ctx.createRadialGradient(px, py, 0, px, py, rad)
    const rgb = i === 1 ? pal.accent2 : pal.accent
    orb.addColorStop(0, `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${pal.dark ? 0.14 : 0.08})`)
    orb.addColorStop(1, `rgba(${rgb[0]},${rgb[1]},${rgb[2]},0)`)
    ctx.fillStyle = orb
    ctx.beginPath()
    ctx.arc(px, py, rad, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()
}

function stepNodes() {
  for (const p of nodes) {
    p.x += p.vx
    p.y += p.vy
    if (p.x < -20) p.x = w + 20
    else if (p.x > w + 20) p.x = -20
    if (p.y < -20) p.y = h + 20
    else if (p.y > h + 20) p.y = -20
    p.tw += 0.02
  }
}

function drawConstellation(pal) {
  if (!ctx) return
  // links
  ctx.lineWidth = 1
  for (let i = 0; i < nodes.length; i += 1) {
    const a = nodes[i]
    for (let j = i + 1; j < nodes.length; j += 1) {
      const b = nodes[j]
      const dx = a.x - b.x
      const dy = a.y - b.y
      const d2 = dx * dx + dy * dy
      if (d2 > LINK_DIST_SQ) continue
      const alpha = (1 - Math.sqrt(d2) / LINK_DIST) * (pal.dark ? 0.35 : 0.22)
      ctx.strokeStyle = `${pal.link}${alpha.toFixed(3)})`
      ctx.beginPath()
      ctx.moveTo(a.x, a.y)
      ctx.lineTo(b.x, b.y)
      ctx.stroke()
    }
  }
  // points
  for (const p of nodes) {
    const pulse = 0.55 + 0.45 * Math.sin(p.tw)
    ctx.beginPath()
    ctx.fillStyle = p.kind === 'spark' ? pal.spark : pal.particle
    ctx.globalAlpha = p.kind === 'spark' ? 0.35 + pulse * 0.4 : 0.55 + pulse * 0.35
    ctx.arc(p.x, p.y, p.r * (0.8 + pulse * 0.35), 0, Math.PI * 2)
    ctx.fill()
    if (p.kind === 'spark') {
      ctx.globalAlpha = 0.12 + pulse * 0.1
      ctx.beginPath()
      ctx.arc(p.x, p.y, p.r * 3.2, 0, Math.PI * 2)
      ctx.fill()
    }
  }
  ctx.globalAlpha = 1
}

function drawDecorDots(time, pal) {
  if (!ctx) return
  const count = 18
  ctx.save()
  for (let i = 0; i < count; i += 1) {
    const seed = i * 97.13
    const x = ((Math.sin(seed) * 0.5 + 0.5) * w + Math.sin(time * 0.07 + seed) * 12)
    const y = ((Math.cos(seed * 1.3) * 0.5 + 0.5) * h + Math.cos(time * 0.05 + seed) * 10)
    const blink = 0.15 + 0.85 * (0.5 + 0.5 * Math.sin(time * 1.4 + seed))
    ctx.fillStyle = `rgba(${pal.accent[0]},${pal.accent[1]},${pal.accent[2]},${(pal.dark ? 0.35 : 0.22) * blink})`
    ctx.fillRect(Math.floor(x), Math.floor(y), 2, 2)
  }
  ctx.restore()
}

function paint(time) {
  if (!ctx) return
  const pal = palette(props.theme)
  ctx.clearRect(0, 0, w, h)
  drawAurora(time, pal)
  drawConstellation(pal)
  drawDecorDots(time, pal)
}

function frame(now) {
  if (!running || !ctx) return
  const time = (now - t0) / 1000
  if (!reducedMotion.value) stepNodes()
  paint(time)
  if (reducedMotion.value) {
    running = false
    return
  }
  raf = requestAnimationFrame(frame)
}

function start() {
  if (running) return
  running = true
  t0 = performance.now()
  raf = requestAnimationFrame(frame)
}

function stop() {
  running = false
  if (raf) cancelAnimationFrame(raf)
  raf = 0
}

function onVisibility() {
  if (document.hidden) stop()
  else {
    resize()
    start()
  }
}

onMounted(() => {
  reducedMotion.value = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
  resize()
  start()
  window.addEventListener('resize', resize, { passive: true })
  document.addEventListener('visibilitychange', onVisibility)
  if (typeof ResizeObserver !== 'undefined' && canvasRef.value?.parentElement) {
    resizeObs = new ResizeObserver(() => resize())
    resizeObs.observe(canvasRef.value.parentElement)
  }
})

onBeforeUnmount(() => {
  stop()
  window.removeEventListener('resize', resize)
  document.removeEventListener('visibilitychange', onVisibility)
  resizeObs?.disconnect()
})

watch(
  () => props.theme,
  () => {
    // next frame picks new palette; force clear
    if (ctx) ctx.clearRect(0, 0, w, h)
  }
)
</script>

<style scoped>
.tech-bg {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  overflow: hidden;
}
.tech-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
}

/* 透视动态网格 */
.tech-grid {
  position: absolute;
  inset: -20% 0 -35%;
  background-image:
    linear-gradient(var(--grid, rgba(141, 163, 184, 0.08)) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid, rgba(141, 163, 184, 0.08)) 1px, transparent 1px);
  background-size: 56px 56px;
  transform: perspective(720px) rotateX(58deg) scale(1.35);
  transform-origin: 50% 0%;
  mask-image: linear-gradient(to bottom, transparent 0%, #000 28%, #000 72%, transparent 100%);
  opacity: 0.55;
  animation: grid-drift 28s linear infinite;
}
.login-root[data-theme='light'] .tech-grid {
  opacity: 0.35;
}

/* 扫描线 */
.tech-scan {
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    to bottom,
    transparent 0,
    transparent 2px,
    color-mix(in srgb, var(--text-muted, #8da3b8) 8%, transparent) 3px,
    transparent 4px
  );
  opacity: 0.22;
  mix-blend-mode: soft-light;
}
.login-root[data-theme='light'] .tech-scan {
  opacity: 0.12;
  mix-blend-mode: multiply;
}

.tech-scan::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  height: 28%;
  background: linear-gradient(
    to bottom,
    transparent,
    color-mix(in srgb, var(--accent, #34d1cf) 18%, transparent),
    transparent
  );
  animation: scan-sweep 5.5s ease-in-out infinite;
  opacity: 0.55;
}

/* CRT 暗角 + 轻微弯曲感 */
.tech-crt {
  position: absolute;
  inset: 0;
  box-shadow:
    inset 0 0 120px color-mix(in srgb, var(--bg, #0b1624) 70%, transparent),
    inset 0 0 40px color-mix(in srgb, #000 35%, transparent);
  opacity: 0.7;
}
.login-root[data-theme='light'] .tech-crt {
  box-shadow:
    inset 0 0 100px rgba(238, 243, 248, 0.55),
    inset 0 0 28px rgba(36, 52, 71, 0.08);
  opacity: 0.85;
}

.tech-vignette {
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse 75% 65% at 50% 45%, transparent 40%, color-mix(in srgb, var(--bg) 88%, #000) 100%);
  opacity: 0.85;
}

.tech-noise {
  position: absolute;
  inset: 0;
  opacity: 0.035;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.55'/%3E%3C/svg%3E");
  background-size: 180px 180px;
  mix-blend-mode: overlay;
  animation: noise-shift 0.35s steps(2) infinite;
}

.reduced .tech-grid,
.reduced .tech-scan::after,
.reduced .tech-noise {
  animation: none;
}
.reduced .tech-scan::after {
  opacity: 0.25;
  top: 36%;
}

@keyframes grid-drift {
  from { background-position: 0 0, 0 0; }
  to { background-position: 0 56px, 56px 0; }
}
@keyframes scan-sweep {
  0% { top: -30%; opacity: 0; }
  12% { opacity: 0.55; }
  50% { opacity: 0.4; }
  88% { opacity: 0.55; }
  100% { top: 102%; opacity: 0; }
}
@keyframes noise-shift {
  0% { transform: translate(0, 0); }
  50% { transform: translate(-1%, 1%); }
  100% { transform: translate(1%, -1%); }
}

@media (prefers-reduced-motion: reduce) {
  .tech-grid,
  .tech-scan::after,
  .tech-noise {
    animation: none !important;
  }
}
</style>
