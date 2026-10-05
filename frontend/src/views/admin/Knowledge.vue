<template>
  <div class="page">
    <h2 class="title">知识库管理</h2>

    <el-card shadow="never">
      <div class="header">
        <el-button type="primary" @click="showUpload = true">上传</el-button>
        <div class="right">
          <el-input v-model="store.keyword" placeholder="搜索文件名" style="width: 260px" clearable @keyup.enter="store.loadList()" />
          <el-button @click="store.loadList()">搜索</el-button>
        </div>
      </div>

      <el-table :data="store.files" v-loading="store.loading" size="small">
        <el-table-column prop="filename" label="文件名称" min-width="260" show-overflow-tooltip />
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ fmtSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column prop="upload_time" label="上传时间" width="170" />
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button link type="primary" @click="viewDetail(row)">详情</el-button>
            <el-button link type="danger" @click="removeFile(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <UploadModal v-model="showUpload" @success="store.loadList()" />

    <el-dialog v-model="detailVisible" title="文件详情" width="460px">
      <el-descriptions :column="1" border size="small" v-if="detail">
        <el-descriptions-item label="文件名">{{ detail.filename }}</el-descriptions-item>
        <el-descriptions-item label="存储名">{{ detail.stored_filename }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{ detail.file_type }}</el-descriptions-item>
        <el-descriptions-item label="大小">{{ fmtSize(detail.file_size) }}</el-descriptions-item>
        <el-descriptions-item label="上传时间">{{ detail.upload_time }}</el-descriptions-item>
        <el-descriptions-item label="切片数">{{ detail.chunk_count }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="detail.status === '已向量化' ? 'success' : 'info'">{{ detail.status }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="上传者">{{ detail.uploader_name || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import UploadModal from '@/components/UploadModal.vue'
import { useKnowledgeStore } from '@/stores/knowledge'
import { detailKnowledge } from '@/api/knowledge'
import type { KnowledgeFile } from '@/types/knowledge'

const store = useKnowledgeStore()
const showUpload = ref(false)
const detailVisible = ref(false)
const detail = ref<KnowledgeFile | null>(null)

function fmtSize(n?: number) {
  if (n == null) return '-'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

async function viewDetail(row: KnowledgeFile) {
  try {
    detail.value = await detailKnowledge(row.id)
  } catch {
    detail.value = row
  }
  detailVisible.value = true
}

async function removeFile(row: KnowledgeFile) {
  try {
    await ElMessageBox.confirm(`确定删除「${row.filename}」？向量与文件会一并删除。`, '提示', {
      type: 'warning'
    })
  } catch {
    return
  }
  await store.remove(row.id)
  ElMessage.success('已删除')
}

onMounted(() => store.loadList())
</script>

<style scoped>
.title {
  margin: 0 0 14px;
}
.header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 14px;
}
.right {
  display: flex;
  gap: 8px;
}
</style>
