<template>
  <div class="page chat-page">
    <el-card shadow="never" class="chat-card">
      <template #header>
        <div class="head">
          <b>AI 志愿助手</b>
          <el-switch v-model="useRag" active-text="知识库增强(RAG)" />
          <!-- 0.12.0：画像入口 -->
          <el-tag v-if="profileReady" type="success" size="small">已结合你的画像</el-tag>
          <el-button v-if="userStore.isLogin" size="small" type="primary" plain @click="openDrawer">
            构建专属画像
          </el-button>
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

    <!-- ============ 0.12.0 构建画像抽屉 ============ -->
    <el-drawer v-model="drawer" title="构建专属画像" size="620px" @closed="onDrawerClosed">
      <el-steps :active="stepIndex" simple class="steps">
        <el-step title="选择方式" />
        <el-step :title="track === 'survey' ? '填写问卷' : track === 'report' ? '上传报告' : '填写信息'" />
        <el-step title="画像总结" />
      </el-steps>

      <!-- ---------- Step 1：双轨制选择 ---------- -->
      <div v-if="step === 1" class="step-body">
        <p class="muted">
          画像用于让 AI 结合你的特点给出个性化建议。两种方式可以任选其一，也可以都做（会合并）。
        </p>

        <div class="track-grid">
          <div class="track-card" :class="{ on: track === 'report' }" @click="chooseTrack('report')">
            <div class="track-icon">A</div>
            <div class="track-title">上传测评报告</div>
            <div class="track-desc">
              已有 MBTI / 霍兰德等报告？上传 PDF / 图片文件或粘贴文字，AI 自动提取特质与适合的专业方向。
            </div>
          </div>
          <div class="track-card" :class="{ on: track === 'survey' }" @click="chooseTrack('survey')">
            <div class="track-icon">B</div>
            <div class="track-title">填写业务问卷</div>
            <div class="track-desc">
              没有报告？回答 3-5 道志愿填报相关选择题（地域、学费、专业偏好），AI 据此生成画像。
            </div>
          </div>
        </div>

        <div v-if="profileReady" class="current-summary">
          <div class="feature-title">当前画像</div>
          <div class="summary-text">{{ currentSummary }}</div>
        </div>
      </div>

      <!-- ---------- Step 2A：上传报告 ---------- -->
      <div v-else-if="step === 2 && track === 'report'" class="step-body">
        <el-form label-position="top">
          <el-form-item label="报告类型（选填）">
            <el-input v-model="reportHint" placeholder="例如：MBTI / 霍兰德 / 大五人格" maxlength="50" />
          </el-form-item>
          <el-form-item label="报告内容">
            <el-input
              v-model="reportText"
              type="textarea"
              :rows="10"
              maxlength="20000"
              show-word-limit
              placeholder="把报告里的文字粘贴到这里。例如：&#10;霍兰德职业兴趣测评：您的兴趣代码为 IRC（研究型-现实型-常规型）&#10;MBTI 性格类型为 INTJ&#10;特质：逻辑性强、独立思考、喜欢解决复杂问题…"
            />
          </el-form-item>
        </el-form>

        <!-- 0.12.1：直接上传文件，走独立画像接口（不写公共知识库） -->
        <el-divider content-position="left">或者直接上传文件</el-divider>
        <el-upload
          class="report-uploader"
          drag
          :auto-upload="true"
          :show-file-list="true"
          :limit="1"
          accept=".pdf,.txt,.docx,.md,.png,.jpg,.jpeg"
          :http-request="onReportUpload"
          :on-exceed="onReportExceed"
        >
          <div class="uploader-inner">
            <div class="uploader-icon">⬆</div>
            <div class="uploader-text">将报告文件拖到此处，或<em>点击上传</em></div>
            <div class="muted uploader-tip">
              支持 PDF（含扫描件，自动 OCR）/ 图片 / TXT / MD / DOCX，单个不超过 10MB
            </div>
          </div>
        </el-upload>
        <div class="muted hint privacy-hint">
          隐私说明：报告仅用于生成你自己的画像，文件解析后会立即删除，
          不会进入公共知识库，其他用户与管理员都检索不到。
        </div>

        <div class="step-actions">
          <el-button @click="step = 1">上一步</el-button>
          <el-button type="primary" :loading="submitting" @click="submitReport">开始解析文字</el-button>
        </div>
      </div>

      <!-- ---------- Step 2B-1：选领域 ---------- -->
      <div v-else-if="step === 2 && track === 'survey' && !questions.length" class="step-body">
        <p class="muted">选择你希望被了解的方面，AI 会据此出题（只问志愿填报业务，不涉及心理学量表）。</p>
        <el-checkbox-group v-model="domains" class="domain-group">
          <el-checkbox v-for="d in allDomains" :key="d" :value="d" :label="d" />
        </el-checkbox-group>
        <div class="step-actions">
          <el-button @click="step = 1">上一步</el-button>
          <el-button type="primary" :loading="loadingQuestions" @click="genQuestions">
            生成问卷
          </el-button>
        </div>
      </div>

      <!-- ---------- Step 2B-2：答题 ---------- -->
      <div v-else-if="step === 2 && track === 'survey'" class="step-body">
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
            <span class="q-index">{{ idx + 1 }}</span>
            {{ q.title }}
            <el-tag v-if="q.type === 'multiple'" size="small" type="info">多选</el-tag>
          </div>
          <div v-if="q.hint" class="muted q-hint">{{ q.hint }}</div>

          <el-radio-group v-if="q.type === 'single'" v-model="answers[q.id]" class="opts">
            <el-radio v-for="o in q.options" :key="o.value" :value="o.value">{{ o.label }}</el-radio>
          </el-radio-group>
          <el-checkbox-group v-else-if="q.type === 'multiple'" v-model="answers[q.id]" class="opts">
            <el-checkbox v-for="o in q.options" :key="o.value" :value="o.value">{{ o.label }}</el-checkbox>
          </el-checkbox-group>
          <el-input
            v-else
            v-model="answers[q.id]"
            type="textarea"
            :rows="2"
            placeholder="选填"
          />
        </el-card>

        <div class="step-actions">
          <el-button @click="restartSurvey">重新选题</el-button>
          <el-button type="primary" :loading="submitting" @click="submitSurvey">提交并生成画像</el-button>
        </div>
      </div>

      <!-- ---------- Step 3：画像结果 ---------- -->
      <div v-else class="step-body">
        <el-result icon="success" title="画像已生成">
          <template #sub-title>
            <span class="muted">之后在 AI 助手提问时会自动结合这份画像</span>
          </template>
        </el-result>

        <div class="summary-card">
          <div class="feature-title">你的画像（{{ sourceLabel }}）</div>
          <div class="summary-text">{{ summary }}</div>
        </div>

        <div v-if="featureTags.length" class="feature-block">
          <div class="feature-title">提取到的特征</div>
          <div class="tags">
            <el-tag v-for="t in featureTags" :key="t" size="small" type="info">{{ t }}</el-tag>
          </div>
        </div>

        <div class="step-actions">
          <el-button @click="goProfile">去个人主页查看</el-button>
          <el-button type="primary" @click="drawer = false">开始提问</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import ChatBubble from '@/components/ChatBubble.vue'
