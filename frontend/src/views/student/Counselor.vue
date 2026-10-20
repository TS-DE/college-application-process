<template>
  <div class="page counselor-page">
    <div class="topbar">
      <el-button text @click="$router.push('/ai-chat')">← 返回 AI 助手</el-button>
      <div class="title-wrap">
        <h2>想让我更了解你吗？</h2>
        <p class="muted">
          这里是你的专属空间：聊聊你的想法，或者上传测评报告。
          我会把这些整理成画像，之后给建议时就会结合你的情况。
        </p>
      </div>
      <el-tag size="small" type="info">云端模型 · 仅本人可见</el-tag>
    </div>

    <div class="grid">
      <!-- 左：云端心理师对话 -->
      <el-card shadow="never" class="chat-card">
        <template #header>
          <div class="card-head">
            <b>聊聊你的想法</b>
            <span class="muted small">不用着急，想到什么说什么</span>
          </div>
        </template>

        <div ref="scrollEl" class="messages">
          <ChatBubble
            role="ai"
            text="你好呀。最近在志愿这件事上，有什么让你拿不定主意的地方吗？"
          />
          <ChatBubble
            v-for="(m, i) in messages"
            :key="i"
            :role="m.role === 'user' ? 'user' : 'ai'"
            :text="m.content"
          />
          <div v-if="thinking" class="thinking">
            <span class="dots"><i></i><i></i><i></i></span>
            <span class="thinking-text">正在倾听和思考…</span>
          </div>
        </div>

        <div class="composer">
          <el-input
            v-model="question"
            type="textarea"
            :rows="2"
            placeholder="例如：我爸妈想让我学医，但我更喜欢计算机，怎么办？"
            @keyup.ctrl.enter="send"
          />
          <el-button type="primary" :loading="thinking" @click="send">发送</el-button>
        </div>
      </el-card>

      <!-- 右：报告上传 + 画像 -->
      <div class="side">
        <el-card shadow="never">
          <template #header>
            <div class="card-head">
              <b>上传测评报告</b>
              <el-tag v-if="profile?.ready" type="success" size="small">{{ sourceLabel }}</el-tag>
            </div>
          </template>

          <p class="muted small tip">上传你的测评报告，我会更懂你。</p>

          <el-upload
            class="uploader"
            drag
            :auto-upload="true"
            :show-file-list="false"
            :limit="1"
            accept=".pdf,.txt,.docx,.md,.png,.jpg,.jpeg"
            :http-request="onFileUpload"
          >
            <div class="uploader-inner">
              <div class="uploader-icon">⬆</div>
              <div class="uploader-text">拖入文件，或<em>点击上传</em></div>
              <div class="muted uploader-tip">PDF / 图片 / TXT / MD / DOCX，≤10MB</div>
            </div>
          </el-upload>

          <div class="upload-actions">
            <el-button size="small" @click="pasteVisible = true">粘贴报告文字</el-button>
            <el-button size="small" @click="openSurvey">填写问卷</el-button>
          </div>

          <el-alert
            class="privacy"
            type="info"
            :closable="false"
            show-icon
            title="报告仅用于生成你自己的画像，解析后立即删除，不会进入公共知识库。"
          />
        </el-card>

        <el-card shadow="never" class="profile-card">
          <template #header>
            <div class="card-head">
              <b>我的画像</b>
              <el-button
                v-if="profile?.ready"
                text
                size="small"
                :loading="rebuilding"
                @click="onRebuild"
              >
                重新汇总
              </el-button>
            </div>
          </template>

          <div v-if="loading" class="muted small">加载中…</div>
          <template v-else>
            <div v-if="profile?.ready" class="summary">{{ profile.summary_text }}</div>
            <el-empty
              v-else
              description="还没有画像：聊几句、传份报告或做一次问卷都可以"
              :image-size="64"
            />

            <div v-if="tags.length" class="tags">
              <el-tag v-for="t in tags" :key="t" size="small" type="info">{{ t }}</el-tag>
            </div>

            <div v-if="profile?.updated_at" class="muted small updated">
              更新于 {{ profile.updated_at }}
            </div>

            <el-button text size="small" class="link" @click="$router.push('/profile')">
              去个人主页完善资料 →
            </el-button>
          </template>
        </el-card>
      </div>
    </div>

    <!-- 粘贴报告文字 -->
    <el-dialog v-model="pasteVisible" title="粘贴报告内容" width="600px">
      <el-input
        v-model="reportText"
        type="textarea"
        :rows="10"
        maxlength="20000"
        show-word-limit
        placeholder="把 MBTI / 霍兰德报告里的文字贴进来，例如：&#10;霍兰德兴趣代码 IRC，MBTI 为 INTJ&#10;特质：逻辑性强、独立思考…"
      />
      <template #footer>
        <el-button @click="pasteVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitPaste">开始解析</el-button>
      </template>
    </el-dialog>

    <!-- 业务问卷 -->
    <el-drawer v-model="surveyVisible" title="填写问卷" size="560px">
      <div v-if="!questions.length" class="step-body">
        <p class="muted">选择你希望被了解的方面，AI 会据此出题（只问志愿填报业务）。</p>
        <el-checkbox-group v-model="domains" class="domain-group">
          <el-checkbox v-for="d in allDomains" :key="d" :value="d" :label="d" />
        </el-checkbox-group>
        <div class="step-actions">
          <el-button type="primary" :loading="loadingQuestions" @click="genQuestions">
            生成问卷
          </el-button>
        </div>
      </div>

      <div v-else class="step-body">
        <el-alert
          v-if="fallbackTip"
          :title="fallbackTip"
          type="info"
          :closable="false"
          show-icon
          class="tip"
        />
        <el-card v-for="(q, idx) in questions" :key="q.id" shadow="never" class="q-card">
          <div class="q-title">
            <span class="q-index">{{ idx + 1 }}</span>{{ q.title }}
            <el-tag v-if="q.type === 'multiple'" size="small" type="info">多选</el-tag>
          </div>
          <div v-if="q.hint" class="muted small q-hint">{{ q.hint }}</div>
          <el-radio-group v-if="q.type === 'single'" v-model="answers[q.id]" class="opts">
            <el-radio v-for="o in q.options" :key="o.value" :value="o.value">{{ o.label }}</el-radio>
          </el-radio-group>
          <el-checkbox-group v-else-if="q.type === 'multiple'" v-model="answers[q.id]" class="opts">
            <el-checkbox v-for="o in q.options" :key="o.value" :value="o.value">
              {{ o.label }}
            </el-checkbox>
          </el-checkbox-group>
          <el-input v-else v-model="answers[q.id]" type="textarea" :rows="2" placeholder="选填" />
        </el-card>
        <div class="step-actions">
          <el-button @click="questions = []">重新选题</el-button>
          <el-button type="primary" :loading="submitting" @click="submitSurvey">提交并生成画像</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import ChatBubble from '@/components/ChatBubble.vue'
