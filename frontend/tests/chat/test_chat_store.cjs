/**
 * 0.16.0 验收：聊天记录会话级持久化（useChatStore）
 *
 * 用 esbuild 打包**真实的** src/stores/chat.ts，在 Node 里用真实 pinia 运行，
 * sessionStorage 用内存实现打桩。验证的是线上跑的同一份源码。
 *
 * 覆盖验收标准：
 *   ① 发 3 条 → 组件卸载重挂 → 3 条仍在
 *   ② 刷新（重建 pinia）→ 3 条仍在
 *   ③ 关闭标签页（sessionStorage 清空）→ 全新空会话
 *   ④ 草稿跨页保留
 *   ⑤ 换账号看不到上一个账号的记录
 *   ⑥ 超过 100 条只保留最新 100 条
 *   ⑦ 脏 JSON → 降级重建 + console.warn
 *
 * 运行：node tests/chat/test_chat_store.cjs
 */
const esbuild = require('esbuild')
const path = require('path')

const OUT = path.join(__dirname, '.tmp_chat.cjs')

// ---------------- sessionStorage 打桩 ----------------
function makeStorage() {
  const map = new Map()
  return {
    _map: map,
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
    clear: () => map.clear(),
    key: (i) => Array.from(map.keys())[i] ?? null,
    get length() {
      return map.size
    }
  }
}
global.sessionStorage = makeStorage()

// ---------------- 捕获 console.warn ----------------
// 只记录不转发：否则告警会把完整堆栈刷到控制台，淹没测试结果
const warnings = []
console.warn = (...args) => {
  warnings.push(args.map(String).join(' '))
}