import { chat } from '@/api/ai'
import {
  fetchProfile,
  fetchProfileDomains,
  generateSurvey,
  submitSurvey as submitSurveyApi,
  uploadReport,
  uploadReportFile
} from '@/api/profile'
import { useKnowledgeStore } from '@/stores/knowledge'
import { useUserStore } from '@/stores/user'
import type { SurveyQuestion } from '@/types/profile'

interface Msg {
  role: 'user' | 'ai'
  text: string
  sources?: string[]
}

const userStore = useUserStore()
const knowledgeStore = useKnowledgeStore()
const route = useRoute()
const router = useRouter()

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

    // 2) 调用大模型（后端会再次检索并把资料 + 画像拼进 Prompt）
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

// ============================================================ 画像抽屉

const drawer = ref(false)
/** 1 选择方式 / 2 填写 / 3 结果 */
const step = ref<1 | 2 | 3>(1)
const track = ref<'' | 'report' | 'survey'>('')

const stepIndex = computed(() => (step.value === 1 ? 0 : step.value === 2 ? 1 : 2))

// —— 报告轨 ——
const reportText = ref('')
const reportHint = ref('')

// —— 问卷轨 ——
const allDomains = ref<string[]>([])
const domains = ref<string[]>([])
const questions = ref<SurveyQuestion[]>([])
const answers = reactive<Record<string, any>>({})
const loadingQuestions = ref(false)
const fallbackTip = ref('')

