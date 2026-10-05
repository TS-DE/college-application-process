export type UserRole = 'admin' | 'student'

export interface UserInfo {
  id: number
  username: string
  role: UserRole
  created_at?: string
}

export interface LoginPayload {
  username: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: UserInfo
}