import { counselorChat, type CounselorMessage } from '@/api/ai'
import {
  fetchProfile,
  fetchProfileDomains,
  generateSurvey,
  rebuildProfile,
  submitSurvey as submitSurveyApi,
  updateProfileBasic,
  uploadReport,
  uploadReportFile
} from '@/api/profile'
import type { ProfileView, SurveyQuestion } from '@/types/profile'

// ---------------------------------------------------------------- 对话

const messages = ref<CounselorMessage[]>([])
const question = ref('')
const thinking = ref(false)
const scrollEl = ref<HTMLDivElement>()

async function scrollBottom() {
  await nextTick()
  if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
}

async function send() {
  const q = question.value.trim()
  if (!q) return
  messages.value.push({ role: 'user', content: q })
  question.value = ''
  thinking.value = true
  await scrollBottom()
  try {
    // 只传最近 20 条，避免请求体过大
    const res = await counselorChat(messages.value.slice(-20))
    messages.value.push({ role: 'assistant', content: res.answer })
    if (res.profile_injected) profileInjected.value = true
  } catch (e: any) {
    messages.value.push({
      role: 'assistant',
      content: `抱歉，我这边有点问题：${e?.response?.data?.detail || '请稍后再试'}`
    })
  } finally {
    thinking.value = false
    await scrollBottom()
  }
}

// ---------------------------------------------------------------- 画像

const profile = ref<ProfileView | null>(null)
const loading = ref(false)
const rebuilding = ref(false)
const submitting = ref(false)
const profileInjected = ref(false)

const sourceLabel = computed(() => {
  const map: Record<string, string> = {
    report: '来自测评报告',
    survey: '来自业务问卷',
    both: '报告 + 问卷',
    manual: '手动汇总'
  }
  return map[profile.value?.source || ''] || '已生成'
})

/** 画像标签：MBTI / 霍兰德 / 特质 / 偏好 */
const tags = computed(() => {
  const out: string[] = []
  const r = profile.value?.external_reports
  if (r?.mbti) out.push(`MBTI ${r.mbti}`)
  if (r?.holland) out.push(`霍兰德 ${r.holland}`)
  for (const t of r?.traits || []) if (!out.includes(t)) out.push(t)
  for (const t of r?.interests || []) if (!out.includes(t)) out.push(t)
  const feats = (profile.value?.survey_answers as any)?.features
  for (const t of feats?.traits || []) if (!out.includes(t)) out.push(t)
  return out.slice(0, 12)
})

async function loadProfile() {
  loading.value = true
  try {
    profile.value = await fetchProfile()
  } finally {
    loading.value = false
  }
}

async function onRebuild() {
  rebuilding.value = true
  try {
    await rebuildProfile()
    await loadProfile()
    ElMessage.success('画像已重新汇总')
  } catch {
    ElMessage.error('重新汇总失败，请稍后重试')
  } finally {
    rebuilding.value = false
  }
}

// ---------------------------------------------------------------- 报告上传

const pasteVisible = ref(false)
const reportText = ref('')

