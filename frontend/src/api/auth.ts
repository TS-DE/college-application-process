import { http } from './request'
import type { LoginPayload, TokenResponse, UserInfo } from '@/types/user'

export function login(data: LoginPayload) {
  return http<TokenResponse>({ url: '/auth/login', method: 'POST', data })
}

export function register(data: LoginPayload) {
  return http<UserInfo>({ url: '/auth/register', method: 'POST', data })
}

export function fetchMe() {
  return http<UserInfo>({ url: '/auth/me' })
}
