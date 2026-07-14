<template>
  <div class="login-root">
    <!-- Three.js 背景（首页同色深蓝梯度 + 粒子网络） -->
    <canvas ref="canvasRef" class="bg-canvas" />

    <!-- 轻量平台装饰（对齐首页 hero 气质，弱化科幻 HUD） -->
    <div class="chrome-layer">
      <div class="chrome-top">
        <span class="chrome-brand">TIGER AI PLATFORM</span>
        <span class="chrome-dot" />
        <span class="chrome-status">READY</span>
      </div>
      <div class="chrome-bottom">
        <span>视觉 · 文本 · 语音 · 训练闭环</span>
        <span class="chrome-sep">|</span>
        <span class="mono">{{ hudTime }}</span>
      </div>
    </div>

    <!-- 登录面板：白卡片风格对齐首页 stat/loop card -->
    <div class="login-shell" :class="{ shake: shaking }">
      <div class="hero-band">
        <div class="hero-badge">CV</div>
        <div class="hero-copy">
          <h1 class="brand-name">Tiger AI Platform</h1>
          <p class="brand-sub">多任务 / 多模态 AI 模型管理与测试学习平台</p>
        </div>
      </div>

      <div class="card-body">
        <div class="feature-tags">
          <span v-for="t in tags" :key="t.text" class="htag" :style="{ background: t.color }">{{ t.text }}</span>
        </div>

        <el-form ref="formRef" :model="form" :rules="rules" class="login-form" @keyup.enter="onSubmit">
          <el-form-item prop="username">
            <div class="input-wrap">
              <el-icon class="inp-icon"><User /></el-icon>
              <el-input v-model="form.username" placeholder="用户名" class="platform-input" />
            </div>
          </el-form-item>
          <el-form-item prop="password">
            <div class="input-wrap">
              <el-icon class="inp-icon"><Lock /></el-icon>
              <el-input
                v-model="form.password"
                type="password"
                placeholder="密码"
                show-password
                class="platform-input"
              />
            </div>
          </el-form-item>

          <button class="submit-btn" :class="{ loading }" :disabled="loading" @click.prevent="onSubmit">
            <span v-if="!loading" class="btn-label">登 录</span>
            <span v-else class="btn-spinner" />
            <div class="btn-shine" />
          </button>
        </el-form>

        <div class="login-tip">
          默认账号
          <span class="tip-key">admin</span> / <span class="tip-key">admin123</span>
          <span class="tip-sep">·</span>
          <span class="tip-key">tiger</span> / <span class="tip-key">123456</span>
        </div>
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

const tags = [
  { text: '目标检测', color: '#409eff' },
  { text: '模型训练闭环', color: '#1a73e8' },
  { text: '在线标注', color: '#ff6b35' },
  { text: '姿态估计', color: '#00b894' },
  { text: '语音 ASR/TTS', color: '#f5222d' },
  { text: 'RBAC', color: '#52c41a' },
]

