<template>
  <div class="page">
    <h2 class="title">后台首页</h2>

    <div class="cards">
      <el-card shadow="never" class="stat">
        <div class="num">{{ store.files.length }}</div>
        <div class="lbl">知识库文件</div>
      </el-card>
      <el-card shadow="never" class="stat">
        <div class="num">{{ totalChunks }}</div>
        <div class="lbl">向量切片总数</div>
      </el-card>
      <el-card shadow="never" class="stat">
        <div class="num">{{ store.backend?.collection || '-' }}</div>
        <div class="lbl">Chroma 集合</div>
      </el-card>
      <el-card shadow="never" class="stat">
        <div class="num">{{ store.backend?.embedding_model || '-' }}</div>
        <div class="lbl">Embedding 模型</div>
      </el-card>
    </div>

    <el-card shadow="never" class="block">
      <template #header><b>向量库状态</b></template>
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="存储">{{ store.backend?.vector_store || '-' }}</el-descriptions-item>
        <el-descriptions-item label="可用">
          <el-tag :type="store.backend?.ready ? 'success' : 'danger'">
            {{ store.backend?.ready ? '正常' : '不可用' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="Embedding 提供方">{{ store.backend?.embedding_provider || '-' }}</el-descriptions-item>
        <el-descriptions-item label="持久化目录">{{ store.backend?.persist_path || '-' }}</el-descriptions-item>
        <el-descriptions-item label="错误信息">{{ store.backend?.error || '无' }}</el-descriptions-item>
      </el-descriptions>
      <div class="actions">
        <el-button type="primary" @click="$router.push('/admin/knowledge')">进入知识库管理</el-button>
        <el-button @click="store.loadBackendInfo()">刷新状态</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useKnowledgeStore } from '@/stores/knowledge'

const store = useKnowledgeStore()
const totalChunks = computed(() => store.files.reduce((s, f) => s + (f.chunk_count || 0), 0))

onMounted(async () => {
  await Promise.all([store.loadList(), store.loadBackendInfo()])
})
</script>

<style scoped>
.title {
  margin: 0 0 14px;
}
.cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 16px;
}
.stat {
  text-align: center;
}
.num {
  font-size: 22px;
  font-weight: 700;
  color: var(--primary);
  word-break: break-all;
}
.lbl {
  font-size: 13px;
  color: var(--text-muted);
  margin-top: 4px;
}
.block {
  margin-bottom: 16px;
}
.actions {
  margin-top: 14px;
  display: flex;
  gap: 10px;
}
@media (max-width: 900px) {
  .cards {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