async function main() {
  await esbuild.build({
    entryPoints: [path.join(__dirname, '../../src/stores/chat.ts')],
    bundle: true,
    format: 'cjs',
    platform: 'node',
    outfile: OUT,
    external: ['pinia'],
    logLevel: 'silent'
  })

  const { createPinia, setActivePinia } = require('pinia')
  const { useChatStore } = require(OUT)

  /** 模拟「刷新页面」：重建 pinia + 重新取 store */
  function freshStore() {
    setActivePinia(createPinia())
    return useChatStore()
  }

  const results = []
  const check = (name, cond, extra = '') => {
    results.push({ name, ok: !!cond })
    console.log(`  ${cond ? 'PASS' : 'FAIL'}  ${name}${extra ? '  ' + extra : ''}`)
  }

  // ============ ① 发 3 条 → 组件卸载重挂 ============
  console.log('=== ① 发 3 条 → 切走再切回 ===')
  let store = freshStore()
  store.loadForUser(1)
  store.push({ role: 'user', text: '问题 1' })
  store.push({ role: 'ai', text: '回答 1' })
  store.push({ role: 'user', text: '问题 2' })
  // 模拟「切到 /volunteer 再切回来」：组件卸载重建，store 数据仍在
  const afterSwitch = useChatStore()
  check('切页后仍能读到 3 条', afterSwitch.messages.length === 3,
    `实际 ${afterSwitch.messages.length} 条`)

  // ============ ② 刷新页面 ============
  console.log('\n=== ② 刷新页面（重建 pinia）===')
  store = freshStore()
  store.loadForUser(1)
  check('刷新后 3 条仍在', store.messages.length === 3,
    `实际 ${store.messages.length} 条`)
  check('刷新后内容一致', store.messages[0].text === '问题 1' &&
    store.messages[2].text === '问题 2')
  check('消息带 id 与 createdAt',
    typeof store.messages[0].id === 'string' && store.messages[0].id.length > 0 &&
    typeof store.messages[0].createdAt === 'number')

  // ============ ③ 关闭标签页重开 ============
  console.log('\n=== ③ 关闭标签页重新打开 ===')
  global.sessionStorage.clear()
  store = freshStore()
  store.loadForUser(1)
  check('重新打开是全新空会话', store.messages.length === 0)
  check('欢迎语条件成立（isEmpty）', store.isEmpty === true)

  // ============ ④ 草稿保留 ============
  console.log('\n=== ④ 输入框草稿跨页保留 ===')
  store = freshStore()
  store.loadForUser(7)
  store.setDraft('河南本科批平行志')
  store = freshStore()
  store.loadForUser(7)
  check('草稿仍在', store.draftQuestion === '河南本科批平行志',
    `实际 "${store.draftQuestion}"`)

  // ============ ⑤ 账号隔离 ============
  console.log('\n=== ⑤ 换账号登录 ===')
  store = freshStore()
  store.loadForUser(100)
  store.push({ role: 'user', text: 'A 账号的私密问题' })
  store.push({ role: 'ai', text: 'A 账号的回答' })
  check('A 账号有 2 条', store.messages.length === 2)

  store.loadForUser(200) // 切成 B
  check('B 账号看不到 A 的记录', store.messages.length === 0,
    `实际 ${store.messages.length} 条`)
  check('A 的存储键已被清除',
    global.sessionStorage.getItem('gaokao_chat_100') === null)
  check('B 拥有独立的存储键',
    global.sessionStorage.getItem('gaokao_chat_200') !== null)

  // B 自己的记录与 A 无关
  store.push({ role: 'user', text: 'B 的问题' })
  store = freshStore()
  store.loadForUser(200)
  check('B 的记录独立保存', store.messages.length === 1 &&
    store.messages[0].text === 'B 的问题')

  // ============ ⑥ 超过 100 条 ============
  console.log('\n=== ⑥ 连续发送超过 100 条 ===')
  store = freshStore()
  store.loadForUser(300)
  const t0 = Date.now()
  for (let i = 1; i <= 105; i += 1) {
    store.push({ role: i % 2 ? 'user' : 'ai', text: `第 ${i} 条` })
  }
  const cost = Date.now() - t0
  check('只保留 100 条', store.messages.length === 100,
    `实际 ${store.messages.length} 条`)
  check('保留的是最新 100 条',
    store.messages[99].text === '第 105 条' &&
    store.messages[0].text === '第 6 条')
  check('trimmed 标志已置位（UI 可提示）', store.trimmed === true)
  check(`写入不卡顿（${cost}ms < 3000ms）`, cost < 3000)

  // ============ ⑦ 脏数据降级 ============
  console.log('\n=== ⑦ 脏 JSON 降级 ===')
  global.sessionStorage.setItem('gaokao_chat_400', '{ 这不是合法 JSON')
  warnings.length = 0
  store = freshStore()
  store.loadForUser(400)
  check('页面不崩，按空会话处理', store.messages.length === 0)
  check('控制台有告警', warnings.some((w) => w.includes('[CHAT]')),
    warnings[0] ? `（${warnings[0].slice(0, 46)}…）` : '')

  // 结构不符（非 JSON 但是合法 JSON）
  global.sessionStorage.setItem('gaokao_chat_500', JSON.stringify({ foo: 1 }))
  warnings.length = 0
  store = freshStore()
  store.loadForUser(500)
  check('结构不符也降级为空会话', store.messages.length === 0)
  check('结构不符有告警', warnings.some((w) => w.includes('[CHAT]')))

  // ============ 附加：超长文本截断 + 序列化失败不白屏 ============
  console.log('\n=== 附加：超长截断与写入失败降级 ===')
  store = freshStore()
  store.loadForUser(600)
  store.push({ role: 'user', text: 'x'.repeat(5000) })
  check('超长文本被截断到 4000', store.messages[0].text.length === 4000,
    `实际 ${store.messages[0].text.length} 字`)

  // 写入失败（配额超限）
  const origSet = global.sessionStorage.setItem
  global.sessionStorage.setItem = () => {
    const e = new Error('QuotaExceededError')
    throw e
  }
  warnings.length = 0
  let threw = false
  try {
    store.push({ role: 'user', text: '写入失败也要不崩' })
  } catch (e) {
    threw = true
  }
  global.sessionStorage.setItem = origSet
  check('写入失败不抛异常（不白屏）', !threw)
  check('写入失败有告警', warnings.some((w) => w.includes('[CHAT]')))

  // ============ 汇总 ============
  console.log('\n===== 汇总 =====')
  const failed = results.filter((r) => !r.ok)
  console.log(`共 ${results.length} 项，通过 ${results.length - failed.length} 项，失败 ${failed.length} 项`)
  if (failed.length) {
    failed.forEach((f) => console.log(`  FAIL: ${f.name}`))
  }
  process.exit(failed.length ? 2 : 0)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
