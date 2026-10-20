import { http, httpAI } from './request'

export interface ChatPayload {
  question: string
  context?: string
  use_rag?: boolean
  top_k?: number
  /** 0.9.0：是否叠加知识图谱双通道 */
  use_graph?: boolean
}

export interface ChatResult {
  answer: string
  source: string
  sources: string[]
  /** 0.9.1 三路融合调试字段 */
  graph_hit?: boolean
  mysql_hit?: boolean
  vector_hit?: boolean
  fusion_strategy?: string
  graph_cypher?: string
  graph_error?: string
  mysql_error?: string
  /** 0.12.0：本次回答是否注入了用户画像 */
  profile_injected?: boolean
  /** 0.13.0：本地 Agent 执行轨迹（用了哪些工具、耗时多少） */
  tool_trace?: Array<{
    name: string
    arguments?: Record<string, any>
    ok?: boolean
    skipped?: boolean
    elapsed_ms?: number
    error?: string
    preview?: string
  }>
  tools_used?: string[]
  steps?: number
  elapsed_ms?: number
  model?: string
}

/** 志愿问答：use_rag=true 时后端先检索知识库再交给 Qwen3（0.12.0 起必须登录，会自动注入画像） */
export function chat(payload: ChatPayload) {
  // 0.7.2：AI 问答使用独立的长超时实例，避免污染首页/登录的短超时
  // 0.13.0：本地 Agent 要「选工具 → 查库 → 生成」两轮推理，本机 CPU 下
  //         约 110-155 秒，因此超时放宽到 200 秒（页面显示思考动画）
  return httpAI<ChatResult>({ url: '/ai/chat', method: 'POST', data: payload, timeout: 200000 })
}

/** 心理师对话消息（0.13.0） */
export interface CounselorMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface CounselorResult {
  answer: string
  source: string
  model?: string | null
  elapsed_ms: number
  profile_injected: boolean
  error?: string | null
}

/**
 * 云端「心理师」多轮对话（0.13.0）。
 *
 * 与 `chat()` 的分工：
 *   · `chat()`      本地 qwen3:4b + 工具，查政策与数据，数据不出本机；
 *   · `counselor()` 云端 qwen3.7-flash，谈心 / 疏导 / 采集画像，**不降级到本地**。
 *
 * 超时给到 120 秒：云端要读画像 + 生成较长回复。
 */
export function counselorChat(messages: CounselorMessage[]) {
  return httpAI<CounselorResult>({
    url: '/ai/counselor',
    method: 'POST',
    data: { messages },
    timeout: 120000
  })
}

export function aiStatus() {
  return http<{ ai_enabled: boolean; ollama: boolean; message: string; model: string }>({
    url: '/ai/status'
  })
}

export function parseIntent(text: string, province = '河南') {
  return http<Record<string, any>>({ url: '/ai/parse-intent', method: 'POST', data: { text, province } })
}
