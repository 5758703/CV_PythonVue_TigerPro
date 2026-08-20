import { createRouter, createWebHistory } from 'vue-router'

import { useUserStore } from '../store/user'
import Layout from '../layout/index.vue'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/register', name: 'register', component: () => import('../views/Register.vue'), meta: { public: true } },
  {
    path: '/',
    component: Layout,
    redirect: '/index',
    children: [
      { path: 'index', name: 'home', component: () => import('../views/Dashboard.vue'), meta: { title: '首页', icon: 'HomeFilled' } },
      { path: 'ai/model', name: 'aiModel', component: () => import('../views/ai/model/index.vue'), meta: { title: '模型管理' } },
      { path: 'ai/image', name: 'aiImage', component: () => import('../views/ai/image/index.vue'), meta: { title: '图片检测' } },
      { path: 'ai/video', name: 'aiVideo', component: () => import('../views/ai/video/index.vue'), meta: { title: '视频检测' } },
      { path: 'ai/track', name: 'aiTrack', component: () => import('../views/ai/track/index.vue'), meta: { title: '目标追踪' } },
      { path: 'ai/pose', name: 'aiPose', component: () => import('../views/ai/pose/index.vue'), meta: { title: '姿态估计' } },
      { path: 'ai/segment', name: 'aiSegment', component: () => import('../views/ai/segment/index.vue'), meta: { title: '图像分割' } },
      { path: 'ai/inpaint', name: 'aiInpaint', component: () => import('../views/ai/inpaint/index.vue'), meta: { title: '图像修复' } },
      { path: 'ai/camera', name: 'aiCamera', component: () => import('../views/ai/camera/index.vue'), meta: { title: '摄像头实时检测' } },
      { path: 'ai/face', name: 'aiFace', component: () => import('../views/ai/face/index.vue'), meta: { title: '人脸识别' } },
      { path: 'ai/reid', name: 'aiReid', component: () => import('../views/ai/reid/index.vue'), meta: { title: '行人重识别' } },
      { path: 'ai/mtmc', name: 'aiMtmc', component: () => import('../views/ai/mtmc/index.vue'), meta: { title: '跨镜重识别' } },
      { path: 'ai/handpose', name: 'aiHandpose', component: () => import('../views/ai/handpose/index.vue'), meta: { title: '手势识别' } },
      { path: 'ai/fall', name: 'aiFall', component: () => import('../views/ai/fall/index.vue'), meta: { title: '跌倒检测' } },
      { path: 'ai/alert', name: 'aiAlert', component: () => import('../views/ai/alert/index.vue'), meta: { title: '检测告警' } },
      { path: 'ai/text', name: 'aiText', component: () => import('../views/ai/text/index.vue'), meta: { title: '文本分析' } },
      { path: 'ai/imgcls', name: 'aiImgcls', component: () => import('../views/ai/imgcls/index.vue'), meta: { title: '图像分类' } },
      { path: 'ai/livecls', name: 'aiLivecls', component: () => import('../views/ai/livecls/index.vue'), meta: { title: '实时分类' } },
      { path: 'ai/ocr', name: 'aiOcr', component: () => import('../views/ai/ocr/index.vue'), meta: { title: '文字识别' } },
      { path: 'ai/paddleocr', name: 'aiPaddleOcr', component: () => import('../views/ai/paddleocr/index.vue'), meta: { title: 'PaddleOCR 识别' } },
      { path: 'ai/table', name: 'aiTable', component: () => import('../views/ai/table/index.vue'), meta: { title: '表格识别' } },
      // 车辆追踪已并入目标追踪场景；保留路径兼容旧书签/菜单
      {
        path: 'ai/vehicle',
        name: 'aiVehicle',
        redirect: { path: '/ai/track', query: { scenario: 'vehicle' } },
        meta: { title: '车辆追踪' },
      },
      {
        path: 'ai/absence',
        name: 'aiAbsence',
        redirect: { path: '/ai/track', query: { scenario: 'absence' } },
        meta: { title: '人员离岗检测' },
      },
      { path: 'ai/generate', name: 'aiGenerate', component: () => import('../views/ai/generate/index.vue'), meta: { title: '文本生成' } },
      { path: 'ai/ner', name: 'aiNer', component: () => import('../views/ai/ner/index.vue'), meta: { title: '实体识别' } },
      { path: 'ai/qa', name: 'aiQa', component: () => import('../views/ai/qa/index.vue'), meta: { title: '智能问答' } },
      { path: 'ai/asr', name: 'aiAsr', component: () => import('../views/ai/asr/index.vue'), meta: { title: '语音识别' } },
      { path: 'ai/talker', name: 'aiTalker', component: () => import('../views/ai/talker/index.vue'), meta: { title: '数字人合成' } },
      { path: 'ai/tts', name: 'aiTts', component: () => import('../views/ai/tts/index.vue'), meta: { title: '文本转语音' } },
      { path: 'system/user', name: 'sysUser', component: () => import('../views/system/user/index.vue'), meta: { title: '用户管理' } },
      { path: 'system/role', name: 'sysRole', component: () => import('../views/system/role/index.vue'), meta: { title: '角色管理' } },
      { path: 'system/dept', name: 'sysDept', component: () => import('../views/system/dept/index.vue'), meta: { title: '部门管理' } },
      { path: 'system/job', name: 'sysJob', component: () => import('../views/system/job/index.vue'), meta: { title: '岗位管理' } },
      { path: 'system/menu', name: 'sysMenu', component: () => import('../views/system/menu/index.vue'), meta: { title: '菜单管理' } },
      { path: 'system/open-app', name: 'sysOpenApp', component: () => import('../views/system/openApp/index.vue'), meta: { title: '开放平台' } },
      { path: 'camera', name: 'camera', component: () => import('../views/camera/index.vue'), meta: { title: '摄像头管理' } },
      { path: 'camera/wall', name: 'cameraWall', component: () => import('../views/camera/wall/index.vue'), meta: { title: '实时监控大屏' } },
      { path: 'ai/water', name: 'aiWater', component: () => import('../views/ai/water/index.vue'), meta: { title: '水位检测' } },
      { path: 'ai/badminton', name: 'aiBadminton', component: () => import('../views/ai/badminton/index.vue'), meta: { title: '羽毛球分析' } },
      { path: 'ai/training', name: 'aiTraining', component: () => import('../views/ai/training/index.vue'), meta: { title: '模型训练' } }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/index' }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

router.beforeEach(async (to) => {
  const store = useUserStore()

  const safeRedirect = (raw) => {
    const value = Array.isArray(raw) ? raw[0] : raw
    if (typeof value !== 'string') return null
    let path = value.trim()
    try {
      path = decodeURIComponent(path)
    } catch {
      /* keep */
    }
    if (!path.startsWith('/') || path.startsWith('//') || path.includes('://')) return null
    return path
  }

  if (to.meta.public) {
    if (store.token) {
      return safeRedirect(to.query.redirect) || { path: '/index' }
    }
    return true
  }

  if (!store.token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // 已登录但未加载权限 -> 拉取
  if (!store.roles.length) {
    try {
      await store.loadInfo()
    } catch (e) {
      store.logout()
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }
  return true
})

export default router
