import { defineStore } from 'pinia'
import {
  deleteKnowledge as deleteApi,
  listKnowledge,
  ragStatus,
  searchKnowledge,
  uploadKnowledge
} from '@/api/knowledge'
import type { ChunkHit, KnowledgeFile, RagBackendInfo } from '@/types/knowledge'

interface State {
  files: KnowledgeFile[]
  loading: boolean
  keyword: string
  backend: RagBackendInfo | null
}

export const useKnowledgeStore = defineStore('knowledge', {
  state: (): State => ({
    files: [],
    loading: false,
    keyword: '',
    backend: null
  }),
  actions: {
    async loadList() {
      this.loading = true
      try {
        const res = await listKnowledge(this.keyword)
        this.files = res.data
      } finally {
        this.loading = false
      }
    },
    async upload(file: File) {
      const res = await uploadKnowledge(file)
      await this.loadList()
      return res
    },
    async remove(id: number) {
      await deleteApi(id)
      await this.loadList()
    },
    async search(query: string, topK = 5): Promise<ChunkHit[]> {
      const res = await searchKnowledge(query, topK)
      return res.data || []
    },
    async loadBackendInfo() {
      try {
        this.backend = await ragStatus()
      } catch {
        this.backend = null
      }
      return this.backend
    }
  }
})