async function onFileUpload(options: { file: File }) {
  submitting.value = true
  try {
    const res = await uploadReportFile(options.file)
    await loadProfile()
    ElMessage.success(res.ready ? '报告已解析，画像已更新' : '报告已上传')
  } catch (e: any) {
    ElMessage.error(
      e?.response?.data?.detail || '解析失败：若是扫描件请确认 OCR 可用，或改为粘贴文字'
    )
  } finally {
    submitting.value = false
  }
}

async function submitPaste() {
  const text = reportText.value.trim()
  if (text.length < 10) {
    ElMessage.warning('内容太短，请至少粘贴 10 个字')
    return
  }
  submitting.value = true
  try {
    await uploadReport(text)
    pasteVisible.value = false
    reportText.value = ''
    await loadProfile()
    ElMessage.success('报告已解析，画像已更新')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '解析失败，请检查内容')
  } finally {
    submitting.value = false
  }
}

// ---------------------------------------------------------------- 问卷

const surveyVisible = ref(false)
const allDomains = ref<string[]>([])
const domains = ref<string[]>([])
const questions = ref<SurveyQuestion[]>([])
const answers = reactive<Record<string, any>>({})
const loadingQuestions = ref(false)
const fallbackTip = ref('')

async function openSurvey() {
  surveyVisible.value = true
  if (!allDomains.value.length) {
    try {
      allDomains.value = await fetchProfileDomains()
      domains.value = allDomains.value.slice(0, 4)
    } catch {
      ElMessage.error('领域列表加载失败')
    }
  }
}

async function genQuestions() {
  if (!domains.value.length) {
    ElMessage.warning('请至少选择一个方面')
    return
  }
  loadingQuestions.value = true
  try {
    const res = await generateSurvey(domains.value, 5)
    questions.value = res.questions || []
    fallbackTip.value = res.fallback ? res.message || '大模型暂不可用，已返回内置问卷' : ''
    questions.value.forEach((q) => {
      answers[q.id] = q.type === 'multiple' ? [] : ''
    })
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '问卷生成失败')
  } finally {
    loadingQuestions.value = false
  }
}

async function submitSurvey() {
  const missing = questions.value.filter((q) => {
    if (q.type === 'text') return false
    const v = answers[q.id]
    return Array.isArray(v) ? v.length === 0 : !v
  })
  if (missing.length) {
    ElMessage.warning(`还有 ${missing.length} 道题未作答`)
    return
  }
  const payload: Record<string, any> = {}
  questions.value.forEach((q) => {
    const v = answers[q.id]
    if (Array.isArray(v) ? v.length : v) payload[q.id] = v
  })
  submitting.value = true
  try {
    await submitSurveyApi(questions.value, payload)
    surveyVisible.value = false
    questions.value = []
    await loadProfile()
    ElMessage.success('画像已更新')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

// ---------------------------------------------------------------- 生命周期

onMounted(async () => {
  await loadProfile()
  // 顺手把基础信息同步进画像快照（静默，失败不影响页面）
  try {
    const info = profile.value?.basic_info || {}
    if (!info.nickname) return
    await updateProfileBasic({ nickname: info.nickname })
  } catch {
    /* 忽略 */
  }
})
</script>

<style scoped>
.counselor-page {
  max-width: 1180px;
}
.topbar {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.title-wrap h2 {
  margin: 0 0 4px;
  font-size: 20px;
}
.title-wrap p {
  margin: 0;
  font-size: 13px;
}
.grid {
  display: grid;
  grid-template-columns: 1.25fr 1fr;
  gap: 16px;
  align-items: start;
}
@media (max-width: 960px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
.side {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: space-between;
}
.small {
  font-size: 12.5px;
}
.messages {
  height: 430px;
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
.tip {
  margin: 0 0 8px;
}
.uploader :deep(.el-upload),
.uploader :deep(.el-upload-dragger) {
  width: 100%;
}
.uploader-inner {
  padding: 8px 0;
}
.uploader-icon {
  font-size: 20px;
  color: var(--primary);
}
.uploader-text {
  font-size: 13px;
  margin: 2px 0;
}
.uploader-tip {
  font-size: 11.5px;
}
.upload-actions {
  display: flex;
  gap: 8px;
  margin: 10px 0;
}
.privacy {
  margin-top: 4px;
}
.privacy :deep(.el-alert__title) {
  font-size: 12px;
  line-height: 1.6;
}
.profile-card {
  min-height: 200px;
}
.summary {
  background: #f6f8fb;
  border-left: 3px solid var(--primary);
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 13.5px;
  line-height: 1.85;
  white-space: pre-wrap;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}
.updated {
  margin-top: 8px;
}
.link {
  margin-top: 6px;
  padding-left: 0;
}
.domain-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 14px 0;
}
.q-card {
  margin-bottom: 10px;
  border: 1px solid var(--border);
}
.q-title {
  font-weight: 600;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.q-index {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.q-hint {
  margin: 4px 0 8px 28px;
}
.opts {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
}
.step-actions {
  margin-top: 16px;
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}
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
