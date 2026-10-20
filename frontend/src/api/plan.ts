import { http, httpAI } from './request'

/**
 * 人机协同志愿规划（0.14.0）。
 *
 * 三段式交互对应后端 LangGraph 的三次调用：
 *   start  → 生成初稿（图停在 human_review 之前）
 *   resume → 注入意见、恢复执行（图跑到 END）
 *   state  → 读会话现场（刷新页面后恢复）
 */

export interface PlanItem {
  university_name?: string
  major_name?: string
  school_province?: string
  school_nature?: string
  min_score?: number
  min_rank?: number
  probability?: number
  tier?: string
  tier_label?: string
  tuition?: number | null
  duration?: string | null
  plan_count?: number | null
  subject_req?: string
  is_985?: boolean
  is_211?: boolean
  reason?: string
}

export type PlanTiers = {
  chong?: PlanItem[]
  wen?: PlanItem[]
  bao?: PlanItem[]
}

export interface PlanStartPayload {
  province: string
  category: string
  score?: number
  rank?: number
  year?: number
  preferences?: string
}

export interface PlanStartResult {
  thread_id: string
  rank: number
  draft_plan: PlanTiers
  summary: string
  intent: Record<string, any>
  stage: string
  elapsed_ms: number
  awaiting_feedback: boolean
}

export interface PlanChange {
  action: string
  tier: string
  university: string
  major: string
  reason: string
}

export interface PlanResumeResult {
  thread_id: string
  final_plan: PlanTiers
  changes: PlanChange[]
  feedback_parsed: Record<string, any>
  note: string
  rank?: number
  stage: string
  elapsed_ms: number
}

export interface PlanStateResult {
  thread_id: string
  stage: string
  rank?: number
  draft_plan: PlanTiers
  final_plan: PlanTiers
  changes: PlanChange[]
  note: string
  awaiting_feedback: boolean
}

/** 生成初稿：内部要查库算冲稳保，走长超时实例 */
export function startPlan(payload: PlanStartPayload) {
  return httpAI<PlanStartResult>({
    url: '/plan/start',
    method: 'POST',
    data: payload,
    timeout: 90000
  })
}

/** 提交修改意见并生成终稿（可能含一次大模型调用） */
export function resumePlan(threadId: string, userFeedback: string) {
  return httpAI<PlanResumeResult>({
    url: '/plan/resume',
    method: 'POST',
    data: { thread_id: threadId, user_feedback: userFeedback },
    timeout: 120000
  })
}

/** 读取会话现场 */
export function planState(threadId: string) {
  return http<PlanStateResult>({ url: `/plan/state/${threadId}` })
}

/** 依赖自检：langgraph 是否就绪 */
export function planHealth() {
  return http<{ available: boolean; engine: string; error?: string }>({
    url: '/plan/health'
  })
}
