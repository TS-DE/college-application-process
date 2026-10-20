import { defineStore } from 'pinia'
import { clearToken, getToken, isUnauthorized, setToken } from '@/api/request'
import { fetchMeWithTimeout, login as loginApi, register as registerApi } from '@/api/auth'
import type { LoginPayload, RegisterPayload, UserInfo, UserRole } from '@/types/user'

/**
 * `/auth/me` 结果的短期缓存时长（0.15.0）。
 *
 * 刷新页面后 Pinia 状态全丢，守卫必然触发一次 `/auth/me`。
 * 但同一个页面生命周期内可能连续发生多次导航（首页→查大学→志愿填报），
 * 每次都打一次接口既浪费又放大故障概率。60 秒内复用内存里的结果即可。
 */
const ME_CACHE_TTL = 60_000

interface State {
  token: string
  user: UserInfo | null
  /** 上次 `/auth/me` 成功的时间戳（0 表示从未成功） */
  lastMeLoadedAt: number
  /** 上次 `/auth/me` 的失败类型：空串=无失败 */
  meError: '' | 'network' | 'unauthorized'
}

export interface LoadMeOptions {
  /** true = 忽略 60 秒缓存，强制重新拉取 */
  force?: boolean
}

export const useUserStore = defineStore('user', {
  state: (): State => ({
    token: getToken(),
    user: null,
    lastMeLoadedAt: 0,
    meError: ''
  }),
  getters: {
    isLogin: (s) => !!s.token,
    role: (s): UserRole | '' => (s.user?.role as UserRole) || '',
    isAdmin: (s) => s.user?.role === 'admin',
    username: (s) => s.user?.username || '',
    /** 0.12.0：展示名（昵称优先），头像菜单与问候语都用它 */
    displayName: (s) => s.user?.display_name || s.user?.nickname || s.user?.username || '',
    /** 头像文字：取展示名首字，没有则用「考」 */
    avatarText: (s): string => {
      const name = s.user?.display_name || s.user?.nickname || s.user?.username || ''
      return name.slice(0, 1) || '考'
    },
    /** 上次失败是否仅为网络问题（登录态仍然有效） */
    isNetworkDegraded: (s) => s.meError === 'network'
  },
  actions: {
    async login(payload: LoginPayload) {
      const data = await loginApi(payload)
      this.token = data.access_token
      this.user = data.user
      this.lastMeLoadedAt = Date.now()
      this.meError = ''
      setToken(data.access_token)
      return data.user
    },
    /** 注册（不自动登录，由页面决定是否跳转登录） */
    async register(payload: RegisterPayload) {
      const user = await registerApi(payload)
      return user
    },
    /**
     * 拉取当前用户（0.15.0：区分「真失效」与「网络问题」）。
     *
     * ## 为什么这是「超时掉登录」的核心修复点
     * 旧实现 `catch { this.logout() }` 把三种情况一视同仁：
     *   ① 401 token 过期 —— 应当登出；
     *   ② 请求超时 / 后端没响应 —— **绝不能登出**，用户并没有失效；
     *   ③ 5xx 后端故障 —— 同样不能登出。
     * 只要 `/auth/me` 超时一次就清 token，于是一条 AI 请求就能把用户踢下线。
     *
     * 现在只有 401 才 logout；其余情况保留 token、`user` 置 null，
     * 由路由守卫按「网络降级」处理（放行 or 跳登录页并提示网络波动）。
     */
    async loadMe(options: LoadMeOptions = {}) {
      if (!this.token) return null

      // 60 秒内成功过 → 直接用内存结果，避免每次导航都打接口
      if (!options.force && this.user && Date.now() - this.lastMeLoadedAt < ME_CACHE_TTL) {
        return this.user
      }

      try {
        this.user = await fetchMeWithTimeout()
        this.lastMeLoadedAt = Date.now()
        this.meError = ''
        return this.user
      } catch (error) {
        if (isUnauthorized(error)) {
          // 真正的登录失效：token 过期 / 被吊销
          this.meError = 'unauthorized'
          console.warn('[AUTH] /auth/me 返回 401，登录已失效，清空 token')
          this.logout()
          return null
        }
        // 网络层问题（超时 / 断网 / 5xx）：保留 token，仅标记降级
        this.user = null
        this.meError = 'network'
        console.warn(
          '[AUTH] /auth/me 网络异常，保留登录态待重试：',
          (error as any)?.message || error
        )
        return null
      }
    },
    /** 资料更新后局部刷新用户信息（避免整页重新拉取） */
    patchUser(patch: Partial<UserInfo>) {
      if (this.user) this.user = { ...this.user, ...patch }
    },
    logout() {
      this.token = ''
      this.user = null
      this.lastMeLoadedAt = 0
      this.meError = ''
      clearToken()
    }
  }
})