const form = reactive({ username: 'admin', password: 'admin123' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
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

/* ════ Three.js：沿用粒子网络，色板对齐首页 hero ════ */

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
  for(int i=0;i<6;i++){
    float fi=float(i);
    vec2 c=vec2(0.5+0.36*sin(fi*1.3+t*0.22),0.5+0.36*cos(fi*0.9+t*0.16));
    float d=length(uv-c);
    v+=sin(d*18.0-t*2.0+fi*0.8)*exp(-d*3.8)*0.15;
  }
  return v;
}

void main(){
  vec2 uv=gl_FragCoord.xy/uRes;

  // 首页 hero：#0c1733 → #16306b → #1f6feb
  vec3 deep=vec3(0.047,0.090,0.200);
  vec3 mid=vec3(0.086,0.188,0.420);
  vec3 accent=vec3(0.122,0.435,0.920);
  vec3 col=mix(deep, mid, uv.y);
  col=mix(col, accent, pow(uv.y, 2.2) * 0.35);

  float n=noise(uv*3.5+uTime*0.1)*0.5+noise(uv*7.0-uTime*0.07)*0.22;
  col+=vec3(0.05,0.18,0.45)*n;

  float vl1=exp(-pow(length(uv-vec2(0.2,0.15))*1.4,2.0))*0.22;
  col+=vec3(0.25,0.52,1.0)*vl1;
  float vl2=exp(-pow(length(uv-vec2(0.85,0.75))*1.6,2.0))*0.16;
  col+=vec3(0.16,0.38,0.95)*vl2;

  float rip=neuralRipple(uv,uTime);
  col+=vec3(0.25,0.55,1.0)*rip*0.55;

  vec2 mp=uMouse*0.5+0.5;
  float mg=exp(-length(uv-mp)*3.6)*0.22;
  col+=vec3(0.25,0.55,1.0)*mg;

  float vig=1.0-smoothstep(0.30,0.95,length(uv-0.5)*1.45);
  col*=0.55+0.45*vig;

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
  float nx=noise3(pos*0.4+vec3(t*0.22,0,0));
  float ny=noise3(pos*0.4+vec3(0,t*0.22,1.5));
  float nz=noise3(pos*0.4+vec3(2.1,0,t*0.22));
  pos+=vec3(nx,ny,nz)*0.9;
  pos.z+=sin(length(pos.xy)*1.3-uTime*1.8)*0.28;
  float d=length(pos.xy-uMouse*6.0);
  pos.xy+=normalize(pos.xy-uMouse*6.0+0.001)*smoothstep(3.0,0.0,d)*1.5;
  vHue=nx;
  vAlpha=0.28+0.72*(0.5+0.5*sin(t+aPhase));
  vec4 mv=modelViewMatrix*vec4(pos,1.0);
  gl_PointSize=aSize*(260.0/-mv.z);
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
  float halo=exp(-r*4.5)*0.42;
  float glow=core+halo;
  // #409eff → #1f6feb
  vec3 col=mix(vec3(0.25,0.62,1.0),vec3(0.12,0.44,0.92),clamp(vHue+sin(uTime*0.35)*0.08,0.0,1.0));
  col=mix(col,vec3(1.0),core*0.45);
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
  float p=0.5+0.5*sin(uTime*1.5);
  vec3 col=mix(vec3(0.25,0.62,1.0),vec3(0.12,0.44,0.92),p);
  gl_FragColor=vec4(col,vAlpha*0.38);
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

  const bgGeo = new THREE.BufferGeometry()
  bgGeo.setAttribute('position', new THREE.BufferAttribute(
    new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, -1, 0, 1, 1, 0, -1, 1, 0]), 3))
  const bgMat = new THREE.ShaderMaterial({
    vertexShader: BG_VERT,
    fragmentShader: BG_FRAG,
    uniforms: {
      uTime: { value: 0 },
      uRes: { value: new THREE.Vector2(W, H) },
      uMouse: { value: new THREE.Vector2(0, 0) },
    },
    depthTest: false,
    depthWrite: false,
  })
  const bgMesh = new THREE.Mesh(bgGeo, bgMat)
  bgMesh.renderOrder = -999
  bgMesh.frustumCulled = false
  scene.add(bgMesh)

  const CNT = 2800
  const pos = new Float32Array(CNT * 3)
  const sizes = new Float32Array(CNT)
  const speeds = new Float32Array(CNT)
  const phases = new Float32Array(CNT)
  for (let i = 0; i < CNT; i++) {
    const r = Math.random() * 14
    const t = Math.random() * Math.PI * 2
    const p = Math.acos(2 * Math.random() - 1)
    pos[i * 3] = r * Math.sin(p) * Math.cos(t)
    pos[i * 3 + 1] = r * Math.sin(p) * Math.sin(t)
    pos[i * 3 + 2] = (Math.random() - 0.5) * 9
    sizes[i] = Math.random() * 2.6 + 0.4
    speeds[i] = Math.random() * 0.45 + 0.15
    phases[i] = Math.random() * Math.PI * 2
  }
  const pGeo = new THREE.BufferGeometry()
  pGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3))
  pGeo.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1))
  pGeo.setAttribute('aSpeed', new THREE.BufferAttribute(speeds, 1))
  pGeo.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1))
  const pMat = new THREE.ShaderMaterial({
    vertexShader: PARTICLE_VERT,
    fragmentShader: PARTICLE_FRAG,
    uniforms: {
      uTime: { value: 0 },
      uMouse: { value: new THREE.Vector2(0, 0) },
    },
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  })
  const particles = new THREE.Points(pGeo, pMat)
  scene.add(particles)

  const NODE_CNT = 64
  const nodes = []
  for (let i = 0; i < NODE_CNT; i++) {
    nodes.push(new THREE.Vector3(
      (Math.random() - 0.5) * 22,
      (Math.random() - 0.5) * 14,
      (Math.random() - 0.5) * 7,
    ))
  }
  const linePos = [], lineAlpha = []
  const MAX_D = 5.2
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
    vertexShader: LINE_VERT,
    fragmentShader: LINE_FRAG,
    uniforms: { uTime: { value: 0 } },
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  })
  const lines = new THREE.LineSegments(lGeo, lMat)
  scene.add(lines)

  const startTime = performance.now()
  function animate() {
    animId = requestAnimationFrame(animate)
    const t = (performance.now() - startTime) / 1000
    bgMat.uniforms.uTime.value = t
    bgMat.uniforms.uMouse.value.set(mouseX, mouseY)
    pMat.uniforms.uTime.value = t
    pMat.uniforms.uMouse.value.set(mouseX, mouseY)
    lMat.uniforms.uTime.value = t
    camera.position.x += (mouseX * 1.6 - camera.position.x) * 0.025
    camera.position.y += (mouseY * 0.9 - camera.position.y) * 0.025
    camera.lookAt(0, 0, 0)
    particles.rotation.y = t * 0.03
    particles.rotation.x = Math.sin(t * 0.016) * 0.07
    lines.rotation.y = t * 0.03
    lines.rotation.x = Math.sin(t * 0.016) * 0.07
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
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}