// —— 通用 ——
const submitting = ref(false)
const summary = ref('')
const currentSummary = ref('')
const profileReady = ref(false)
const profileSource = ref('')
/** Step 3 从后端返回的特征，用于展示标签 */
const featureTags = ref<string[]>([])

const sourceLabel = computed(() => {
  const map: Record<string, string> = {
    report: '来自测评报告',
    survey: '来自业务问卷',
    both: '报告 + 问卷',
    manual: '手动汇总'
  }
  return map[profileSource.value] || '已生成'
})

/** 打开抽屉：重置到第一步，并拉取当前画像与可选领域 */
async function openDrawer() {
  step.value = 1
  track.value = ''
  resetForm()
  drawer.value = true
  await refreshCurrent()
}

function resetForm() {
  reportText.value = ''
  reportHint.value = ''
  questions.value = []
  Object.keys(answers).forEach((k) => delete answers[k])
  fallbackTip.value = ''
  summary.value = ''
  featureTags.value = []
}

function onDrawerClosed() {
  // 关闭时若已生成画像，刷新一下顶部标签
  if (summary.value) refreshCurrent()
}

async function refreshCurrent() {
  try {
    const [profile, domainList] = await Promise.all([
      fetchProfile(),
      allDomains.value.length ? Promise.resolve(allDomains.value) : fetchProfileDomains()
    ])
    profileReady.value = !!profile.ready
    currentSummary.value = profile.summary_text || ''
    profileSource.value = profile.source || ''
    if (Array.isArray(domainList) && domainList.length) {
      allDomains.value = domainList
      if (!domains.value.length) domains.value = domainList.slice(0, 4)
    }
  } catch {
    // 拉取失败不阻塞抽屉使用
  }
}

function chooseTrack(t: 'report' | 'survey') {
  track.value = t
  step.value = 2
}

// ---------------- 途径 A：报告 ----------------

async function submitReport() {
  const text = reportText.value.trim()
  if (text.length < 10) {
    ElMessage.warning('报告内容太短，请粘贴至少 10 个字')
    return
  }
  submitting.value = true
  try {
    const res = await uploadReport(text, reportHint.value.trim())
    applySummary(res)
    ElMessage.success('报告解析完成')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '报告解析失败，请检查内容')
  } finally {
    submitting.value = false
  }
}

/** 0.12.1：文件版报告上传（独立接口，不写公共知识库） */
async function onReportUpload(options: { file: File }) {
  submitting.value = true
  try {
    const res = await uploadReportFile(options.file)
    applySummary(res)
    ElMessage.success('报告解析完成')
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    ElMessage.error(detail || '报告解析失败，若是扫描件请确认 OCR 通道可用，或改为粘贴文字')
  } finally {
    submitting.value = false
  }
}

function onReportExceed() {
  ElMessage.warning('一次只能上传一个报告文件')
}

// ---------------- 途径 B：问卷 ----------------

async function genQuestions() {
  if (!domains.value.length) {
    ElMessage.warning('请至少选择一个想被了解的方面')
    return
  }
  loadingQuestions.value = true
  try {
    const res = await generateSurvey(domains.value, 5)
    questions.value = res.questions || []
    fallbackTip.value = res.fallback ? res.message || '大模型暂不可用，已返回内置问卷' : ''
    // 初始化作答容器：多选给数组，其余给空串
    questions.value.forEach((q) => {
      answers[q.id] = q.type === 'multiple' ? [] : ''
    })
    if (!questions.value.length) ElMessage.warning('未能生成题目，请稍后重试')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '问卷生成失败')
  } finally {
    loadingQuestions.value = false
  }
}

