import axios from 'axios'
import { ElMessage } from 'element-plus'

import { useUserStore } from '../store/user'
import router from '../router'

const request = axios.create({
  baseURL: '/api',
  timeout: 10000
})

request.interceptors.request.use((config) => {
  const userStore = useUserStore()
  if (userStore.token) {
    config.headers.Authorization = `Bearer ${userStore.token}`
  }
  return config
})

request.interceptors.response.use(
  (response) => {
    const res = response.data
    // blob/arraybuffer（视频下载等）直接返回，勿按业务 JSON 解析
    if (response.config?.responseType === 'blob' || response.config?.responseType === 'arraybuffer') {
      return res
    }
    if (res.code !== undefined && res.code !== 0) {
      ElMessage.error(res.message || '请求错误')
      return Promise.reject(new Error(res.message || 'Error'))
    }
    return res
  },
  async (error) => {
    const status = error.response?.status
    let message = error.message
    const data = error.response?.data
    if (data instanceof Blob) {
      try {
        const text = await data.text()
        const json = JSON.parse(text)
        message = json.message || message
      } catch (_) {
        /* ignore non-json blob errors */
      }
    } else if (data?.message) {
      message = data.message
    }
    if (status === 401) {
      const userStore = useUserStore()
      userStore.logout()
      router.push('/login')
    }
    ElMessage.error(message || '网络错误')
    return Promise.reject(error)
  }
)

export default request
