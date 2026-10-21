<template>
  <div class="plan-chat">
    <div class="chat-head">
      <span>第 {{ round }} 轮 / 最多 {{ maxRounds }} 轮</span>
      <span v-if="ended" class="muted">已达上限或已定稿</span>
    </div>

    <div ref="scrollEl" class="chat-body">
      <div v-for="m in messages" :key="m.id" :class="['msg', m.role]">
        <template v-if="m.role === 'ai'">
          <PlanCard
            v-if="m.plan"
            :plan="m.plan"
            :version="m.version || 1"
            :prev-plan="m.prevPlan"
            :changes="m.changes"
            :note="m.note"
          />
          <div v-else class="bubble ai">{{ m.text }}</div>
        </template>
        <div v-else class="bubble user">{{ m.text }}</div>
      </div>
    </div>

    <div class="composer">
      <el-input
        v-model="draft"
        type="textarea"
        :rows="2"
        :disabled="inputDisabled"
        maxlength="1000"
        placeholder="继续提意见，例如：只保留福建的、学费别超 6000、太远的不想去"
        @keyup.ctrl.enter="onSend"
      />
      <div class="actions">
        <el-button :disabled="inputDisabled" @click="onSend" :loading="loading">
          发送修改意见
        </el-button>
        <el-button type="success" :disabled="acceptDisabled" @click="emit('accept')">
          就这个方案，定稿
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import PlanCard from './PlanCard.vue'
import type { PlanChange, PlanTiers } from '@/api/plan'

export interface ChatMessage {
  id: string
  role: 'ai' | 'user'
  text?: string
  plan?: PlanTiers
  version?: number
  prevPlan?: PlanTiers | null
  changes?: PlanChange[]
  note?: string
}

const props = defineProps<{
  messages: ChatMessage[]
  round: number
  maxRounds: number
  loading: boolean
  ended: boolean
}>()

const emit = defineEmits<{
  (e: 'send', feedback: string): void
  (e: 'accept'): void
}>()

const draft = ref('')
const scrollEl = ref<HTMLDivElement>()

const inputDisabled = computed(() => props.loading || props.ended)
const acceptDisabled = computed(() => props.loading || props.ended)

function onSend() {
  const text = draft.value.trim()
  if (!text) {
    ElMessage.warning('说点什么再发送～')
    return
  }
  if (props.ended) return
  emit('send', text)
  draft.value = ''
}

watch(
  () => props.messages.length,
  async () => {
    await nextTick()
    if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
  }
)
</script>

<style scoped>
.plan-chat {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 1100px;
  margin: 0 auto;
}
.chat-head {
  display: flex;
  justify-content: space-between;
  font-size: 12.5px;
  color: var(--el-text-color-secondary);
}
.muted {
  color: var(--el-text-color-placeholder);
}
.chat-body {
  max-height: 62vh;
  overflow-y: auto;
  padding: 4px 2px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.msg.ai {
  align-self: stretch;
}
.msg.user {
  align-self: flex-end;
  max-width: 70%;
}
.bubble {
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.bubble.user {
  background: var(--el-color-primary-light-9);
  border: 1px solid var(--el-color-primary-light-7);
}
.bubble.ai {
  background: var(--el-fill-color-lighter);
}
.composer {
  border-top: 1px solid var(--el-border-color-lighter);
  padding-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
