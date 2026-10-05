export interface RecommendItem {
  university_code?: string
  university_name: string
  major_name: string
  min_score?: number
  min_rank?: number
  rank_diff?: number
  probability?: number
  school_province?: string
  school_nature?: string
  tuition?: number
  plan_count?: number
  duration?: string
  subject_req?: string
  tier?: 'chong' | 'wen' | 'bao'
  tier_label?: string
  reason?: string
  is_985?: boolean
  is_211?: boolean
  is_double_first_class?: boolean
}

export interface ProvinceMajorStat {
  province: string
  university_count: number
  major_count: number
}

export interface ProvinceMajorStatsResult {
  code: number
  msg: string
  province: string
  year: number
  category: string
  batch: string
  total_major: number
  total_university: number
  data: ProvinceMajorStat[]
}

export interface RecommendResult {
  chong: RecommendItem[]
  wen: RecommendItem[]
  bao: RecommendItem[]
  meta?: Record<string, any>
}
