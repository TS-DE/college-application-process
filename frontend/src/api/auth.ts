import { httpAuth, isConnectionError, isUnauthorized } from './request'
import type { LoginPayload, RegisterPayload, TokenResponse, UserInfo } from '@/types/user'

/**
 * 认证接口（0.15.0 改造）。
 *
 * ## 为什么全部改用 httpAuth
 * 认证是「刷新页面必调一次」的链路，此前走默认实例（10 秒超时）：
 * 后端被 AI 请求占满时 `/auth/me` 排队 >10 秒即超时，
 * 而 store 又把超时误判成登录失效 —— 一条 AI 请求就能把用户踢下线。
 * 现在统一走 `httpAuth`（30 秒），与业务接口的超时预算分开。
 */

/** `/auth/me` 的指数退避重试间隔（毫秒）：300 → 900 → 2700，共 3 次 */
const ME_RETRY_DELAYS = [300, 900, 2700]

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export function login(data: LoginPayload) {
  return httpAuth<TokenResponse>({ url: '/auth/login', method: 'POST', data })
}

/** 注册（0.12.0：昵称 / 手机号可选） */
export function register(data: RegisterPayload) {
  return httpAuth<UserInfo>({ url: '/auth/register', method: 'POST', data })
}

/**
 * 拉取当前用户（连接失败时做 3 次指数退避重试）。
 *
 * 重试判据（重要）：
 *   · **401 立即抛出** —— token 真的失效，重试没有意义；
 *   · **连接失败才重试** —— 后端正在重启时毫秒级失败，重试很便宜；
 *   · **超时不重试** —— 30 秒超时已说明后端在但慢，重试只会把等待翻倍；
 *   · 其他 4xx（如 404 用户不存在）直接抛出。
 *
 * 三次重试总等待 <5 秒（连接失败是快速失败），不会让正常请求变慢。
 */
export async function fetchMe(): Promise<UserInfo> {
  let lastError: unknown

  for (let attempt = 0; attempt <= ME_RETRY_DELAYS.length; attempt += 1) {
    try {
      return await httpAuth<UserInfo>({ url: '/auth/me' })
    } catch (error) {
      lastError = error
      if (isUnauthorized(error) || !isConnectionError(error)) {
        throw error
      }
      const delay = ME_RETRY_DELAYS[attempt]
      if (delay === undefined) {
        break
      }
      console.warn(`[AUTH] /auth/me 连接失败，${delay}ms 后重试（第 ${attempt + 1} 次）`)
      await sleep(delay)
    }
  }

  throw lastError
}

/**
 * `fetchMe` 的语义化别名。
 *
 * 名字强调「有独立超时 + 重试」，供 `userStore.loadMe()` 使用，
 * 避免调用方误以为它是一次即失败的裸请求。
 */
export function fetchMeWithTimeout(): Promise<UserInfo> {
  return fetchMe()
}
