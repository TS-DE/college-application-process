import { http } from './request'
import type { LoginPayload, RegisterPayload, TokenResponse, UserInfo } from '@/types/user'

export function login(data: LoginPayload) {
  return http<TokenResponse>({ url: '/auth/login', method: 'POST', data })
}

/** 注册（0.12.0：昵称 / 手机号可选） */
export function register(data: RegisterPayload) {
  return http<UserInfo>({ url: '/auth/register', method: 'POST', data })
}

export function fetchMe() {
  return http<UserInfo>({ url: '/auth/me' })
}
