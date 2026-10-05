export interface KnowledgeFile {
  id: number
  filename: string
  stored_filename: string
  file_type?: string
  file_size?: number
  upload_time?: string
  chunk_count: number
  status?: string
  uploaded_by?: number
  uploader_name?: string
}

export interface ChunkHit {
  text: string
  metadata: Record<string, any>
  distance?: number
}

export interface SearchResult {
  code: number
  msg: string
  query: string
  data: ChunkHit[]
}

export interface RagBackendInfo {
  vector_store: string
  persist_path: string
  collection: string
  embedding_model: string
  embedding_provider: string
  ready: boolean
  error?: string | null
  count: number
}
