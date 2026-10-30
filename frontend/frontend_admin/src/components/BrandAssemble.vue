<template>
  <button
    type="button"
    class="ta-stage"
    :class="{ assembled, reduced: reducedMotion }"
    :style="{ '--size': `${size}px` }"
    aria-label="Tiger AI 标识，点击重播聚合动画"
    @click="replay"
  >
    <span class="ta-floor" aria-hidden="true" />

    <span :key="cycle" class="ta-build" aria-hidden="true">
      <svg class="ta-plate" viewBox="8 8 112 112">
        <rect x="8" y="8" width="112" height="112" rx="27" fill="#172A40" />
      </svg>

      <!-- 第一阶段：T、A 各 9 块分别由远及近聚合成字母；第二阶段：两字母相向合拢成完整标识 -->
      <span
        v-for="letter in letters"
        :key="letter.id"
        class="ta-letter"
        :class="`ta-letter-${letter.id}`"
        @animationend.self="onLetterMerged"
      >
        <span
          v-for="piece in letter.pieces"
          :key="piece.key"
          class="ta-piece"
          :style="piece.style"
        >
          <svg :viewBox="piece.viewBox" preserveAspectRatio="none" class="ta-svg">
            <path :d="letter.path" :fill="letter.fill" />
          </svg>
        </span>
      </span>
    </span>

    <svg class="ta-whole" viewBox="8 8 112 112" aria-hidden="true">
      <rect x="8" y="8" width="112" height="112" rx="27" fill="#172A40" />
      <path :d="T_PATH" fill="#FFFFFF" />
      <path :d="A_PATH" fill="#34D1CF" />
    </svg>
    <span class="ta-shine" aria-hidden="true" />
  </button>
</template>

<script setup>
import { ref, onMounted } from 'vue'

defineProps({
  size: { type: Number, default: 220 },
})

const emit = defineEmits(['assembled'])

const T_PATH = 'M25 38h53v13H58v43H44V51H25V38Z'
const A_PATH = 'M77 38h15l19 56H96l-4-13H76l-4 13H58l19-56Zm3 31h9l-4.5-16L80 69Z'
const STAGE = 112
const ORIGIN = 8

/** T 按笔画切 9 块（横 4 + 竖 5），保证每块都有实体；A 按包围盒 3×3 切 9 块 */
function slicesT() {
  const bar = Array.from({ length: 4 }, (_, i) => ({ x: 25 + i * 13.25, y: 38, w: 13.25, h: 13 }))
  const stem = Array.from({ length: 5 }, (_, i) => ({ x: 44, y: 51 + i * 8.6, w: 14, h: 8.6 }))
  return [...bar, ...stem]
}
function slicesA() {
  const w = 53 / 3
  const h = 56 / 3
  return Array.from({ length: 9 }, (_, i) => ({ x: 58 + (i % 3) * w, y: 38 + Math.floor(i / 3) * h, w, h }))
}

/** T 的碎块从左侧远景飞入，A 从右侧远景飞入；越靠外越远、旋转越大 */
function buildPieces(rects, side, delays) {
  return rects.map((r, i) => {
    const cx = r.x + r.w / 2 - (side < 0 ? 51.5 : 84.5)
    const cy = r.y + r.h / 2 - 66
    const spread = 1 + (i % 3) * 0.18
    return {
      key: `${side}-${i}`,
      viewBox: `${r.x} ${r.y} ${r.w} ${r.h}`,
      style: {
        left: `${((r.x - ORIGIN) / STAGE) * 100}%`,
        top: `${((r.y - ORIGIN) / STAGE) * 100}%`,
        width: `calc(${(r.w / STAGE) * 100}% + 0.4px)`,
        height: `calc(${(r.h / STAGE) * 100}% + 0.4px)`,
        '--fx': `${(side * 420 + cx * 14) * spread}px`,
        '--fy': `${cy * 16 * spread + (i % 2 ? -90 : 90)}px`,
        '--fz': `${-1500 - ((i * 7) % 5) * 240}px`,
        '--rx': `${-cy * 2.4 + side * 8}deg`,
        '--ry': `${side * 46 + cx * 1.6}deg`,
        '--rz': `${((i * 37) % 80) - 40}deg`,
        '--delay': `${delays[i]}s`,
      },
    }
  })
}

const letters = [
  {
    id: 't',
    path: T_PATH,
    fill: '#FFFFFF',
    pieces: buildPieces(slicesT(), -1, [0.06, 0, 0.14, 0.2, 0.1, 0.26, 0.18, 0.32, 0.4]),
  },
  {
    id: 'a',
    path: A_PATH,
    fill: '#34D1CF',
    pieces: buildPieces(slicesA(), 1, [0.16, 0.08, 0.2, 0.28, 0.42, 0.12, 0.3, 0.36, 0.24]),
  },
]

const cycle = ref(0)
const assembled = ref(false)
const reducedMotion = ref(false)
let merged = 0

function onLetterMerged() {
  merged += 1
  if (merged === letters.length) {
    assembled.value = true
    emit('assembled')
  }
}