.bg-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: 0;
}

.chrome-layer {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
}
.chrome-top,
.chrome-bottom {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  letter-spacing: 1.5px;
  color: rgba(188, 208, 245, 0.75);
}
.chrome-top { top: 22px; }
.chrome-bottom { bottom: 20px; letter-spacing: 0.5px; font-size: 12px; color: rgba(214, 227, 255, 0.65); }
.chrome-brand { font-weight: 700; color: #eaf2ff; }
.chrome-status { color: #7ab8ff; }
.chrome-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #409eff;
  box-shadow: 0 0 8px rgba(64, 158, 255, 0.8);
  animation: pulse 2s ease-in-out infinite;
}
.chrome-sep { opacity: 0.4; }
.mono { font-family: Consolas, "Courier New", monospace; opacity: 0.85; }
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.8); }
}

.login-shell {
  position: relative;
  z-index: 2;
  width: min(440px, calc(100vw - 32px));
  border-radius: 16px;
  overflow: hidden;
  background: #fff;
  box-shadow:
    0 8px 24px rgba(20, 48, 107, 0.22),
    0 24px 64px rgba(12, 23, 51, 0.35);
  transition: transform 0.25s ease, box-shadow 0.3s ease;
}
.login-shell:hover {
  box-shadow:
    0 10px 28px rgba(20, 48, 107, 0.28),
    0 28px 72px rgba(12, 23, 51, 0.4);
}
.login-shell.shake {
  animation: shake 0.5s cubic-bezier(0.36, 0.07, 0.19, 0.97);
}
@keyframes shake {
  10%, 90% { transform: translateX(-3px); }
  20%, 80% { transform: translateX(4px); }
  30%, 50%, 70% { transform: translateX(-5px); }
  40%, 60% { transform: translateX(5px); }
}

