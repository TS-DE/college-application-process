import { http } from './request'
import type { KnowledgeFile, RagBackendInfo, SearchResult } from '@/types/knowledge'

/** 上传知识库文件（管理员） */
export function uploadKnowledge(file: File) {
  const form = new FormData()
  form.append('file', file)
  return http<{ code: number; msg: string; file_id: number; data: KnowledgeFile }>({
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

/** 检索：所有登录用户可用（考生端 RAG） */
export function searchKnowledge(query: string, topK = 5) {
  return http<SearchResult>({ url: '/knowledge/search', params: { query, top_k: topK } })
}

export function ragStatus() {
  return http<RagBackendInfo>({ url: '/knowledge/status' })
}

export function downloadUrl(id: number) {
  return `/api/knowledge/download/${id}`
}
