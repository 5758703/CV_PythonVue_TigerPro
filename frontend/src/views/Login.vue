<template>
  <div class="login-root">
    <!-- Three.js canvas 背景 -->
    <canvas ref="canvasRef" class="bg-canvas" />

    <!-- 全息 HUD 装饰层 -->
    <div class="hud-layer">
      <div class="hud-corner hud-tl" />
      <div class="hud-corner hud-tr" />
      <div class="hud-corner hud-bl" />
      <div class="hud-corner hud-br" />
      <div class="hud-scan-line" />
      <div class="hud-top-bar">
        <span class="hud-text">TIGER · AI · PLATFORM</span>
        <span class="hud-dot" />
        <span class="hud-text blink">ONLINE</span>
      </div>
      <div class="hud-bottom-bar">
        <span class="hud-text mono">SYS v2.6.1</span>
        <span class="hud-divider" />
        <span class="hud-text mono">{{ hudTime }}</span>
        <span class="hud-divider" />
        <span class="hud-text mono">NODE: 0x{{ nodeId }}</span>
      </div>
      <div class="vol-light vol-left" />
      <div class="vol-light vol-right" />
    </div>

    <!-- 登录卡片 -->
    <div class="login-card" :class="{ shake: shaking }">
      <div class="card-glow" />

      <!-- LOGO区 -->
      <div class="brand-row">
        <div class="brand-icon">
          <div class="icon-hex">
            <svg viewBox="0 0 60 60" fill="none">
              <polygon points="30,4 54,17 54,43 30,56 6,43 6,17"
                stroke="url(#hexGrad)" stroke-width="1.5" fill="url(#hexFill)" />
              <text x="50%" y="57%" dominant-baseline="middle" text-anchor="middle"
                fill="white" font-size="16" font-weight="800" font-family="monospace">CV</text>
              <defs>
                <linearGradient id="hexGrad" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stop-color="#38bdf8"/>
                  <stop offset="100%" stop-color="#818cf8"/>
                </linearGradient>
                <linearGradient id="hexFill" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stop-color="#0ea5e9" stop-opacity="0.3"/>
                  <stop offset="100%" stop-color="#6366f1" stop-opacity="0.15"/>
                </linearGradient>
              </defs>
            </svg>
          </div>
          <div class="icon-ring ring1" />
          <div class="icon-ring ring2" />
        </div>
        <div class="brand-text">
          <h1 class="brand-name">Tiger AI Platform</h1>
          <p class="brand-sub">多任务 AI 模型管理与测试平台</p>
        </div>
      </div>

      <div class="divider-line">
        <span class="divider-dot" /><span class="divider-core" /><span class="divider-dot" />
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" class="login-form" @keyup.enter="onSubmit">
        <el-form-item prop="username">
          <div class="input-wrap">
            <el-icon class="inp-icon"><User /></el-icon>
            <el-input v-model="form.username" placeholder="用户名" class="glass-input" />
          </div>
        </el-form-item>
        <el-form-item prop="password">
          <div class="input-wrap">
            <el-icon class="inp-icon"><Lock /></el-icon>
            <el-input v-model="form.password" type="password" placeholder="密码"
              show-password class="glass-input" />
          </div>
        </el-form-item>

        <button class="submit-btn" :class="{ loading }" @click.prevent="onSubmit" :disabled="loading">
          <span v-if="!loading" class="btn-label">登 录</span>
          <span v-else class="btn-spinner" />
          <div class="btn-shine" />
        </button>
      </el-form>

      <div class="login-tip">
        <span class="tip-key">admin</span> / <span class="tip-key">admin123</span>
        &nbsp;·&nbsp;
        <span class="tip-key">tiger</span> / <span class="tip-key">123456</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import * as THREE from 'three'

import { login } from '../api/auth'
import { useUserStore } from '../store/user'

const router = useRouter()
const store = useUserStore()
const canvasRef = ref(null)
const formRef = ref(null)
const loading = ref(false)
const shaking = ref(false)
const hudTime = ref('')
const nodeId = ref('A4F3')

