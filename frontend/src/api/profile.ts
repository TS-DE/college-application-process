/**
 * 用户画像 API 封装（0.12.0）。
 *
 * 迪米特法则：组件只调用这里的函数，不感知 URL、超时、字段名，
 * 也不直接操作后端字段。后端结构调整时只改这一层。
 */
import { http, httpAI } from './request'
import type {
  ProfileBasicPayload,
  ProfileView,
  SummaryResult,
  SurveyAnswers,
  SurveyQuestion,
  SurveyQuestionResult
} from '@/types/profile'

/** 读取当前登录用户的画像 */
export function fetchProfile() {
  return http<ProfileView>({ url: '/profile' })
}

/** 完善 / 修改基础资料（个人主页） */
export function updateProfileBasic(payload: ProfileBasicPayload) {
  return http<ProfileView>({ url: '/profile/basic', method: 'PUT', data: payload })
}

/** 问卷可选领域（勾选框数据源） */
export function fetchProfileDomains() {
  return http<string[]>({ url: '/profile/domains' })
}

/** 途径 B：生成业务问卷（大模型可能较慢，用长超时实例） */
export function generateSurvey(domains: string[], count = 5) {
  return httpAI<SurveyQuestionResult>({
    url: '/profile/survey/questions',
    method: 'POST',
    data: { domains, count }
  })
}

/** 途径 B：提交问卷作答并生成画像 */
export function submitSurvey(questions: SurveyQuestion[], answers: SurveyAnswers) {
  return httpAI<SummaryResult>({
    url: '/profile/survey/submit',
    method: 'POST',
    data: { questions, answers }
  })
}

/** 途径 A：上传报告文本并解析 */
export function uploadReport(text: string, sourceHint?: string) {
  return httpAI<SummaryResult>({
    url: '/profile/report/upload',
    method: 'POST',
    data: { text, source_hint: sourceHint || undefined }
  })
}

/**
 * 途径 A（文件版）：上传 PDF / 图片 / 文档报告。
 *
 * ★ 隐私隔离（0.13.0 物理级解耦）：
 *   接口为 `/profile/report-upload`，与知识库上传**不是同一条链路**——
 *   文件落在 `{UPLOAD_ROOT}/reports/`、解析后立即删除、**不写 Chroma**、
 *   不写 `knowledge_files` 台账，管理员的知识库页看不到。
 *   必须登录；走独立长超时实例（OCR + 大模型解析可能较慢）。
 */
export function uploadReportFile(file: File) {
  const form = new FormData()
  form.append('file', file)
  return httpAI<SummaryResult>({
    url: '/profile/report-upload',
    method: 'POST',
    data: form,
    timeout: 180000
  })
}

/** 手动重算画像 */
export function rebuildProfile() {
  return httpAI<SummaryResult>({ url: '/profile/summary/rebuild', method: 'POST' })
}

/** 清空画像（不影响账号） */
export function clearProfile() {
  return http<{ code: number; msg: string }>({ url: '/profile', method: 'DELETE' })
}
