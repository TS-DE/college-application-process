<template>
  <div class="page chat-page">
    <el-card shadow="never" class="chat-card">
      <template #header>
        <div class="head">
          <div class="head-left">
            <b>AI 志愿助手</b>
            <span class="badge">本地模型 · 数据不出本机</span>
            <el-tag v-if="profileReady" type="success" size="small">已结合你的画像</el-tag>

            <!-- 0.13.1：环境状态指示灯，说明「为什么有些问题答不上来」 -->
            <el-tooltip
              :content="statusTip.vector"
              placement="bottom"
              :show-after="200"
            >
              <span class="status-dot">
                <i :class="['dot', status.vector_ready ? 'ok' : 'bad']"></i>政策库
              </span>
            </el-tooltip>
            <el-tooltip
              :content="statusTip.graph"
              placement="bottom"
              :show-after="200"
            >
              <span class="status-dot">
                <i :class="['dot', status.graph_ready ? 'ok' : 'bad']"></i>图谱
              </span>
            </el-tooltip>
          </div>
          <!-- 0.14.0：人机协同志愿规划入口 -->
          <div class="head-right">
            <template v-if="userStore.isLogin">
              <el-button size="small" @click="$router.push('/plan')">
                🤖 智能生成志愿方案
              </el-button>
              <!-- 0.13.0：画像空间入口 -->
              <el-button
                class="counselor-btn"
                type="primary"
                size="small"
                @click="$router.push('/counselor')"
              >
                想让我更了解你吗？
              </el-button>
            </template>
            <el-tag v-else type="warning" size="small" @click="$router.push('/login')">
              登录后可用
            </el-tag>
          </div>
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
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import ChatBubble from '@/components/ChatBubble.vue'
import { chat } from '@/api/ai'
import { agentStatus, type AgentStatusResult } from '@/api/recommend'
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

// ---- 0.13.1 环境状态指示灯 ----
const status = ref<AgentStatusResult>({
  vector_ready: false,
  vector_count: 0,
  graph_ready: false,
  local_model: '',
  agent_mode: 'fast',
  agent_enabled: true
})

/** 悬浮提示：把「为什么答不上来」说清楚 */
const statusTip = computed(() => ({
  vector: status.value.vector_ready
    ? `政策库就绪（${status.value.vector_count} 个文档切片）`
    : `政策库暂无内容，政策类问题可能答不上来${status.value.vector_error ? `（${status.value.vector_error}）` : ''}`,
  graph: status.value.graph_ready
    ? '知识图谱在线，可查询院校—专业—地区关系'
    : '图数据库未启动，无法查询开设专业和选科要求'
}))

async function loadStatus() {
  try {
    status.value = await agentStatus()
  } catch {
    // 探测失败不影响聊天，指示灯保持灰色（默认红灯）
  }
}

/**
 * 思考文案随耗时升级（0.13.1）。
 *
 * 背景：Fast Mode 约 3-10 秒；Agent 模式（AGENT_FAST_MODE=0）在纯 CPU 上
 * 规划 20-55s + 工具 5-10s + 生成 25s，最长约 90 秒。
 * 超过 45 秒仍无响应时必须明确告知「需要约 1 分钟」，而不是让用户以为卡死。
 */
let thinkTimer: number | undefined
let thinkStart = 0

function startThinking() {
  thinking.value = true
  thinkStart = Date.now()
  thinkingText.value = 'AI 正在思考…'
  thinkTimer = window.setInterval(() => {
    const sec = (Date.now() - thinkStart) / 1000
    if (sec < 6) thinkingText.value = 'AI 正在思考…'
    else if (sec < 15) thinkingText.value = '正在判断需要查哪些资料…'
    else if (sec < 30) thinkingText.value = '正在检索政策与录取数据…'
    else if (sec < 45) thinkingText.value = '正在整理答案…'
    else
      thinkingText.value = `本地模型正在深度推理，约需 1 分钟（已等待 ${Math.round(sec)} 秒）…`
  }, 2000)
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
  // 环境状态与登录无关，先探测（后端有 30s 缓存，开销很小）
  loadStatus()
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

/* ---------------- 0.13.1 环境指示灯 ---------------- */
.status-dot {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  color: var(--text-sub);
  cursor: help;
  user-select: none;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
  transition: background 0.3s;
}
.dot.ok {
  background: #43a047;
  box-shadow: 0 0 0 2px rgba(67, 160, 71, 0.18);
}
.dot.bad {
  background: #e53935;
  box-shadow: 0 0 0 2px rgba(229, 57, 53, 0.18);
}
.counselor-btn {
  border-radius: 16px;
}
.head-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
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