const form = reactive({ username: 'admin', password: 'admin123' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

let clockTimer
function updateClock() {
  hudTime.value = new Date().toTimeString().slice(0, 8)
}

const onSubmit = async () => {
  await formRef.value.validate()
  loading.value = true
  try {
    const res = await login(form)
    store.setToken(res.data.token)
    await store.loadInfo()
    ElMessage.success('登录成功')
    router.push('/index')
  } catch {
    shaking.value = true
    setTimeout(() => (shaking.value = false), 600)
  } finally {
    loading.value = false
  }
}

// ════ Three.js shaders ════

const BG_VERT = `void main(){gl_Position=vec4(position,1.0);}`

const BG_FRAG = `
uniform float uTime;
uniform vec2 uRes;
uniform vec2 uMouse;

float hash(vec2 p){p=fract(p*vec2(234.34,435.346));p+=dot(p,p+34.23);return fract(p.x*p.y);}

float noise(vec2 p){
  vec2 i=floor(p);vec2 f=fract(p);
  f=f*f*(3.0-2.0*f);
  return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);
}

float neuralRipple(vec2 uv,float t){
  float v=0.0;
  for(int i=0;i<7;i++){
    float fi=float(i);
    vec2 c=vec2(0.5+0.38*sin(fi*1.3+t*0.25),0.5+0.38*cos(fi*0.9+t*0.18));
    float d=length(uv-c);
    v+=sin(d*20.0-t*2.2+fi*0.9)*exp(-d*4.0)*0.18;
  }
  return v;
}

void main(){
  vec2 uv=gl_FragCoord.xy/uRes;

  // 深空渐变
  vec3 col=mix(vec3(0.02,0.03,0.10),vec3(0.04,0.01,0.15),uv.y);

  // 流体噪声纹理
  float n=noise(uv*4.0+uTime*0.12)*0.5+noise(uv*8.0-uTime*0.08)*0.25;
  col+=vec3(0.02,0.06,0.14)*n;

  // 体积光 — 上下两道
  float vl1=exp(-pow(length(uv-vec2(0.5,0.0))*1.3,2.0))*0.18;
  col+=vec3(0.05,0.35,1.0)*vl1;
  float vl2=exp(-pow(length(uv-vec2(0.5,1.0))*1.5,2.0))*0.12;
  col+=vec3(0.25,0.05,0.8)*vl2;

  // 神经网络波纹
  float rip=neuralRipple(uv,uTime);
  col+=vec3(0.0,0.5,1.0)*rip*0.7;
  col+=vec3(0.3,0.0,0.85)*rip*0.35;

  // 鼠标跟随光晕
  vec2 mp=uMouse*0.5+0.5;
  float mg=exp(-length(uv-mp)*3.8)*0.3;
  col+=vec3(0.15,0.55,1.0)*mg;

  // 暗角
  float vig=1.0-smoothstep(0.25,0.9,length(uv-0.5)*1.5);
  col*=0.4+0.6*vig;

  gl_FragColor=vec4(col,1.0);
}
`

const PARTICLE_VERT = `
uniform float uTime;
uniform vec2 uMouse;
attribute float aSize;
attribute float aSpeed;
attribute float aPhase;
varying float vAlpha;
varying float vHue;

float hash3(vec3 p){p=fract(p*0.3183+0.1);p*=17.0;return fract(p.x*p.y*p.z*(p.x+p.y+p.z));}
float noise3(vec3 p){
  vec3 i=floor(p);vec3 f=fract(p);f=f*f*(3.0-2.0*f);
  return mix(mix(mix(hash3(i),hash3(i+vec3(1,0,0)),f.x),
    mix(hash3(i+vec3(0,1,0)),hash3(i+vec3(1,1,0)),f.x),f.y),
    mix(mix(hash3(i+vec3(0,0,1)),hash3(i+vec3(1,0,1)),f.x),
    mix(hash3(i+vec3(0,1,1)),hash3(i+vec3(1,1,1)),f.x),f.y),f.z);
}

void main(){
  vec3 pos=position;
  float t=uTime*aSpeed+aPhase;

  // 流体扰动 3-octave
  float nx=noise3(pos*0.4+vec3(t*0.25,0,0));
  float ny=noise3(pos*0.4+vec3(0,t*0.25,1.5));
  float nz=noise3(pos*0.4+vec3(2.1,0,t*0.25));
  pos+=vec3(nx,ny,nz)*1.0;

  // 波纹
  pos.z+=sin(length(pos.xy)*1.4-uTime*2.0)*0.35;

  // 鼠标斥力
  float d=length(pos.xy-uMouse*6.0);
  pos.xy+=normalize(pos.xy-uMouse*6.0+0.001)*smoothstep(3.0,0.0,d)*1.8;

  vHue=nx;
  vAlpha=0.25+0.75*(0.5+0.5*sin(t+aPhase));

  vec4 mv=modelViewMatrix*vec4(pos,1.0);
  gl_PointSize=aSize*(280.0/-mv.z);
  gl_Position=projectionMatrix*mv;
}
`

const PARTICLE_FRAG = `
varying float vAlpha;
varying float vHue;
uniform float uTime;

void main(){
  vec2 uv=gl_PointCoord-0.5;
  float r=length(uv);
  if(r>0.5)discard;

  float core=exp(-r*14.0);
  float halo=exp(-r*4.5)*0.45;
  float glow=core+halo;

  // 青→紫渐变 + 时间偏移
  vec3 col=mix(vec3(0.0,0.85,1.0),vec3(0.5,0.25,1.0),clamp(vHue+sin(uTime*0.4)*0.1,0.0,1.0));
  col=mix(col,vec3(1.0),core*0.55);

  gl_FragColor=vec4(col,glow*vAlpha);
}
`

const LINE_VERT = `
attribute float aAlpha;
varying float vAlpha;
void main(){vAlpha=aAlpha;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}
`
const LINE_FRAG = `
uniform float uTime;
varying float vAlpha;
void main(){
  float p=0.5+0.5*sin(uTime*1.8);
  vec3 col=mix(vec3(0.05,0.55,1.0),vec3(0.4,0.15,0.9),p);
  gl_FragColor=vec4(col,vAlpha*0.45);
}
`

let renderer, scene, camera, animId
let mouseX = 0, mouseY = 0

function onMouseMove(e) {
  mouseX = (e.clientX / window.innerWidth) * 2 - 1
  mouseY = -((e.clientY / window.innerHeight) * 2 - 1)
}

function initThree() {
  const W = window.innerWidth, H = window.innerHeight

  renderer = new THREE.WebGLRenderer({ canvas: canvasRef.value, antialias: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.setSize(W, H)

  scene = new THREE.Scene()
  camera = new THREE.PerspectiveCamera(60, W / H, 0.1, 200)
  camera.position.z = 13

  // ── 背景 fullscreen quad ──
  const bgGeo = new THREE.BufferGeometry()
  bgGeo.setAttribute('position', new THREE.BufferAttribute(
    new Float32Array([-1,-1,0, 1,-1,0, 1,1,0, -1,-1,0, 1,1,0, -1,1,0]), 3))
  const bgMat = new THREE.ShaderMaterial({
    vertexShader: BG_VERT, fragmentShader: BG_FRAG,
    uniforms: {
      uTime: { value: 0 },
      uRes: { value: new THREE.Vector2(W, H) },
      uMouse: { value: new THREE.Vector2(0, 0) }
    },
    depthTest: false, depthWrite: false
  })
  const bgMesh = new THREE.Mesh(bgGeo, bgMat)
  bgMesh.renderOrder = -999
  bgMesh.frustumCulled = false
  scene.add(bgMesh)

  // ── 粒子 ──
  const CNT = 3200
  const pos = new Float32Array(CNT * 3)
  const sizes = new Float32Array(CNT)
  const speeds = new Float32Array(CNT)
  const phases = new Float32Array(CNT)

  for (let i = 0; i < CNT; i++) {
    const r = Math.random() * 14
    const t = Math.random() * Math.PI * 2
    const p = Math.acos(2 * Math.random() - 1)
    pos[i*3]   = r * Math.sin(p) * Math.cos(t)
    pos[i*3+1] = r * Math.sin(p) * Math.sin(t)
    pos[i*3+2] = (Math.random() - 0.5) * 9
    sizes[i]   = Math.random() * 2.8 + 0.4
    speeds[i]  = Math.random() * 0.5 + 0.15
    phases[i]  = Math.random() * Math.PI * 2
  }

  const pGeo = new THREE.BufferGeometry()
  pGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3))
  pGeo.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1))
  pGeo.setAttribute('aSpeed', new THREE.BufferAttribute(speeds, 1))
  pGeo.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1))

  const pMat = new THREE.ShaderMaterial({
    vertexShader: PARTICLE_VERT, fragmentShader: PARTICLE_FRAG,
    uniforms: {
      uTime: { value: 0 },
      uMouse: { value: new THREE.Vector2(0, 0) }
    },
    transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending
  })
  const particles = new THREE.Points(pGeo, pMat)
  scene.add(particles)

  // ── 神经网络连线 ──
  const NODE_CNT = 70
  const nodes = []
  for (let i = 0; i < NODE_CNT; i++) {
    nodes.push(new THREE.Vector3(
      (Math.random() - 0.5) * 22,
      (Math.random() - 0.5) * 14,
      (Math.random() - 0.5) * 7
    ))
  }
  const linePos = [], lineAlpha = []
  const MAX_D = 5.5
  for (let i = 0; i < NODE_CNT; i++) {
    for (let j = i + 1; j < NODE_CNT; j++) {
      const d = nodes[i].distanceTo(nodes[j])
      if (d < MAX_D) {
        linePos.push(nodes[i].x, nodes[i].y, nodes[i].z, nodes[j].x, nodes[j].y, nodes[j].z)
        const a = 1 - d / MAX_D
        lineAlpha.push(a, a)
      }
    }
  }

  const lGeo = new THREE.BufferGeometry()
  lGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(linePos), 3))
  lGeo.setAttribute('aAlpha', new THREE.BufferAttribute(new Float32Array(lineAlpha), 1))
  const lMat = new THREE.ShaderMaterial({
    vertexShader: LINE_VERT, fragmentShader: LINE_FRAG,
    uniforms: { uTime: { value: 0 } },
    transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending
  })
  const lines = new THREE.LineSegments(lGeo, lMat)
  scene.add(lines)

  // ── 动画循环 ──
  const startTime = performance.now()
  function animate() {
    animId = requestAnimationFrame(animate)
    const t = (performance.now() - startTime) / 1000

    bgMat.uniforms.uTime.value = t
    bgMat.uniforms.uMouse.value.set(mouseX, mouseY)
    pMat.uniforms.uTime.value = t
    pMat.uniforms.uMouse.value.set(mouseX, mouseY)
    lMat.uniforms.uTime.value = t

    // 摄像机跟随鼠标
    camera.position.x += (mouseX * 1.8 - camera.position.x) * 0.025
    camera.position.y += (mouseY * 1.0 - camera.position.y) * 0.025
    camera.lookAt(0, 0, 0)

    particles.rotation.y = t * 0.035
    particles.rotation.x = Math.sin(t * 0.018) * 0.08
    lines.rotation.y = t * 0.035
    lines.rotation.x = Math.sin(t * 0.018) * 0.08

    renderer.render(scene, camera)
  }
  animate()

  const onResize = () => {
    const w = window.innerWidth, h = window.innerHeight
    renderer.setSize(w, h)
    camera.aspect = w / h
    camera.updateProjectionMatrix()
    bgMat.uniforms.uRes.value.set(w, h)
  }
  window.addEventListener('resize', onResize)
}

