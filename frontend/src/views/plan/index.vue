<template>
  <div class="page plan-page">
    <PlanForm v-if="phase === 'form'" :loading="loading" @submit="onStart" />

    <template v-else>
      <PlanChat
        :messages="messages"
        :round="round"
        :max-rounds="maxRounds"
        :loading="loading"
        :ended="ended"
        @send="onSend"
        @accept="onAccept"
      />

      <div v-if="ended" class="final-bar">
        <el-alert
          type="success"
          :closable="false"
          show-icon
          title="方案已定稿"
          description="可以导出 CSV 保存，或重新生成一份新方案。"
        />
        <div class="final-actions">
          <el-button type="primary" @click="exportCsv">导出 CSV</el-button>
          <el-button @click="reset">重新生成</el-button>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PlanForm from './components/PlanForm.vue'
import PlanChat, { type ChatMessage } from './components/PlanChat.vue'
import {
  planHealth,
  planState,
  resumePlan,
  startPlan,
  type PlanChange,
  type PlanStartPayload,
  type PlanTiers
} from '@/api/plan'

const THREAD_KEY = 'gaokao_plan_thread'

const phase = ref<'form' | 'chat'>('form')
const messages = ref<ChatMessage[]>([])
const round = ref(1)
const maxRounds = ref(5)
const loading = ref(false)
const ended = ref(false)
const threadId = ref('')
const latestPlan = ref<PlanTiers | null>(null)

let seq = 0
function nextId() {
  seq += 1
  return `m${Date.now()}_${seq}`
}

function pushUser(text: string) {
  messages.value.push({ id: nextId(), role: 'user', text })
}

function pushPlanCard(
  plan: PlanTiers,
  version: number,
  prevPlan: PlanTiers | null,
  changes?: PlanChange[],
  note?: string
) {
  messages.value.push({
    id: nextId(),
    role: 'ai',
    plan,
    version,
    prevPlan,
    changes: changes || [],
    note
  })
  latestPlan.value = plan
}

async function onStart(payload: PlanStartPayload) {
  loading.value = true
  try {
    const res = await startPlan(payload)
    threadId.value = res.thread_id
    sessionStorage.setItem(THREAD_KEY, res.thread_id)
    const plan = res.final_plan || res.draft_plan
    messages.value = []
    pushPlanCard(plan, res.review_round || 1, null, [], res.note)
    round.value = res.review_round || 1
    ended.value = false
    phase.value = 'chat'
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '生成初稿失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

async function onSend(feedback: string) {
  if (loading.value || ended.value) return
  pushUser(feedback)
  loading.value = true
  const prev = latestPlan.value
  try {
    const res = await resumePlan(threadId.value, feedback, 'revise')
    pushPlanCard(res.final_plan, res.review_round, prev, res.changes, res.note)
    round.value = res.review_round
    if (!res.awaiting_feedback) {
      ended.value = true
      ElMessage.info(`已达 ${maxRounds.value} 轮上限，可以定稿了`)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '调整失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

async function onAccept() {
  if (loading.value) return
  loading.value = true
  const prev = latestPlan.value
  try {
    const res = await resumePlan(threadId.value, '', 'accept')
    if (res.final_plan && Object.keys(res.final_plan).length) {
      pushPlanCard(res.final_plan, round.value, prev, [], res.note || '已按你的确认定稿')
    }
    ended.value = true
    sessionStorage.removeItem(THREAD_KEY)
    ElMessage.success('已定稿')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '定稿失败')
  } finally {
    loading.value = false
  }
}

function reset() {
  sessionStorage.removeItem(THREAD_KEY)
  threadId.value = ''
  messages.value = []
  latestPlan.value = null
  round.value = 1
  ended.value = false
  phase.value = 'form'
}

/** 刷新恢复：thread_id 存 sessionStorage，状态从后端读（0.19.0 D3） */
async function restore() {
  const tid = sessionStorage.getItem(THREAD_KEY)
  if (!tid) return
  try {
    const health = await planHealth()
    if (health.max_review_rounds) maxRounds.value = health.max_review_rounds
    const st = await planState(tid)
    threadId.value = tid
    round.value = st.review_round || 1
    ended.value = !st.awaiting_feedback
    messages.value = []
    // 历史轮次：把每轮用户意见与调整条数还原成对话
    for (const h of st.history || []) {
      if (h.feedback) pushUser(h.feedback)
      messages.value.push({
        id: nextId(),
        role: 'ai',
        text: `第 ${h.round} 轮：调整 ${(h.changes || []).length} 条${h.note ? `（${h.note}）` : ''}`,
        changes: h.changes
      })
    }
    const plan = st.final_plan && Object.keys(st.final_plan).length ? st.final_plan : st.draft_plan
    pushPlanCard(plan, st.review_round || 1, null, st.changes, st.note)
    phase.value = 'chat'
  } catch {
    // 404 / 过期：清掉回到表单
    sessionStorage.removeItem(THREAD_KEY)
  }
}

function exportCsv() {
  const plan = latestPlan.value || {}
  const rows: string[] = ['档位,院校,专业,省份,学费,概率']
  const label: Record<string, string> = { chong: '冲', wen: '稳', bao: '保' }
  for (const tier of ['chong', 'wen', 'bao']) {
    for (const it of plan[tier as keyof PlanTiers] || []) {
      rows.push(
        [
          label[tier],
          it.university_name || '',
          it.major_name || '',
          it.school_province || '',
          it.tuition ?? '',
          it.probability != null ? `${Math.round(it.probability * 100)}%` : ''
        ].join(',')
      )
    }
  }
  const blob = new Blob(['\ufeff' + rows.join('\n')], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `志愿方案_第${round.value}版.csv`
  a.click()
  URL.revokeObjectURL(a.href)
}

onMounted(async () => {
  try {
    const health = await planHealth()
    if (health.max_review_rounds) maxRounds.value = health.max_review_rounds
  } catch {
    /* 自检失败不影响表单 */
  }
  await restore()
})
</script>

<style scoped>
.plan-page {
  padding-bottom: 24px;
}
.final-bar {
  max-width: 1100px;
  margin: 16px auto 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.final-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
