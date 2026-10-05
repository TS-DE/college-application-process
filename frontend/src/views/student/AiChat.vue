<template>
  <div class="page chat-page">
    <el-card shadow="never" class="chat-card">
      <template #header>
        <div class="head">
          <b>AI 志愿助手</b>
          <el-switch v-model="useRag" active-text="知识库增强(RAG)" />
          <el-tag v-if="!userStore.isLogin" type="warning" size="small" @click="$router.push('/login')">
            登录后可用
          </el-tag>
        </div>
      </template>

      <div ref="scrollEl" class="messages">
        <ChatBubble role="ai" text="你好，我是高考志愿填报助手。可以问我填报政策、批次规则、冲稳保策略等问题。" />
        <ChatBubble
          v-for="(m, i) in messages"
          :key="i"
          :role="m.role"
          :text="m.text"
          :sources="m.sources"
        />
        <div v-if="thinking" class="muted">AI 正在思考…（本地大模型，约需几秒）</div>
      </div>

      <div class="composer">
        <el-input
          v-model="question"
          type="textarea"
          :rows="2"
          placeholder="例如：河南本科批平行志愿怎么填报？"
          @keyup.ctrl.enter="send"
        />
        <el-button type="primary" :loading="thinking" @click="send">发送</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { ElMessage } from 'element-plus'
import ChatBubble from '@/components/ChatBubble.vue'
import { chat } from '@/api/ai'
import { useKnowledgeStore } from '@/stores/knowledge'
import { useUserStore } from '@/stores/user'

interface Msg {
  role: 'user' | 'ai'
  text: string
  sources?: string[]
}

const userStore = useUserStore()
const knowledgeStore = useKnowledgeStore()

const question = ref('')
const thinking = ref(false)
const useRag = ref(true)
const messages = ref<Msg[]>([])
const scrollEl = ref<HTMLDivElement>()

async function scrollBottom() {
  await nextTick()
  if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
}

async function send() {
  const q = question.value.trim()
  if (!q) return
  if (!userStore.isLogin) {
    ElMessage.warning('请先登录（知识库检索需要登录态）')
    return
  }
  messages.value.push({ role: 'user', text: q })
  question.value = ''
  thinking.value = true
  await scrollBottom()

  try {
    // 1) 检索知识库（可选，仅用于前端展示命中来源）
    let hits: string[] = []
    if (useRag.value) {
      try {
        const chunks = await knowledgeStore.search(q, 3)
        hits = [...new Set(chunks.map((c) => c.metadata?.filename).filter(Boolean))]
      } catch {
        hits = []
      }
    }

    // 2) 调用大模型（后端会再次检索并把资料拼进 Prompt）
    const res = await chat({ question: q, use_rag: useRag.value, top_k: 3 })
    messages.value.push({
      role: 'ai',
      text: res.answer,
      sources: res.sources?.length ? res.sources : hits
    })
  } catch (e: any) {
    messages.value.push({ role: 'ai', text: `抱歉，回答失败：${e?.message || '未知错误'}` })
  } finally {
    thinking.value = false
    await scrollBottom()
  }
}
</script>

<style scoped>
.chat-page {
  max-width: 900px;
}
.head {
  display: flex;
  align-items: center;
  gap: 14px;
}
.messages {
  height: 460px;
  overflow-y: auto;
  padding: 6px 4px 12px;
}
.composer {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  border-top: 1px solid var(--border);
  padding-top: 12px;
}
.composer .el-button {
  height: 56px;
}
</style>