onMounted(() => {
  updateClock()
  clockTimer = setInterval(updateClock, 1000)
  nodeId.value = Math.random().toString(16).slice(2, 6).toUpperCase()
  window.addEventListener('mousemove', onMouseMove)
  initThree()
})

onBeforeUnmount(() => {
  clearInterval(clockTimer)
  window.removeEventListener('mousemove', onMouseMove)
  cancelAnimationFrame(animId)
  renderer?.dispose()
})
</script>

<style scoped>
.login-root {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  font-family: 'Inter', 'SF Pro Display', system-ui, sans-serif;
}

.bg-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: 0;
}

/* ══ HUD ══ */
.hud-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 1;
}

.hud-corner {
  position: absolute;
  width: 30px;
  height: 30px;
  border-color: rgba(56, 189, 248, 0.55);
  border-style: solid;
}
.hud-tl { top: 18px; left: 18px; border-width: 2px 0 0 2px; }
.hud-tr { top: 18px; right: 18px; border-width: 2px 2px 0 0; }
.hud-bl { bottom: 18px; left: 18px; border-width: 0 0 2px 2px; }
.hud-br { bottom: 18px; right: 18px; border-width: 0 2px 2px 0; }

.hud-scan-line {
  position: absolute;
  left: 0; right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(56,189,248,0.55), transparent);
  animation: scanLine 7s linear infinite;
}
@keyframes scanLine {
  0%   { top: 0; opacity: 1; }
  85%  { top: 100%; opacity: 0.2; }
  100% { top: 100%; opacity: 0; }
}

