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

/**
 * 401 时的回调（0.15.1）。
 *
 * ## 为什么用回调而不是直接 import store
 * `request.ts` 是基础设施层，`stores/user.ts` 又 import 了 `api/auth.ts`，
 * 而 `api/auth.ts` 依赖 `request.ts` —— 直接 import store 会形成**循环依赖**
 * （打包后表现为 `useUserStore is not defined` 或 undefined 的诡异报错）。
 * 用回调注入把依赖方向反过来：基础设施只声明「需要通知」，由应用入口装配。
 *
 * 注册方：`main.ts`（pinia 安装之后）。
 */
let onUnauthorized: (() => void) | null = null

export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

// 0.7.2：默认超时从 60000ms 下调到 10000ms，避免后端偶发阻塞时前端长时间挂起。
// AI / 文件上传等长耗时接口请使用 aiRequest 或在请求配置里显式覆盖 timeout。
const DEFAULT_TIMEOUT = 10000

/**
 * 认证类接口专用超时（0.15.0）。
 *
 * 认证是「刷新页面必调一次」的链路，一旦超时被误判成登录失效，
 * 用户就被踢出登录。给它 30 秒独立预算：既比默认 10 秒宽容，
 * 又远小于后端的 `AUTH_TIMEOUT_SECONDS` 兜底之外的人工排查时间。
 */
const AUTH_TIMEOUT = 30000

const request: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: DEFAULT_TIMEOUT
})

const aiRequest: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 120000
})

/**
 * 认证专用实例（0.15.0）。
 *
 * 为什么单独一个：`request` 的 10 秒超时对「后端正被 AI 请求占满」的场景太紧，
 * 而 `aiRequest` 的 120 秒又太久（登录按钮会转两分钟）。
 * 复用同一套 token 注入与错误拦截（`addAuthInterceptor`），只是超时不同。
 */
const authRequest: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: AUTH_TIMEOUT
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
        // 0.15.1：只清 localStorage 会让 Pinia 里的 token 残留，
        // 表现为「导航栏显示已登录、实际所有请求 401」。必须同步 store 状态。
        clearToken()
        onUnauthorized?.()
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
addAuthInterceptor(authRequest)

export async function http<T = any>(config: AxiosRequestConfig): Promise<T> {
  const resp = await request.request(config)
  return resp.data as T
}

export async function httpAI<T = any>(config: AxiosRequestConfig): Promise<T> {
  const resp = await aiRequest.request(config)
  return resp.data as T
}

/** 认证类接口专用（0.15.0）：30 秒超时，供 login / register / fetchMe 使用 */
export async function httpAuth<T = any>(config: AxiosRequestConfig): Promise<T> {
  const resp = await authRequest.request(config)
  return resp.data as T
}

/**
 * 判断一个 axios 错误是否属于「网络层问题」。
 *
 * 只有真正的 **401** 才代表登录失效；超时、断网、5xx 都属于「后端暂时不可用」，
 * 必须保留 token —— 这是本次「超时掉登录」修复的核心判据，
 * 因此收敛成函数供 store 与路由守卫共用，避免各处各写一套。
 */
export function isNetworkError(error: any): boolean {
  if (!error) return false
  const status = error?.response?.status
  // 无响应 = 超时 / 断网 / CORS / 后端进程没起
  if (!error.response) return true
  // 5xx：后端自己出问题，不应牵连登录态
  if (status >= 500) return true
  const code = error.code || ''
  if (code === 'ECONNABORTED' || code === 'ETIMEDOUT' || code === 'ERR_NETWORK') return true
  return /timeout/i.test(error.message || '')
}

/** 是否「真的登录失效」（仅 401） */
export function isUnauthorized(error: any): boolean {
  return error?.response?.status === 401
}

/**
 * 是否「连接层失败」（后端没起 / 网络不可达）——**只有这一类值得重试**。
 *
 * ## 为什么超时不重试
 * `AUTH_TIMEOUT` 是 30 秒。若超时也重试 3 次，一次刷新就要白屏
 * `30 × 4 + 退避 ≈ 2 分钟`，与「关闭后端后应尽快提示网络异常」的诉求直接冲突。
 * 而超时本身说明**后端在、只是慢**，立刻重试大概率还是慢，只会加倍等待。
 *
 * 连接失败则相反：毫秒级返回，重试 3 次总耗时 <5 秒，能扛住后端正在重启的窗口期。
 */
export function isConnectionError(error: any): boolean {
  if (!error || error.response) return false
  const code = error.code || ''
  if (code === 'ERR_NETWORK' || code === 'ECONNREFUSED' || code === 'ECONNRESET') return true
  return /network error|failed to fetch/i.test(error.message || '')
}

export { aiRequest, authRequest }
export default request
