<template>
  <div class="plan-card">
    <div class="plan-head">
      <b>第 {{ version }} 版方案</b>
      <el-tag v-if="changes.length" size="small" type="warning">
        本轮调整 {{ changes.length }} 条
      </el-tag>
      <span v-else class="muted">本轮无调整</span>
    </div>

    <el-alert
      v-if="note"
      class="plan-note"
      :title="note"
      type="info"
      :closable="false"
      show-icon
    />

    <div class="tiers">
      <section v-for="tier in TIERS" :key="tier.key" class="tier">
        <header :class="['tier-head', tier.key]">
          {{ tier.label }}
          <span class="count">{{ (plan[tier.key] || []).length }}</span>
        </header>
        <div v-if="!(plan[tier.key] || []).length" class="empty">本档暂无院校</div>
        <div
          v-for="item in plan[tier.key] || []"
          :key="keyOf(item)"
          :class="['item', { added: addedKeys.has(keyOf(item)) }]"
        >
          <div class="row1">
            <span class="univ">{{ item.university_name }}</span>
            <el-tag v-if="addedKeys.has(keyOf(item))" size="small" type="success">新增</el-tag>
            <span class="prob">{{ pct(item.probability) }}</span>
          </div>
          <div class="row2">
            <span>{{ item.major_name }}</span>
            <span class="dot">·</span>
            <span>{{ item.school_province }}</span>
            <span class="dot">·</span>
            <span>{{ fmtTuition(item.tuition) }}</span>
          </div>
        </div>
      </section>
    </div>

    <el-collapse v-if="removed.length" class="removed">
      <el-collapse-item :title="`本轮移除 ${removed.length} 条（点击看原因）`">
        <div v-for="(c, i) in removed" :key="i" class="removed-item">
          {{ c.university }} · {{ c.major }} —— {{ c.reason }}
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { PlanChange, PlanItem, PlanTiers } from '@/api/plan'

const props = defineProps<{
  plan: PlanTiers
  version: number
  prevPlan?: PlanTiers | null
  changes?: PlanChange[]
  note?: string
}>()

const TIERS = [
  { key: 'chong' as const, label: '冲' },
  { key: 'wen' as const, label: '稳' },
  { key: 'bao' as const, label: '保' }
]

const changes = computed(() => props.changes || [])
const removed = computed(() => changes.value.filter((c) => c.action === 'remove'))
const note = computed(() => props.note || '')

function keyOf(item: PlanItem) {
  return `${item.university_name || ''}__${item.major_name || ''}`
}

/** 与上一版相比新增的条目（上一版没有的 key） */
const addedKeys = computed(() => {
  const prev = props.prevPlan
  if (!prev) return new Set<string>()
  const oldKeys = new Set<string>()
  for (const tier of TIERS) {
    for (const item of prev[tier.key] || []) oldKeys.add(keyOf(item))
  }
  const added = new Set<string>()
  for (const tier of TIERS) {
    for (const item of props.plan[tier.key] || []) {
      const k = keyOf(item)
      if (!oldKeys.has(k)) added.add(k)
    }
  }
  return added
})

function pct(v?: number) {
  if (v == null) return '—'
  return `${Math.round(v * 100)}%`
}

function fmtTuition(v?: number | null) {
  if (v === 0) return '免学费'
  if (v == null) return '学费未知'
  return `${v} 元/年`
}
</script>

<style scoped>
.plan-card {
  border: 1px solid var(--el-border-color-light);
  border-radius: 10px;
  padding: 12px;
  background: var(--el-bg-color);
}
.plan-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.plan-note {
  margin-bottom: 10px;
}
.tiers {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.tier {
  min-width: 0;
}
.tier-head {
  font-size: 13px;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 6px;
  margin-bottom: 6px;
  display: flex;
  justify-content: space-between;
}
.tier-head.chong {
  background: #fdecea;
  color: #c0392b;
}
.tier-head.wen {
  background: #fff6e5;
  color: #b9770e;
}
.tier-head.bao {
  background: #e8f5e9;
  color: #2e7d32;
}
.count {
  opacity: 0.7;
}
.item {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 6px 8px;
  margin-bottom: 6px;
  font-size: 12.5px;
  line-height: 1.5;
}
.item.added {
  background: #f0f9eb;
  border-color: #b7e0a3;
}
.row1 {
  display: flex;
  align-items: center;
  gap: 6px;
}
.univ {
  font-weight: 600;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.prob {
  color: var(--el-text-color-secondary);
}
.row2 {
  color: var(--el-text-color-secondary);
}
.dot {
  margin: 0 4px;
}
.empty {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  padding: 6px 2px;
}
.removed {
  margin-top: 8px;
}
.removed-item {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.8;
}
@media (max-width: 900px) {
  .tiers {
    grid-template-columns: 1fr;
  }
}
</style>