async function submitSurvey() {
  // 校验：选择题必答（填空题可留空）
  const missing = questions.value.filter((q) => {
    if (q.type === 'text') return false
    const v = answers[q.id]
    return Array.isArray(v) ? v.length === 0 : !v
  })
  if (missing.length) {
    ElMessage.warning(`还有 ${missing.length} 道题未作答`)
    return
  }

  // 只提交非空答案，避免后端收到一堆空串
  const payload: Record<string, any> = {}
  questions.value.forEach((q) => {
    const v = answers[q.id]
    if (Array.isArray(v) ? v.length : v) payload[q.id] = v
  })

  submitting.value = true
  try {
    const res = await submitSurveyApi(questions.value, payload)
    applySummary(res)
    ElMessage.success('画像已生成')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '提交失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}

function restartSurvey() {
  questions.value = []
  fallbackTip.value = ''
}

// ---------------- 结果 ----------------

function applySummary(res: { summary_text: string; source: string }) {
  summary.value = res.summary_text || ''
  profileSource.value = res.source || ''
  profileReady.value = !!res.summary_text
  currentSummary.value = res.summary_text || ''
  featureTags.value = extractTags(res)
  step.value = 3
}

/** 从后端返回的特征里收集可展示的标签 */
function extractTags(res: any): string[] {
  const feats = res?.features || {}
  const tags: string[] = []
  const report = feats.report || {}
  if (report.mbti) tags.push(`MBTI ${report.mbti}`)
  if (report.holland) tags.push(`霍兰德 ${report.holland}`)
  for (const key of ['traits', 'interests', 'majors']) {
    for (const t of report[key] || []) {
      if (t && !tags.includes(t)) tags.push(String(t))
    }
  }
  const survey = feats.survey || {}
  for (const t of survey.traits || []) {
    if (t && !tags.includes(t)) tags.push(String(t))
  }
  return tags.slice(0, 12)
}

function goProfile() {
  drawer.value = false
  router.push('/profile')
}

// ---------------- 初始化 ----------------

onMounted(async () => {
  if (userStore.isLogin) {
    await refreshCurrent()
    // 从 Navbar「构建/查看画像」跳转过来时自动打开抽屉
    if (route.query.build === '1') {
      await openDrawer()
      router.replace({ path: '/ai-chat' })
    }
  }
})
</script>

<style scoped>
.chat-page {
  max-width: 900px;
}
.head {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
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

/* ---------------- 抽屉 ---------------- */
.steps {
  margin-bottom: 18px;
}
.step-body {
  padding-bottom: 12px;
}
.track-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin: 14px 0;
}
@media (max-width: 640px) {
  .track-grid {
    grid-template-columns: 1fr;
  }
}
.track-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px;
  cursor: pointer;
  transition: all 0.2s;
  height: 100%;
}
.track-card:hover {
  border-color: var(--primary);
  box-shadow: 0 2px 10px rgba(25, 118, 210, 0.08);
}
.track-card.on {
  border-color: var(--primary);
  background: #f5f9ff;
}
.track-icon {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  background: var(--primary);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 8px;
}
.track-title {
  font-weight: 600;
  margin-bottom: 4px;
}
.track-desc {
  font-size: 12.5px;
  color: var(--text-sub);
  line-height: 1.7;
}
.current-summary {
  margin-top: 16px;
}
.domain-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 14px 0;
}
.q-card {
  margin-bottom: 12px;
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
}
.q-hint {
  font-size: 12px;
  margin: 4px 0 8px 28px;
}
.opts {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 10px;
}
.step-actions {
  margin-top: 18px;
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}
.summary-card {
  background: #f6f8fb;
  border-left: 3px solid var(--primary);
  border-radius: 6px;
  padding: 14px;
  margin-bottom: 8px;
}
.summary-text {
  line-height: 1.9;
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
.hint {
  font-size: 12px;
  margin-top: -6px;
}
.tip {
  margin-bottom: 12px;
}
/* ---------------- 0.12.1 报告上传 ---------------- */
.report-uploader {
  width: 100%;
}
.uploader-inner {
  padding: 6px 0 2px;
}
.uploader-icon {
  font-size: 22px;
  color: var(--primary);
  line-height: 1.4;
}
.uploader-text {
  font-size: 13.5px;
  margin: 2px 0 4px;
}
.uploader-tip {
  font-size: 12px;
}
.privacy-hint {
  margin-top: 10px;
  padding: 8px 10px;
  background: #f0f7ff;
  border-left: 3px solid var(--primary);
  border-radius: 4px;
  line-height: 1.7;
}
</style>