function replay() {
  if (reducedMotion.value) return
  merged = 0
  assembled.value = false
  cycle.value += 1
}

onMounted(() => {
  reducedMotion.value = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
  if (reducedMotion.value) {
    assembled.value = true
    emit('assembled')
  }
})
</script>

<style scoped>
.ta-stage {
  --gather: 1.4s;
  --merge-at: 1.95s;
  --merge: 0.75s;
  position: relative;
  width: var(--size);
  height: var(--size);
  padding: 0;
  border: 0;
  background: none;
  cursor: pointer;
  perspective: 1100px;
  perspective-origin: 50% 40%;
  -webkit-tap-highlight-color: transparent;
}
.ta-stage:focus-visible {
  outline: 2px solid #34d1cf;
  outline-offset: 10px;
  border-radius: 28%;
}

.ta-floor {
  position: absolute;
  left: 50%;
  bottom: -18%;
  width: 90%;
  height: 18%;
  transform: translateX(-50%);
  border-radius: 50%;
  background: radial-gradient(closest-side, rgba(52, 209, 207, 0.38), transparent);
  filter: blur(6px);
  opacity: 0;
  animation: floor-in 1.4s 1.6s ease-out forwards;
}

.ta-build {
  position: absolute;
  inset: 0;
  transform-style: preserve-3d;
}

.ta-plate {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  transform: scale(0.72);
  animation: plate-in var(--merge) var(--merge-at) cubic-bezier(0.16, 1, 0.3, 1) forwards;
}

.ta-letter {
  position: absolute;
  inset: 0;
  transform-style: preserve-3d;
  animation: merge var(--merge) var(--merge-at) cubic-bezier(0.65, 0, 0.2, 1.25) both;
}
.ta-letter-t { --apart: calc(var(--size) * -0.2); }
.ta-letter-a { --apart: calc(var(--size) * 0.2); }

.ta-piece {
  position: absolute;
  transform-style: preserve-3d;
  will-change: transform, opacity, filter;
  opacity: 0;
  animation: fly-in var(--gather) var(--delay) cubic-bezier(0.16, 1, 0.3, 1) forwards;
}
.ta-svg {
  display: block;
  width: 100%;
  height: 100%;
}

@keyframes fly-in {
  0% {
    opacity: 0;
    filter: blur(10px) drop-shadow(0 0 0 rgba(52, 209, 207, 0));
    transform: translate3d(var(--fx), var(--fy), var(--fz)) rotateX(var(--rx)) rotateY(var(--ry)) rotateZ(var(--rz));
  }
  18% {
    opacity: 1;
  }
  62% {
    filter: blur(0) drop-shadow(0 0 8px rgba(52, 209, 207, 0.85));
    transform: translate3d(calc(var(--fx) * 0.04), calc(var(--fy) * 0.04), 50px) rotateX(calc(var(--rx) * 0.06))
      rotateY(calc(var(--ry) * 0.06)) rotateZ(calc(var(--rz) * 0.04));
  }
  100% {
    opacity: 1;
    filter: blur(0) drop-shadow(0 0 0 rgba(52, 209, 207, 0));
    transform: translate3d(0, 0, 0) rotateX(0) rotateY(0) rotateZ(0);
  }
}

/* 字母成形期间两组左右分开，随后相向合拢到最终位置 */
@keyframes merge {
  from { transform: translateX(var(--apart)); }
  to { transform: translateX(0); }
}
@keyframes plate-in {
  to { opacity: 1; transform: scale(1); }
}

.ta-whole {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  pointer-events: none;
}

.ta-shine {
  position: absolute;
  inset: 0;
  border-radius: 24%;
  overflow: hidden;
  pointer-events: none;
}
.ta-shine::after {
  content: '';
  position: absolute;
  top: -20%;
  left: -60%;
  width: 40%;
  height: 140%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.35), transparent);
  transform: skewX(-18deg);
  opacity: 0;
}

/* 聚合完成：切换为整图消除拼缝，并做一次锁定光扫 + 呼吸光晕 */
.assembled .ta-build {
  visibility: hidden;
}
.assembled .ta-whole {
  opacity: 1;
  animation: lock-pulse 3.6s 0.2s ease-in-out infinite;
}
.assembled .ta-shine::after {
  animation: sweep 1.1s ease-out forwards;
}
.assembled:hover .ta-whole {
  transform: translateY(-3px);
  transition: transform 0.3s ease;
}

@keyframes sweep {
  0% { left: -60%; opacity: 0; }
  20% { opacity: 1; }
  100% { left: 130%; opacity: 0; }
}
@keyframes lock-pulse {
  0%, 100% { filter: drop-shadow(0 10px 28px rgba(52, 209, 207, 0.18)); }
  50% { filter: drop-shadow(0 12px 40px rgba(52, 209, 207, 0.42)); }
}
@keyframes floor-in {
  to { opacity: 1; }
}

.reduced .ta-floor { animation: none; opacity: 1; }
.reduced .ta-shine::after { animation: none; }
.reduced .ta-whole { animation: none; }
</style>
