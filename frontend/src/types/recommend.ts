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
  /** 0.12.1：true 表示该省数据集缺少院校所在地维度（如吉林），无法按省份分布展示 */
  degraded?: boolean
  message?: string
  data: ProvinceMajorStat[]
}

export interface RecommendResult {
  chong: RecommendItem[]
  wen: RecommendItem[]
  bao: RecommendItem[]
  meta?: Record<string, any>
  /** 0.11.1：全国引擎算出的位次（与 chong/wen/bao 同源，便于前端展示） */
  rank?: number
  /** 0.11.1：全国引擎原始三档结果（键为 chong/wen/bao） */
  tiers?: Record<string, RecommendItem[]>
}
