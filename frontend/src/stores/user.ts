import { defineStore } from 'pinia'
import { clearToken, getToken, setToken } from '@/api/request'
import { fetchMe, login as loginApi, register as registerApi } from '@/api/auth'
import type { LoginPayload, RegisterPayload, UserInfo, UserRole } from '@/types/user'

interface State {
  token: string
  user: UserInfo | null
}

export const useUserStore = defineStore('user', {
  state: (): State => ({
    token: getToken(),
    user: null
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
    }
  },
  actions: {
    async login(payload: LoginPayload) {
      const data = await loginApi(payload)
      this.token = data.access_token
      this.user = data.user
      setToken(data.access_token)
      return data.user
    },
    /** 注册（不自动登录，由页面决定是否跳转登录） */
    async register(payload: RegisterPayload) {
      const user = await registerApi(payload)
      return user
    },
    async loadMe() {
      if (!this.token) return null
      try {
        this.user = await fetchMe()
      } catch {
        this.logout()
      }
      return this.user
    },
    /** 资料更新后局部刷新用户信息（避免整页重新拉取） */
    patchUser(patch: Partial<UserInfo>) {
      if (this.user) this.user = { ...this.user, ...patch }
    },
    logout() {
      this.token = ''
      this.user = null
      clearToken()
    }
  }
})