.hud-top-bar, .hud-bottom-bar {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 10px;
  letter-spacing: 2px;
  color: rgba(56,189,248,0.65);
}
.hud-top-bar    { top: 18px; }
.hud-bottom-bar { bottom: 18px; }
.hud-text { font-family: 'Courier New', monospace; }
.hud-text.mono { opacity: 0.65; }
.hud-text.blink { animation: blink 1.8s step-end infinite; }
.hud-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: #22d3ee;
  box-shadow: 0 0 6px #22d3ee;
  animation: pulse 2s ease-in-out infinite;
}
.hud-divider { width: 1px; height: 12px; background: rgba(56,189,248,0.35); }

@keyframes blink  { 0%,100%{opacity:1} 50%{opacity:0.15} }
@keyframes pulse  { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.35;transform:scale(0.75)} }

.vol-light {
  position: absolute;
  top: 0;
  width: 280px;
  height: 100%;
  pointer-events: none;
}
.vol-left  { left: -80px;  background: linear-gradient(90deg,transparent,rgba(56,189,248,0.04),transparent); transform: skewX(-12deg); animation: volP 5s ease-in-out infinite; }
.vol-right { right: -80px; background: linear-gradient(90deg,transparent,rgba(139,92,246,0.04),transparent); transform: skewX(12deg);  animation: volP 5s ease-in-out infinite 2.5s; }
@keyframes volP { 0%,100%{opacity:0.4} 50%{opacity:1} }

