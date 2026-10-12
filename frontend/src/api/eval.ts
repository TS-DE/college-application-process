import { http, httpAI } from './request'

export interface EvalAggregate {
  context_precision?: number
  context_recall?: number
  mrr?: number
  ndcg?: number
  hit_rate?: number
  semantic_similarity?: number
  faithfulness?: number
  answer_relevance?: number
  answer_correctness?: number
  overall?: number
}

export interface Diagnosis {
  suggestion_id: string
  metric: string
  score: number
  threshold: number
  level: 'high' | 'medium' | 'low'
  problem: string
  suggestions: string[]
  param_changes: Record<string, any>
}

export interface EvalRunResult {
  report_id: string
  created_at: string
  dataset: string
  dataset_size: number
  aggregate: EvalAggregate
  grade: string
  duration_sec: number
  details: Array<{ question: string; answer: string; ground_truth: string; [key: string]: any }>
  chart_data: { bar: any; radar: any; trend: any }
  diagnoses: Diagnosis[]
  diagnosis_summary: string
}

export interface EvalSummary {
  report_id: string
  created_at: string
  grade: string
  dataset_size: number
  aggregate: EvalAggregate
}

export interface EvalDataset {
  dataset_id: string
  filename: string
  size_kb: number
  sample_count: number
}

export interface ChangeRecord {
  time: string
  action: string
  name?: string
  old_value?: any
  new_value?: any
  reason?: string
  report_id?: string
}

/** 一键运行评估（耗时较长，走 AI 长超时实例） */
export function runEval(payload: { dataset_id?: string; config_overrides?: Record<string, any> }) {
  return httpAI<EvalRunResult>({
    url: '/eval/run',
    method: 'POST',
    data: payload,
    timeout: 300000
  })
}

export function getReport(reportId: string) {
  return http<any>({ url: `/eval/report/${reportId}` })
}

export function listReports() {
  return http<{ total: number; data: EvalSummary[] }>({ url: '/eval/reports' })
}

/** 一键应用诊断建议（自动写回白名单参数） */
export function applySuggestion(payload: {
  report_id: string
  suggestion_id: string
  dry_run?: boolean
}) {
  return http<{
    applied: boolean
    need_restart: boolean
    changes: Array<Record<string, any>>
    message: string
  }>({
    url: '/eval/apply-suggestion',
    method: 'POST',
    data: payload
  })
}

export function rollbackEvaluate() {
  return http<{ applied: boolean; message: string }>({ url: '/eval/rollback', method: 'POST' })
}

export function listChanges() {
  return http<{ total: number; data: ChangeRecord[] }>({ url: '/eval/changes' })
}

export function listDatasets() {
  return http<{ total: number; data: EvalDataset[] }>({ url: '/eval/datasets' })
}

export function uploadDataset(file: File) {
  const form = new FormData()
  form.append('file', file)
  return httpAI<{ code: number; msg: string; dataset_id: string; sample_count: number }>({
    url: '/eval/datasets',
    method: 'POST',
    data: form,
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000
  })
}
