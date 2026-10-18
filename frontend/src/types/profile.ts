/**
 * 用户画像相关类型（0.12.0）。
 *
 * 与后端 `schemas/profile.py` 一一对应，但按前端使用场景拆成多个小接口
 * （接口隔离：问卷题、作答、画像视图互不干扰）。
 */

export type QuestionType = 'single' | 'multiple' | 'text'

export interface SurveyOption {
  value: string
  label: string
}

export interface SurveyQuestion {
  id: string
  title: string
  type: QuestionType
  options: SurveyOption[]
  hint?: string | null
}

export interface SurveyQuestionResult {
  questions: SurveyQuestion[]
  /** true 表示大模型不可用，返回的是内置题库 */
  fallback: boolean
  message?: string | null
}

/** 「题目 id → 答案」；多选为 string[]，单/填空为 string */
export type SurveyAnswers = Record<string, string | string[]>

export interface ProfileBasicPayload {
  nickname?: string
  phone?: string
  gender?: 'male' | 'female' | 'other'
  birthday?: string
  email?: string
  /** 画像用的补充信息 */
  province?: string
  category?: string
  score?: number
}

export interface ProfileBasicInfo {
  username?: string
  nickname?: string | null
  gender?: string | null
  birthday?: string | null
  email?: string | null
  province?: string
  category?: string
  score?: number
}

/** 报告解析出的结构化特征 */
export interface ReportFeatures {
  mbti?: string
  holland?: string
  traits?: string[]
  interests?: string[]
  majors?: string[]
  summary?: string
}

export interface ProfileView {
  user_id: number
  basic_info: ProfileBasicInfo
  external_reports?: ReportFeatures | null
  survey_answers?: {
    questions?: SurveyQuestion[]
    answers?: SurveyAnswers
    features?: Record<string, any>
    submitted_at?: string
  } | null
  summary_text?: string | null
  source?: string
  updated_at?: string | null
  /** summary_text 非空时为 true */
  ready: boolean
}

export interface SummaryResult {
  summary_text: string
  source: string
  ready: boolean
  features?: {
    report?: ReportFeatures
    survey?: Record<string, any>
  } | null
}