/* ══ 登录卡片 ══ */
.login-card {
  position: relative;
  z-index: 2;
  width: 420px;
  padding: 42px 40px 36px;
  border-radius: 20px;
  background: linear-gradient(135deg, rgba(255,255,255,0.075) 0%, rgba(255,255,255,0.028) 100%);
  backdrop-filter: blur(26px) saturate(1.5);
  -webkit-backdrop-filter: blur(26px) saturate(1.5);
  border: 1px solid rgba(148,210,255,0.16);
  box-shadow:
    inset 0 0 0 1px rgba(255,255,255,0.05),
    0 24px 64px rgba(0,0,0,0.65),
    0 0 90px rgba(56,189,248,0.07),
    0 0 130px rgba(139,92,246,0.05);
  transition: box-shadow 0.4s;
}
.login-card:hover {
  box-shadow:
    inset 0 0 0 1px rgba(255,255,255,0.07),
    0 28px 72px rgba(0,0,0,0.7),
    0 0 110px rgba(56,189,248,0.11),
    0 0 150px rgba(139,92,246,0.08);
}
.login-card.shake {
  animation: shake 0.5s cubic-bezier(.36,.07,.19,.97);
}
@keyframes shake {
  10%,90% { transform:translateX(-3px); }
  20%,80% { transform:translateX(4px); }
  30%,50%,70% { transform:translateX(-5px); }
  40%,60% { transform:translateX(5px); }
}

.card-glow {
  position: absolute;
  top: -1px; left: 50%;
  transform: translateX(-50%);
  width: 55%; height: 2px;
  background: linear-gradient(90deg, transparent, rgba(56,189,248,0.9), rgba(139,92,246,0.85), transparent);
  box-shadow: 0 0 18px rgba(56,189,248,0.5), 0 0 36px rgba(139,92,246,0.3);
  border-radius: 0 0 4px 4px;
}

/* ── LOGO ── */
.brand-row {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 28px;
}
.brand-icon {
  position: relative;
  width: 56px; height: 56px;
  flex-shrink: 0;
}
.icon-hex {
  position: relative; z-index: 1;
  width: 100%; height: 100%;
  filter: drop-shadow(0 0 10px rgba(56,189,248,0.55));
}
.icon-ring {
  position: absolute;
  border-radius: 50%;
  top: 50%; left: 50%;
  transform: translate(-50%,-50%);
}
.ring1 {
  width: 66px; height: 66px;
  border: 1px solid rgba(56,189,248,0.3);
  animation: rot 7s linear infinite;
}
.ring2 {
  width: 82px; height: 82px;
  border: 1px solid rgba(139,92,246,0.2);
  animation: rot 11s linear infinite reverse;
}
@keyframes rot { to { transform: translate(-50%,-50%) rotate(360deg); } }

