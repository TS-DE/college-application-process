import { http } from './request'
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

export function recommend(payload: RecommendPayload) {
  return http<RecommendResult>({ url: '/recommend', method: 'POST', data: payload })
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
