export type UserRole = 'admin' | 'student'

export type Gender = 'male' | 'female' | 'other'

export interface UserInfo {
  id: number
  username: string
  role: UserRole
  /** 0.12.0 个人资料 */
  nickname?: string | null
  phone?: string | null
  gender?: Gender | null
  birthday?: string | null
  email?: string | null
  /** 展示名（后端 nickname 优先，其次 username） */
  display_name?: string | null
  created_at?: string
}

export interface LoginPayload {
  username: string
  password: string
}

/** 注册：账号 + 昵称 + 手机号（0.12.0 起与登录分离，符合接口隔离） */
export interface RegisterPayload {
  username: string
  password: string
  nickname?: string
  phone?: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: UserInfo
}
