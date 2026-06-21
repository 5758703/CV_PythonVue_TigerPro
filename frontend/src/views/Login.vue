<template>
  <div class="login-bg">
    <div class="grid-overlay"></div>
    <div class="login-box">
      <div class="brand">
        <div class="brand-logo">CV</div>
        <div class="brand-text">
          <h1>Tiger AI Platform</h1>
          <p>多任务 AI 模型管理与测试平台 · 检测 / 文本 / 图像分类</p>
        </div>
      </div>
      <el-form ref="formRef" :model="form" :rules="rules" class="login-form" @keyup.enter="onSubmit">
        <el-form-item prop="username">
          <el-input v-model="form.username" size="large" placeholder="用户名" :prefix-icon="User" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" size="large" type="password" placeholder="密码" show-password :prefix-icon="Lock" />
        </el-form-item>
        <el-button type="primary" size="large" class="login-btn" :loading="loading" @click="onSubmit">
          登 录
        </el-button>
      </el-form>
      <div class="login-tip">
        默认账号：admin / admin123（超管）&nbsp;·&nbsp;tiger / 123456（普通）
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'

import { login } from '../api/auth'
import { useUserStore } from '../store/user'

const router = useRouter()
const store = useUserStore()

const formRef = ref()
const loading = ref(false)
const form = reactive({ username: 'admin', password: 'admin123' })

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
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
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-bg {
  position: relative;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: radial-gradient(circle at 20% 20%, #1b2a6b 0%, #0a1230 45%, #050814 100%);
  overflow: hidden;
}
.grid-overlay {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(64, 158, 255, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(64, 158, 255, 0.08) 1px, transparent 1px);
  background-size: 40px 40px;
  mask-image: radial-gradient(circle at center, #000 30%, transparent 80%);
}
.login-box {
  position: relative;
  width: 400px;
  padding: 40px 36px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.06);
  backdrop-filter: blur(14px);
  border: 1px solid rgba(120, 170, 255, 0.25);
  box-shadow: 0 12px 50px rgba(0, 0, 0, 0.5), inset 0 0 30px rgba(64, 158, 255, 0.06);
}
.brand {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 30px;
}
.brand-logo {
  width: 52px;
  height: 52px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  font-size: 22px;
  color: #fff;
  background: linear-gradient(135deg, #409eff, #6a5acd);
  box-shadow: 0 6px 18px rgba(64, 158, 255, 0.5);
}
.brand-text h1 {
  margin: 0;
  font-size: 20px;
  color: #eaf2ff;
  letter-spacing: 1px;
}
.brand-text p {
  margin: 4px 0 0;
  font-size: 12px;
  color: #7f95c4;
}
.login-form :deep(.el-input__wrapper) {
  background: rgba(255, 255, 255, 0.04);
  box-shadow: 0 0 0 1px rgba(120, 170, 255, 0.25) inset;
}
.login-form :deep(.el-input__inner) {
  color: #eaf2ff;
}
.login-btn {
  width: 100%;
  margin-top: 6px;
  letter-spacing: 6px;
  background: linear-gradient(135deg, #409eff, #6a5acd);
  border: none;
}
.login-tip {
  margin-top: 18px;
  text-align: center;
  font-size: 12px;
  color: #6b80ad;
}
</style>
