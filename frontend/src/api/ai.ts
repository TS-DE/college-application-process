import { http } from './request'

export interface ChatPayload {
  question: string
  context?: string
  use_rag?: boolean
  top_k?: number
}

export interface ChatResult {
  answer: string
  source: string
  sources: string[]
}

/** 志愿问答：use_rag=true 时后端先检索知识库再交给 Qwen3 */
export function chat(payload: ChatPayload) {
  return http<ChatResult>({ url: '/ai/chat', method: 'POST', data: payload, timeout: 120000 })
}

export function aiStatus() {
  return http<{ ai_enabled: boolean; ollama: boolean; message: string; model: string }>({
    url: '/ai/status'
  })
}

export function parseIntent(text: string, province = '河南') {
  return http<Record<string, any>>({ url: '/ai/parse-intent', method: 'POST', data: { text, province } })
}
