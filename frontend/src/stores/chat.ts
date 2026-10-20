import { defineStore } from 'pinia'

/**
 * 聊天记录 store（0.16.0）。
 *
 * ## 为什么用 sessionStorage 而不是 localStorage
 * `localStorage` 在同一浏览器的所有标签页共享，登录 A 账号和 B 账号
 * 会互相串号（两个标签页读到同一份记录）。`sessionStorage` 按**标签页**隔离，
 * 符合「聊天记录属于当前这次会话」的语义；关闭标签页即释放，也不会长期占空间。
 *
 * ## 存储布局
 *   key  : `gaokao_chat_<userId>`（按用户分桶，天然账号隔离）
 *   value: `{ messages, draftQuestion, sessionId, savedAt }`（JSON）
 *
 * ## 健壮性约定
 *   · 序列化 / 反序列化失败一律 `console.warn` + 降级，**不允许让页面白屏**；
 *   · 脏数据（非 JSON、结构不符）直接丢弃重建；
 *   · 单条消息超过 4000 字截断，避免撑爆 sessionStorage 配额；
 *   · 最多保留 100 条，超出丢弃最早的消息并置 `trimmed` 标志供 UI 提示。
 */

/** 存储 key 前缀 */
const STORAGE_PREFIX = 'gaokao_chat_'
/** 最多保留的消息条数 */
const MAX_MESSAGES = 100
/** 单条消息最大长度（字符），超出截断 */
const MAX_TEXT_LENGTH = 4000

export interface ChatMessage {
  id: string
  role: 'user' | 'ai'
  text: string
  sources?: string[]
  createdAt: number
}

interface State {
  messages: ChatMessage[]
  /** 输入框草稿，切换页面也不丢 */
  draftQuestion: string
  /** 当前记录归属用户；用于账号隔离 */
  ownerUserId: number | null
  /** 会话标识（每次进入聊天页生成一个新的，用于排查） */
  sessionId: string
  /** 本次会话是否发生过「更早记录被清理」，供 UI 提示 */
  trimmed: boolean
}

/** 存储 key（按用户分桶） */
function storageKey(userId: number): string {
  return `${STORAGE_PREFIX}${userId}`
}

/** 生成消息 id */
function genId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/** 生成会话 id */
function genSessionId(): string {
  return `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/** 截断超长文本 */
function truncate(text: unknown): string {
  const s = typeof text === 'string' ? text : ''
  return s.length > MAX_TEXT_LENGTH ? s.slice(0, MAX_TEXT_LENGTH) : s
}

/**
 * 读取并校验 sessionStorage 中的会话数据。
 * @returns 合法数据对象；无数据 / 脏数据 / 解析失败均返回 null（调用方按空会话处理）
 */
function readSession(userId: number): Record<string, any> | null {
  let raw: string | null = null
  try {
    raw = sessionStorage.getItem(storageKey(userId))
  } catch (e) {
    console.warn('[CHAT] sessionStorage 不可用，本次不持久化', e)
    return null
  }
  if (!raw) return null

  try {
    const data = JSON.parse(raw)
    if (!data || typeof data !== 'object' || !Array.isArray(data.messages)) {
      console.warn('[CHAT] 会话数据结构不符，已丢弃重建')
      removeSession(userId)
      return null
    }
    return data
  } catch (e) {
    console.warn('[CHAT] 会话数据解析失败（非合法 JSON），已丢弃重建', e)
    removeSession(userId)
    return null
  }
}

/** 写入 sessionStorage；失败只告警，不抛异常（避免页面白屏） */
function writeSession(
  userId: number,
  messages: ChatMessage[],
  draftQuestion: string,
  sessionId: string
): boolean {
  try {
    sessionStorage.setItem(
      storageKey(userId),
      JSON.stringify({ messages, draftQuestion, sessionId, savedAt: Date.now() })
    )
    return true
  } catch (e) {
    console.warn('[CHAT] 会话写入失败（可能超出存储配额），本次仅保留在内存', e)
    return false
  }
}

/** 删除某个用户的会话数据 */
function removeSession(userId: number): void {
  try {
    sessionStorage.removeItem(storageKey(userId))
  } catch (e) {
    console.warn('[CHAT] 会话数据删除失败', e)
  }
}

export const useChatStore = defineStore('chat', {
  state: (): State => ({
    messages: [],
    draftQuestion: '',
    ownerUserId: null,
    sessionId: genSessionId(),
    trimmed: false
  }),
  getters: {
    /** 是否为空会话（决定是否渲染欢迎语） */
    isEmpty: (s) => s.messages.length === 0
  },
  actions: {
    /**
     * 为指定用户加载会话。
     *
     * 账号隔离：若 `ownerUserId` 与传入用户不同，说明换了账号，
     * 会把**上一个账号**的记录也一并清掉，避免同浏览器里残留他人对话。
     */
    loadForUser(userId: number) {
      const id = Number(userId) || 0

      if (this.ownerUserId !== null && this.ownerUserId !== id) {
        removeSession(this.ownerUserId)
      }
      this.ownerUserId = id

      const data = readSession(id)
      if (!data) {
        this.messages = []
        this.draftQuestion = ''
        this.sessionId = genSessionId()
        this.trimmed = false
        this.persist()
        return
      }

      // 逐条校验，丢弃结构不符的条目
      const valid: ChatMessage[] = data.messages
        .filter(
          (m: any) =>
            m &&
            typeof m.text === 'string' &&
            (m.role === 'user' || m.role === 'ai')
        )
        .map((m: any) => ({
          id: typeof m.id === 'string' && m.id ? m.id : genId(),
          role: m.role as 'user' | 'ai',
          text: truncate(m.text),
          sources: Array.isArray(m.sources) ? m.sources : undefined,
          createdAt: typeof m.createdAt === 'number' ? m.createdAt : Date.now()
        }))

      this.messages = valid.slice(-MAX_MESSAGES)
      this.draftQuestion =
        typeof data.draftQuestion === 'string' ? data.draftQuestion : ''
      this.sessionId =
        typeof data.sessionId === 'string' && data.sessionId
          ? data.sessionId
          : genSessionId()
      this.trimmed = false
    },

    /** 追加一条消息并持久化；超过上限时裁剪最早的消息 */
    push(msg: { role: 'user' | 'ai'; text: string; sources?: string[] }) {
      const item: ChatMessage = {
        id: genId(),
        role: msg.role,
        text: truncate(msg.text),
        sources: msg.sources && msg.sources.length ? msg.sources : undefined,
        createdAt: Date.now()
      }
      this.messages.push(item)
      if (this.messages.length > MAX_MESSAGES) {
        this.messages = this.messages.slice(-MAX_MESSAGES)
        this.trimmed = true
      }
      this.persist()
      return item
    },

    /** 更新输入框草稿并持久化 */
    setDraft(text: string) {
      this.draftQuestion = typeof text === 'string' ? text : ''
      this.persist()
    },

    /** 清空当前会话（消息 + 草稿）并删除存储 */
    clear() {
      this.messages = []
      this.draftQuestion = ''
      this.trimmed = false
      if (this.ownerUserId !== null) {
        removeSession(this.ownerUserId)
      }
    },

    /** UI 已提示「更早的记录已清理」后复位标志 */
    acknowledgeTrimmed() {
      this.trimmed = false
    },

    /** 把当前状态写入 sessionStorage（内部使用） */
    persist() {
      if (this.ownerUserId === null) return
      writeSession(
        this.ownerUserId,
        this.messages,
        this.draftQuestion,
        this.sessionId
      )
    }
  }
})
