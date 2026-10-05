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

const request: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 60000
})

request.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

request.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const status = error?.response?.status
    const detail = error?.response?.data?.detail
    if (status === 401) {
      clearToken()
      ElMessage.error(detail || '登录已过期，请重新登录')
    } else if (status === 403) {
      ElMessage.error(detail || '没有权限访问该资源')
    } else {
      ElMessage.error(detail || error.message || '请求失败')
    }
    return Promise.reject(error)
  }
)

export async function http<T = any>(config: AxiosRequestConfig): Promise<T> {
  const resp = await request.request(config)
  return resp.data as T
}

export default request
