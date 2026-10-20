<template>
  <div class="page profile-page">
    <h2 class="title">个人主页</h2>

    <div class="grid">
      <!-- 左：基础资料 -->
      <el-card shadow="never">
        <template #header>
          <div class="card-head">
            <b>基础资料</b>
            <span class="muted">完善后 AI 建议会更贴合你的情况</span>
          </div>
        </template>

        <el-form :model="form" label-position="top">
          <el-form-item label="昵称">
            <el-input v-model="form.nickname" maxlength="20" placeholder="怎么称呼你" />
          </el-form-item>
          <el-form-item label="手机号">
            <el-input v-model="form.phone" maxlength="11" placeholder="11 位手机号" />
          </el-form-item>
          <div class="row2">
            <el-form-item label="性别">
              <el-select v-model="form.gender" clearable placeholder="未填写" style="width: 100%">
                <el-option label="男" value="male" />
                <el-option label="女" value="female" />
                <el-option label="不便透露" value="other" />
              </el-select>
            </el-form-item>
            <el-form-item label="生日">
              <el-date-picker
                v-model="form.birthday"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择日期"
                style="width: 100%"
              />
            </el-form-item>
          </div>
          <el-form-item label="邮箱">
            <el-input v-model="form.email" placeholder="选填，用于接收提醒" />
          </el-form-item>

          <el-divider content-position="left">报考信息（用于画像）</el-divider>

          <div class="row2">
            <el-form-item label="生源省份">
              <el-select v-model="form.province" style="width: 100%" @change="onProvinceChange">
                <el-option v-for="p in provinces" :key="p" :label="p" :value="p" />
              </el-select>
            </el-form-item>
            <el-form-item label="科类">
              <el-select v-model="form.category" style="width: 100%">
                <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
              </el-select>
            </el-form-item>
          </div>
          <el-form-item label="预估分数">
            <el-input v-model.number="form.score" type="number" placeholder="选填，0-750" />
          </el-form-item>

          <el-button type="primary" class="full" :loading="saving" @click="onSave">
            保存资料
          </el-button>
        </el-form>
      </el-card>

      <!-- 右：画像 -->
      <el-card shadow="never">
        <template #header>
          <div class="card-head">
            <b>我的画像</b>
            <el-tag v-if="profile?.ready" type="success" size="small">
              {{ sourceLabel }}
            </el-tag>
            <el-tag v-else type="info" size="small">未构建</el-tag>
          </div>
        </template>

        <div v-if="loading" class="muted">加载中…</div>

        <template v-else>
          <div v-if="profile?.ready" class="summary-box">
            {{ profile.summary_text }}
          </div>
          <el-empty v-else description="还没有画像，去 AI 助手构建一个吧" :image-size="80" />

          <!-- 报告特征回显 -->
          <div v-if="reportTraits.length" class="feature-block">
            <div class="feature-title">测评特征</div>
            <div class="tags">
              <el-tag v-if="profile?.external_reports?.mbti" size="small">
                MBTI {{ profile.external_reports.mbti }}
              </el-tag>
              <el-tag v-if="profile?.external_reports?.holland" size="small">
                霍兰德 {{ profile.external_reports.holland }}
              </el-tag>
              <el-tag v-for="t in reportTraits" :key="t" size="small" type="info">{{ t }}</el-tag>
            </div>
          </div>

          <!-- 问卷偏好回显 -->
          <div v-if="surveyPrefs.length" class="feature-block">
            <div class="feature-title">报考偏好</div>
            <div class="tags">
              <el-tag v-for="p in surveyPrefs" :key="p" size="small" type="warning">{{ p }}</el-tag>
            </div>
          </div>

          <div v-if="profile?.updated_at" class="muted updated">
            最后更新：{{ profile.updated_at }}
          </div>

          <div class="actions">
            <el-button type="primary" plain @click="goBuild">构建 / 更新画像</el-button>
            <el-button :loading="rebuilding" :disabled="!profile?.ready" @click="onRebuild">
              重新汇总
            </el-button>
            <el-button type="danger" plain :disabled="!profile?.ready" @click="onClear">
              清空画像
            </el-button>
          </div>
        </template>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  clearProfile,
  fetchProfile,
  rebuildProfile,
  updateProfileBasic
} from '@/api/profile'
import { metaOptions } from '@/api/recommend'
import { useUserStore } from '@/stores/user'
import type { ProfileView } from '@/types/profile'

const router = useRouter()
const userStore = useUserStore()

