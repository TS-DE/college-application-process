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

/** 手动重算画像 */
export function rebuildProfile() {
  return httpAI<SummaryResult>({ url: '/profile/summary/rebuild', method: 'POST' })
}

/** 清空画像（不影响账号） */
export function clearProfile() {
  return http<{ code: number; msg: string }>({ url: '/profile', method: 'DELETE' })
}
