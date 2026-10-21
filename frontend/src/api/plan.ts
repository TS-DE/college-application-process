import { http, httpAI } from './request'

/**
 * 人机协同志愿规划（0.14.0 引入，0.19.0 改为多轮回环）。
 *
 * 三阶段交互对应后端 LangGraph：
 *   start  → 生成初稿，图停在 human_review 节点**内部**的 interrupt()
 *   resume → 用 Command(resume=…) 把用户决定交回节点；可反复调用（多轮）
 *   state  → 读会话现场（刷新页面后恢复轮次与方案）
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

/** 每轮的历史记录（后端原样回传） */
export interface PlanHistoryEntry {
  round: number
  feedback: string
  changes: PlanChange[]
  note: string
}

export interface PlanStartResult {
  thread_id: string
  rank: number
  draft_plan: PlanTiers
  final_plan?: PlanTiers
  summary: string
  intent: Record<string, any>
  note?: string
  review_round?: number
  history?: PlanHistoryEntry[]
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
  review_round: number
  review_action: string
  history: PlanHistoryEntry[]
  /** true = 仍停在中断点，可继续提意见；false = 已定稿或到轮次上限 */
  awaiting_feedback: boolean
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
  intent?: Record<string, any>
  review_round: number
  review_action: string
  history: PlanHistoryEntry[]
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

/**
 * 提交一轮决定并继续执行。
 *
 * @param action revise = 继续改（默认）；accept = 就这版定稿
 */
export function resumePlan(
  threadId: string,
  userFeedback: string,
  action: 'revise' | 'accept' = 'revise'
) {
  return httpAI<PlanResumeResult>({
    url: '/plan/resume',
    method: 'POST',
    data: { thread_id: threadId, user_feedback: userFeedback, action },
    timeout: 120000
  })
}

/** 读取会话现场 */
export function planState(threadId: string) {
  return http<PlanStateResult>({ url: `/plan/state/${threadId}` })
}

/** 依赖自检：langgraph 是否就绪 */
export function planHealth() {
  return http<{
    available: boolean
    engine: string
    checkpointer?: string
    max_review_rounds?: number
    error?: string
  }>({ url: '/plan/health' })
}