/* 对齐首页 .hero */
.hero-band {
  display: flex;
  gap: 16px;
  align-items: center;
  padding: 22px 24px;
  color: #eaf2ff;
  background: linear-gradient(120deg, #0c1733 0%, #16306b 55%, #1f6feb 100%);
}
.hero-badge {
  flex: none;
  width: 56px;
  height: 56px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(135deg, #409eff, #6a5acd);
  box-shadow: 0 4px 14px rgba(64, 158, 255, 0.35);
}
.brand-name {
  margin: 0;
  font-size: 22px;
  font-weight: 800;
  letter-spacing: 0.4px;
  color: #fff;
}
.brand-sub {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: #bcd0f5;
}

.card-body {
  padding: 22px 24px 20px;
  background: #fff;
}

.feature-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 18px;
}
.htag {
  border: none;
  color: #fff;
  font-size: 11px;
  line-height: 1;
  padding: 6px 8px;
  border-radius: 4px;
  font-weight: 500;
}

.login-form :deep(.el-form-item) { margin-bottom: 14px; }
.login-form :deep(.el-form-item__error) { color: #f56c6c; }

.input-wrap { position: relative; width: 100%; }
.inp-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 2;
  color: #909399;
  font-size: 15px;
  pointer-events: none;
}

.login-form :deep(.platform-input .el-input__wrapper) {
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 10px;
  box-shadow: none;
  padding-left: 36px;
  transition: border-color 0.25s, box-shadow 0.25s, background 0.25s;
}
.login-form :deep(.platform-input .el-input__wrapper:hover),
.login-form :deep(.platform-input .el-input__wrapper.is-focus) {
  background: #fff;
  border-color: #409eff;
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.12);
}
.login-form :deep(.platform-input .el-input__inner) {
  color: #1f2d3d;
  font-size: 14px;
  height: 44px;
}
.login-form :deep(.platform-input .el-input__inner::placeholder) {
  color: #a8abb2;
}
.login-form :deep(.el-input__password) {
  color: #909399;
}

.submit-btn {
  position: relative;
  width: 100%;
  height: 46px;
  margin-top: 6px;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  overflow: hidden;
  background: linear-gradient(135deg, #1f6feb 0%, #409eff 100%);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 6px;
  box-shadow: 0 6px 18px rgba(31, 111, 235, 0.35);
  transition: transform 0.2s, box-shadow 0.25s;
}
.submit-btn:not(:disabled):hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 24px rgba(31, 111, 235, 0.45);
}
.submit-btn:active { transform: translateY(0); }
.submit-btn:disabled { cursor: not-allowed; opacity: 0.75; }

.btn-shine {
  position: absolute;
  top: 0;
  left: -80%;
  width: 55%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.28), transparent);
  transform: skewX(-20deg);
  animation: shine 4.5s ease-in-out infinite;
}
@keyframes shine {
  0% { left: -80%; opacity: 0; }
  15% { opacity: 1; }
  40% { left: 140%; opacity: 0; }
  100% { left: 140%; opacity: 0; }
}

.btn-spinner {
  display: inline-block;
  width: 20px;
  height: 20px;
  border: 2px solid rgba(255, 255, 255, 0.28);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.65s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.login-tip {
  margin-top: 16px;
  text-align: center;
  font-size: 12px;
  color: #909399;
}
.tip-sep { margin: 0 6px; opacity: 0.5; }
.tip-key {
  font-family: Consolas, "Courier New", monospace;
  color: #1f6feb;
  background: #ecf5ff;
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px solid #d9ecff;
}

@media (max-width: 480px) {
  .hero-band { padding: 18px 16px; }
  .card-body { padding: 16px; }
  .brand-name { font-size: 18px; }
}
</style>
