<template>
  <div class="page chat-page">
    <el-card shadow="never" class="chat-card">
      <template #header>
        <div class="head">
          <div class="head-left">
            <b>AI 志愿助手</b>
            <span class="badge">本地模型 · 数据不出本机</span>
            <el-tag v-if="profileReady" type="success" size="small">已结合你的画像</el-tag>
          </div>
          <!-- 0.13.0：唯一入口，替代原来的 RAG 开关与「构建专属画像」按钮 -->
          <el-button
            v-if="userStore.isLogin"
            class="counselor-btn"
            type="primary"
            size="small"
            @click="$router.push('/counselor')"
          >
            想让我更了解你吗？
          </el-button>
          <el-tag v-else type="warning" size="small" @click="$router.push('/login')">
            登录后可用
          </el-tag>
        </div>
      </template>

      <div ref="scrollEl" class="messages">
        <ChatBubble
          role="ai"
          text="你好，我是高考志愿填报助手。可以问我填报政策、批次规则、冲稳保策略，也可以查某所学校或专业的分数、学费。"
        />
        <ChatBubble
          v-for="(m, i) in messages"
          :key="i"
          :role="m.role"
          :text="m.text"
          :sources="m.sources"
        />

        <!-- 0.13.0：本地 4b 推理较慢，给出明确的思考动画，避免用户以为卡死 -->
        <div v-if="thinking" class="thinking">
          <span class="dots"><i></i><i></i><i></i></span>
          <span class="thinking-text">{{ thinkingText }}</span>
        </div>
      </div>

      <div class="composer">
        <el-input
          v-model="question"
          type="textarea"
          :rows="2"
          placeholder="例如：河南本科批平行志愿怎么填报？（Ctrl + Enter 发送）"
          @keyup.ctrl.enter="send"
        />
        <el-button type="primary" :loading="thinking" @click="send">发送</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import ChatBubble from '@/components/ChatBubble.vue'
import { chat } from '@/api/ai'
import { fetchProfile } from '@/api/profile'
import { useUserStore } from '@/stores/user'

interface Msg {
  role: 'user' | 'ai'
  text: string
  sources?: string[]
}

const userStore = useUserStore()

const question = ref('')
const thinking = ref(false)
const thinkingText = ref('AI 正在思考…')
const messages = ref<Msg[]>([])
const scrollEl = ref<HTMLDivElement>()
const profileReady = ref(false)

/** 思考文案随时间变化，让等待过程「有反馈」 */
const THINKING_STEPS = [
  'AI 正在思考…',
  '正在判断需要查哪些资料…',
  '正在检索政策与录取数据…',
  '正在整理答案…（本地模型较慢，请稍候）'
]
let thinkTimer: number | undefined

function startThinking() {
  thinking.value = true
  let i = 0
  thinkingText.value = THINKING_STEPS[0]
  thinkTimer = window.setInterval(() => {
    i = Math.min(i + 1, THINKING_STEPS.length - 1)
    thinkingText.value = THINKING_STEPS[i]
  }, 6000)
}

function stopThinking() {
  thinking.value = false
  if (thinkTimer) {
    window.clearInterval(thinkTimer)
    thinkTimer = undefined
  }
}

async function scrollBottom() {
  await nextTick()
  if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
}

async function send() {
  const q = question.value.trim()
  if (!q) return
  if (!userStore.isLogin) {
    ElMessage.warning('请先登录')
    return
  }
  messages.value.push({ role: 'user', text: q })
  question.value = ''
  startThinking()
  await scrollBottom()

  try {
    // 0.13.0：后端默认走本地 Agent（模型自主决定调用哪个工具），
    // 前端不再传 use_rag —— 用户不需要知道 RAG 是什么。
    const res = await chat({ question: q })
    messages.value.push({
      role: 'ai',
      text: res.answer,
      sources: res.sources?.length ? res.sources : undefined
    })
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    messages.value.push({
      role: 'ai',
      text: `抱歉，回答失败：${detail || e?.message || '未知错误'}`
    })
  } finally {
    stopThinking()
    await scrollBottom()
  }
}

onMounted(async () => {
  if (!userStore.isLogin) return
  try {
    const p = await fetchProfile()
    profileReady.value = !!p.ready
  } catch {
    profileReady.value = false
  }
})

onBeforeUnmount(() => {
  if (thinkTimer) window.clearInterval(thinkTimer)
})
</script>

<style scoped>
.chat-page {
  max-width: 900px;
}
.head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: space-between;
}
.head-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.badge {
  font-size: 11.5px;
  color: #2e7d32;
  background: #e8f5e9;
  border-radius: 10px;
  padding: 1px 8px;
}
.counselor-btn {
  border-radius: 16px;
}
.messages {
  height: 470px;
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

/* ---------------- 思考动画 ---------------- */
.thinking {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 4px;
}
.thinking-text {
  font-size: 13px;
  color: var(--text-sub);
}
.dots {
  display: inline-flex;
  gap: 4px;
}
.dots i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary);
  opacity: 0.35;
  animation: bounce 1.2s infinite ease-in-out;
}
.dots i:nth-child(2) {
  animation-delay: 0.18s;
}
.dots i:nth-child(3) {
  animation-delay: 0.36s;
}
@keyframes bounce {
  0%,
  80%,
  100% {
    transform: translateY(0);
    opacity: 0.35;
  }
  40% {
    transform: translateY(-5px);
    opacity: 1;
  }
}
</style>
