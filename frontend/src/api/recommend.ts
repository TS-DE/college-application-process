import { http, httpAI } from './request'
import type { ProvinceMajorStatsResult, RecommendResult } from '@/types/recommend'

export interface RecommendPayload {
  province: string
  year: number
  category: string
  batch: string
  score?: number | null
  rank?: number | null
  filters?: Record<string, any>
  use_ai?: boolean
}

/** 生成冲/稳/保推荐。涉及 AI 理由时使用独立长超时实例，避免阻塞默认短超时。 */
export function recommend(payload: RecommendPayload) {
  const request = payload.use_ai ? httpAI : http
  return request<RecommendResult>({
    url: '/recommend',
    method: 'POST',
    data: payload,
    timeout: payload.use_ai ? 60000 : 30000
  })
}

/**
 * 维度下拉选项（0.11.1 新增）。
 * `categories_map` 是「省份 → 该省支持的科类」，用于前端做级联：
 * 北京只有「综合」，河南有「物理类 / 历史类」，新疆是「理科 / 文科」。
 */
export interface MetaOptionsResult {
  province: string
  years: number[]
  categories: string[]
  batches: string[]
  raw_batches: string[]
  provinces: string[]
  categories_map: Record<string, string[]>
  province_modes: Record<string, string>
  default: { year: number; category: string; batch: string }
}

export function metaOptions(province: string) {
  return http<MetaOptionsResult>({ url: '/meta/options', params: { province } })
}

/**
 * AI 环境状态（0.13.1）。
 *
 * 用于在 AI 助手页显示「政策库 / 图谱」两个指示灯：
 * 让用户直观知道「为什么有些问题答不上来」，而不是只看到一句「未查询到」。
 * 后端有 30 秒 TTL 缓存，可以放心在页面加载时调用。
 */
export interface AgentStatusResult {
  vector_ready: boolean
  vector_count: number
  vector_error?: string
  graph_ready: boolean
  graph_error?: string
  local_model: string
  /** fast=确定性链路（默认，6-15s）；agent=两轮工具推理（演示用） */
  agent_mode: 'fast' | 'agent'
  agent_enabled: boolean
  embedding_model?: string
}

export function agentStatus(refresh = false) {
  return http<AgentStatusResult>({ url: '/meta/agent-status', params: { refresh } })
}

export interface ScoreCheckPayload {
  province: string
  year: number
  category: string
  score: number
}

export interface ScoreCheckResult {
  rank: number
  rank_range?: string
  recommend_batch?: string
  below_all?: boolean
  lines?: { batch: string; control_score: number }[]
}

export function scoreCheck(payload: ScoreCheckPayload) {
  return http<ScoreCheckResult>({ url: '/meta/score-check', params: payload })
}

export function controlLines(province: string, year: number, category: string) {
  return http<{
    lines: { batch: string; control_score: number }[]
    bounds: Record<string, { min: number; max: number }>
    min_line: number | null
    full_score: number
  }>({ url: '/meta/control-lines', params: { province, year, category } })
}

/** 各省高校在河南投放的专业数量（首页中国地图） */
export function majorCountByProvince(params: {
  province?: string
  year?: number
  category?: string
  batch?: string
}) {
  return http<ProvinceMajorStatsResult>({ url: '/stats/major-count-by-province', params })
}

export function listUniversities(params: Record<string, any>) {
  return http<{ items: any[]; total: number }>({ url: '/universities', params })
}

export function listMajors(params: Record<string, any>) {
  return http<{ items: any[]; total: number }>({ url: '/majors', params })
}

export function provinceStats() {
  return http<{ items: { name: string; value: number }[] }>({ url: '/meta/province-stats' })
}
