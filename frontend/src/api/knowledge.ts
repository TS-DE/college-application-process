import { http, httpAI } from './request'
import type { KnowledgeFile, RagBackendInfo, SearchResult } from '@/types/knowledge'

/** 上传知识库文件（管理员） */
export function uploadKnowledge(file: File) {
  const form = new FormData()
  form.append('file', file)
  return httpAI<{ code: number; msg: string; file_id: number; data: KnowledgeFile }>({
    url: '/knowledge/upload',
    method: 'POST',
    data: form,
    headers: { 'Content-Type': 'multipart/form-data' },
    // 0.10.0：扫描件 PDF 要走 OCR（每页约 20-35 秒，4 路并发），
    // 19 页的《高考志愿录取顺序.pdf》约需 2-3 分钟，超时从 2 分钟放宽到 10 分钟
    timeout: 600000
  })
}

export function listKnowledge(keyword = '') {
  return http<{ code: number; msg: string; total: number; data: KnowledgeFile[] }>({
    url: '/knowledge/list',
    params: { keyword }
  })
}

export function detailKnowledge(id: number) {
  return http<KnowledgeFile>({ url: `/knowledge/detail/${id}` })
}

export function deleteKnowledge(id: number) {
  return http<{ code: number; msg: string }>({ url: `/knowledge/delete/${id}`, method: 'DELETE' })
}

/** 检索：所有登录用户可用（考生端 RAG）
 * 0.7.2：检索涉及 embedding/LLM，使用独立长超时实例，避免阻塞短超时请求。
 */
export function searchKnowledge(query: string, topK = 5) {
  return httpAI<SearchResult>({ url: '/knowledge/search', params: { query, top_k: topK }, timeout: 30000 })
}

export function ragStatus() {
  return http<RagBackendInfo>({ url: '/knowledge/status' })
}

export function downloadUrl(id: number) {
  return `/api/knowledge/download/${id}`
}
