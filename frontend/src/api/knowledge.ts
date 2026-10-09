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
    timeout: 120000
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
 * v2.5.2：检索涉及 embedding/LLM，使用独立长超时实例，避免阻塞短超时请求。
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