.brand-name {
  margin: 0;
  font-size: 19px;
  font-weight: 700;
  background: linear-gradient(135deg,#e0f2fe,#c7d2fe);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: 0.4px;
}
.brand-sub {
  margin: 5px 0 0;
  font-size: 11px;
  color: rgba(148,163,184,0.65);
  letter-spacing: 0.4px;
}

.divider-line {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 24px;
}
.divider-core {
  flex: 1; height: 1px;
  background: linear-gradient(90deg,transparent,rgba(56,189,248,0.38),rgba(139,92,246,0.38),transparent);
}
.divider-dot {
  width: 4px; height: 4px; border-radius: 50%;
  background: rgba(56,189,248,0.65);
  box-shadow: 0 0 5px rgba(56,189,248,0.8);
}

/* ── 输入框 ── */
.login-form :deep(.el-form-item) { margin-bottom: 16px; }
.login-form :deep(.el-form-item__error) { color: #f87171; }

.input-wrap { position: relative; width: 100%; }
.inp-icon {
  position: absolute;
  left: 13px; top: 50%;
  transform: translateY(-50%);
  z-index: 2;
  color: rgba(56,189,248,0.65);
  font-size: 15px;
  pointer-events: none;
}

.login-form :deep(.glass-input .el-input__wrapper) {
  background: rgba(255,255,255,0.035);
  border: 1px solid rgba(148,210,255,0.18);
  border-radius: 10px;
  box-shadow: none;
  padding-left: 38px;
  transition: border-color 0.3s, box-shadow 0.3s, background 0.3s;
}
.login-form :deep(.glass-input .el-input__wrapper:hover),
.login-form :deep(.glass-input .el-input__wrapper.is-focus) {
  background: rgba(56,189,248,0.055);
  border-color: rgba(56,189,248,0.48);
  box-shadow: 0 0 0 3px rgba(56,189,248,0.1), inset 0 0 10px rgba(56,189,248,0.04);
}
.login-form :deep(.glass-input .el-input__inner) {
  color: #e0f2fe;
  font-size: 14px;
  height: 44px;
  background: transparent;
}
.login-form :deep(.glass-input .el-input__inner::placeholder) {
  color: rgba(148,163,184,0.45);
}
.login-form :deep(.el-input__password) {
  color: rgba(56,189,248,0.6);
}

/* ── 提交按钮 ── */
.submit-btn {
  position: relative;
  width: 100%;
  height: 48px;
  margin-top: 8px;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  overflow: hidden;
  background: linear-gradient(135deg, #0ea5e9 0%, #6366f1 100%);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 6px;
  box-shadow: 0 4px 22px rgba(14,165,233,0.38), 0 0 44px rgba(99,102,241,0.22);
  transition: transform 0.2s, box-shadow 0.3s;
}
.submit-btn:not(:disabled):hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 32px rgba(14,165,233,0.48), 0 0 60px rgba(99,102,241,0.32);
}
.submit-btn:active { transform: translateY(0); }
.submit-btn:disabled { cursor: not-allowed; opacity: 0.7; }

.btn-shine {
  position: absolute;
  top: 0; left: -80%;
  width: 55%; height: 100%;
  background: linear-gradient(90deg,transparent,rgba(255,255,255,0.22),transparent);
  transform: skewX(-20deg);
  animation: shine 4.5s ease-in-out infinite;
}
@keyframes shine {
  0%   { left:-80%; opacity:0; }
  15%  { opacity:1; }
  40%  { left:140%; opacity:0; }
  100% { left:140%; opacity:0; }
}

.btn-spinner {
  display: inline-block;
  width: 20px; height: 20px;
  border: 2px solid rgba(255,255,255,0.28);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.65s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── 提示 ── */
.login-tip {
  margin-top: 18px;
  text-align: center;
  font-size: 11px;
  color: rgba(100,116,139,0.75);
}
.tip-key {
  font-family: 'Courier New', monospace;
  color: rgba(56,189,248,0.6);
  background: rgba(56,189,248,0.07);
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px solid rgba(56,189,248,0.14);
}
</style>
