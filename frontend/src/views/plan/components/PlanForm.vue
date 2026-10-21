<template>
  <el-card shadow="never" class="plan-form">
    <template #header>
      <b>生成我的专属志愿方案</b>
      <div class="muted">填好基本信息，AI 先出一版初稿，之后可以反复提意见修改。</div>
    </template>

    <el-form :model="form" label-width="90px" @submit.prevent>
      <el-form-item label="省份" required>
        <el-input v-model="form.province" placeholder="如 河南" maxlength="10" />
      </el-form-item>
      <el-form-item label="科类" required>
        <el-select v-model="form.category" placeholder="请选择" style="width: 100%">
          <el-option label="物理类" value="物理类" />
          <el-option label="历史类" value="历史类" />
          <el-option label="理科" value="理科" />
          <el-option label="文科" value="文科" />
          <el-option label="综合" value="综合" />
        </el-select>
      </el-form-item>
      <el-form-item label="分数 / 位次">
        <div class="two">
          <el-input-number v-model="form.score" :min="0" :max="750" controls-position="right" placeholder="分数" />
          <el-input-number v-model="form.rank" :min="1" controls-position="right" placeholder="位次（可选）" />
        </div>
      </el-form-item>
      <el-form-item label="年份">
        <el-input-number v-model="form.year" :min="2020" :max="2030" controls-position="right" />
      </el-form-item>
      <el-form-item label="偏好">
        <el-input
          v-model="form.preferences"
          type="textarea"
          :rows="2"
          maxlength="500"
          show-word-limit
          placeholder="例如：我想去福建上学；学费别超 6000；太冷的地方不去"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="loading" @click="onSubmit">
          生成初稿
        </el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import type { PlanStartPayload } from '@/api/plan'

defineProps<{ loading: boolean }>()
const emit = defineEmits<{ (e: 'submit', payload: PlanStartPayload): void }>()

const form = reactive({
  province: '河南',
  category: '物理类',
  score: 600 as number | undefined,
  rank: undefined as number | undefined,
  year: 2025,
  preferences: ''
})

function onSubmit() {
  if (!form.province.trim() || !form.category) {
    ElMessage.warning('请填写省份与科类')
    return
  }
  if (!form.score && !form.rank) {
    ElMessage.warning('分数与位次至少填一个')
    return
  }
  emit('submit', {
    province: form.province.trim(),
    category: form.category,
    score: form.score,
    rank: form.rank,
    year: form.year,
    preferences: form.preferences.trim()
  })
}
</script>

<style scoped>
.plan-form {
  max-width: 720px;
  margin: 0 auto;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: 4px;
}
.two {
  display: flex;
  gap: 8px;
  width: 100%;
}
</style>
