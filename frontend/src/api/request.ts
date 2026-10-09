import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

const TOKEN_KEY = 'gaokao_token'

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

// v2.5.2：默认超时从 60000ms 下调到 10000ms，避免后端偶发阻塞时前端长时间挂起。
// AI / 文件上传等长耗时接口请使用 aiRequest 或在请求配置里显式覆盖 timeout。
const DEFAULT_TIMEOUT = 10000

const request: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: DEFAULT_TIMEOUT
})

const aiRequest: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 120000
})

function addAuthInterceptor(instance: AxiosInstance) {
  instance.interceptors.request.use((config) => {
    const token = getToken()
    if (token) {
      config.headers = config.headers || {}
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  })

  instance.interceptors.response.use(
    (resp) => resp,
    (error) => {
      const status = error?.response?.status
      const detail = error?.response?.data?.detail
      if (status === 401) {
        clearToken()
        ElMessage.error(detail || '登录已过期，请重新登录')
      } else if (status === 403) {
        ElMessage.error(detail || '没有权限访问该资源')
      } else if (error.code === 'ECONNABORTED' || (error.message || '').includes('timeout')) {
        ElMessage.error(detail || '请求超时，请稍后重试')
      } else {
        ElMessage.error(detail || error.message || '请求失败')
      }
      return Promise.reject(error)
    }
  )
}

addAuthInterceptor(request)
addAuthInterceptor(aiRequest)

export async function http<T = any>(config: AxiosRequestConfig): Promise<T> {
  const resp = await request.request(config)
  return resp.data as T
}

export async function httpAI<T = any>(config: AxiosRequestConfig): Promise<T> {
  const resp = await aiRequest.request(config)
  return resp.data as T
}

export { aiRequest }
export default request
