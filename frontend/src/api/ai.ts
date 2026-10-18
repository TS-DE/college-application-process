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
}

/** 志愿问答：use_rag=true 时后端先检索知识库再交给 Qwen3（0.12.0 起必须登录，会自动注入画像） */
export function chat(payload: ChatPayload) {
  // 0.7.2：AI 问答使用独立的长超时实例，避免污染首页/登录的短超时
  return httpAI<ChatResult>({ url: '/ai/chat', method: 'POST', data: payload, timeout: 120000 })
}

export function aiStatus() {
  return http<{ ai_enabled: boolean; ollama: boolean; message: string; model: string }>({
    url: '/ai/status'
  })
}

export function parseIntent(text: string, province = '河南') {
  return http<Record<string, any>>({ url: '/ai/parse-intent', method: 'POST', data: { text, province } })
}
