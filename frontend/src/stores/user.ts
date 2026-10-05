import { defineStore } from 'pinia'
import { clearToken, getToken, setToken } from '@/api/request'
import { fetchMe, login as loginApi, register as registerApi } from '@/api/auth'
import type { LoginPayload, UserInfo, UserRole } from '@/types/user'

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
    username: (s) => s.user?.username || ''
  },
  actions: {
    async login(payload: LoginPayload) {
      const data = await loginApi(payload)
      this.token = data.access_token
      this.user = data.user
      setToken(data.access_token)
      return data.user
    },
    async register(payload: LoginPayload) {
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
    logout() {
      this.token = ''
      this.user = null
      clearToken()
    }
  }
})