const loading = ref(false)
const saving = ref(false)
const rebuilding = ref(false)
const profile = ref<ProfileView | null>(null)

const provinces = ref<string[]>(['河南'])
const categoriesMap = ref<Record<string, string[]>>({ 河南: ['物理类', '历史类'] })

const form = reactive({
  nickname: '',
  phone: '',
  gender: '' as '' | 'male' | 'female' | 'other',
  birthday: '',
  email: '',
  province: '河南',
  category: '物理类',
  score: undefined as number | undefined
})

const categories = computed(() => categoriesMap.value[form.province] || [])

/** 画像来源 → 中文标签 */
const sourceLabel = computed(() => {
  const map: Record<string, string> = {
    report: '来自测评报告',
    survey: '来自业务问卷',
    both: '报告 + 问卷',
    manual: '手动汇总'
  }
  return map[profile.value?.source || ''] || '已构建'
})

const reportTraits = computed(() => profile.value?.external_reports?.traits || [])

/** 问卷偏好 → ["地域偏好：河南", ...] */
const surveyPrefs = computed(() => {
  const feats = profile.value?.survey_answers?.features as any
  const prefs = feats?.preferences
  if (!prefs || typeof prefs !== 'object') return []
  return Object.entries(prefs).map(([k, v]) => `${k}：${v}`)
})

function onProvinceChange() {
  form.category = categories.value[0] || ''
}

async function load() {
  loading.value = true
  try {
    profile.value = await fetchProfile()
    const info = profile.value.basic_info || {}
    form.nickname = info.nickname || userStore.user?.nickname || ''
    form.phone = userStore.user?.phone || ''
    form.gender = (userStore.user?.gender as any) || ''
    form.birthday = info.birthday || userStore.user?.birthday || ''
    form.email = info.email || userStore.user?.email || ''
    form.province = info.province || '河南'
    form.category = info.category || '物理类'
    form.score = info.score
  } finally {
    loading.value = false
  }
}

async function loadOptions() {
  try {
    const res = await metaOptions(form.province)
    provinces.value = res.provinces?.length ? res.provinces : provinces.value
    categoriesMap.value = res.categories_map || categoriesMap.value
  } catch {
    // 拉不到就保留默认值
  }
}

async function onSave() {
  saving.value = true
  try {
    const payload: Record<string, any> = {
      nickname: form.nickname || undefined,
      phone: form.phone || undefined,
      gender: form.gender || undefined,
      birthday: form.birthday || undefined,
      email: form.email || undefined,
      province: form.province || undefined,
      category: form.category || undefined,
      score: typeof form.score === 'number' ? form.score : undefined
    }
    profile.value = await updateProfileBasic(payload)
    // 同步 Navbar 的展示名
    userStore.patchUser({
      nickname: form.nickname,
      phone: form.phone,
      gender: (form.gender || null) as any,
      birthday: form.birthday || null,
      email: form.email,
      display_name: form.nickname || userStore.user?.username
    })
    ElMessage.success('资料已保存')
  } finally {
    saving.value = false
  }
}

async function onRebuild() {
  rebuilding.value = true
  try {
    await rebuildProfile()
    profile.value = await fetchProfile()
    ElMessage.success('画像已重新汇总')
  } finally {
    rebuilding.value = false
  }
}

async function onClear() {
  try {
    await ElMessageBox.confirm('清空后需要重新构建画像，确定吗？', '提示', { type: 'warning' })
  } catch {
    return
  }
  await clearProfile()
  profile.value = await fetchProfile()
  ElMessage.success('画像已清空')
}

function goBuild() {
  // 0.13.0：画像构建与报告上传统一收敛到「心理与画像空间」
  router.push('/counselor')
}

onMounted(async () => {
  if (!userStore.user) await userStore.loadMe()
  await loadOptions()
  await load()
})
</script>

<style scoped>
.profile-page {
  max-width: 1080px;
}
.title {
  margin: 0 0 14px;
}
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  align-items: start;
}
@media (max-width: 900px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
.card-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.row2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.full {
  width: 100%;
}
.summary-box {
  background: #f6f8fb;
  border-left: 3px solid var(--primary);
  border-radius: 6px;
  padding: 12px 14px;
  line-height: 1.8;
  font-size: 14px;
  color: #333;
  white-space: pre-wrap;
}
.feature-block {
  margin-top: 14px;
}
.feature-title {
  font-size: 13px;
  color: var(--text-sub);
  margin-bottom: 6px;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.updated {
  margin-top: 12px;
  font-size: 12px;
}
.actions {
  margin-top: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
