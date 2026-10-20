/**
 * 验证（问题 1）：拦截器 401 → 触发回调 → 同步清 store（0.15.1）
 *
 * 做法：用 esbuild 把**真实的** src/api/request.ts 打包成 CJS，
 * 只把 element-plus 打桩，然后注入一个假的 axios adapter 返回 401/超时。
 * 验证的是线上跑的同一份源码，而不是复刻逻辑。
 *
 * 运行：node verify401.cjs
 */
const esbuild = require('esbuild')
const path = require('path')

const OUT = path.join(__dirname, '.tmp_request.cjs')

async function main() {
  await esbuild.build({
    entryPoints: [path.join(__dirname, '../../src/api/request.ts')],
    bundle: true,
    format: 'cjs',
    platform: 'node',
    outfile: OUT,
    external: ['axios'],
    logLevel: 'silent',
    plugins: [
      {
        name: 'stub-element-plus',
        setup(build) {
          build.onResolve({ filter: /^element-plus$/ }, () => ({
            path: 'element-plus',
            namespace: 'stub'
          }))
          build.onLoad({ filter: /.*/, namespace: 'stub' }, () => ({
            contents: 'export const ElMessage={error(){},warning(){},success(){}};',
            loader: 'js'
          }))
        }
      }
    ]
  })

  // ---- polyfill：request.ts 依赖 localStorage ----
  const store = new Map()
  global.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k)
  }

  // ---- 注入假 adapter：按需返回 401 / 503 / 超时 ----
  //
  // 注意：真实 axios 的 xhr adapter 会在 status 非 2xx 时 **reject** 一个
  // 带 response 的 AxiosError（走 settle）。自定义 adapter 必须同样 reject，
  // 否则 axios 会把它当成功响应，拦截器的 error 分支根本不会执行。
  const axios = require('axios')
  let mode = '401'

  const makeError = (config, response) => {
    const err = new Error(`Request failed with status code ${response.status}`)
    err.config = config
    err.response = response
    err.isAxiosError = true
    return err
  }

  axios.defaults.adapter = async (config) => {
    if (mode === 'timeout') {
      const err = new Error('timeout of 30000ms exceeded')
      err.code = 'ECONNABORTED'
      err.config = config
      throw err
    }
    const status = mode === '503' ? 503 : 401
    throw makeError(config, {
      data: { detail: status === 401 ? 'Token 无效或已过期' : 'AI 服务繁忙' },
      status,
      statusText: status === 401 ? 'Unauthorized' : 'Service Unavailable',
      headers: {},
      config
    })
  }

  const req = require(OUT)

  // ---------------- 用例 1：401 应触发回调并清 token ----------------
  let handlerCalls = 0
  req.setToken('a-valid-looking-token')
  req.setUnauthorizedHandler(() => {
    handlerCalls += 1
  })

  console.log('=== 用例 1：业务接口返回 401 ===')
  console.log('  请求前 localStorage token =', JSON.stringify(req.getToken()))
  try {
    await req.http({ url: '/auth/me' })
  } catch (e) {
    console.log('  请求被拒绝（预期）：HTTP', e.response && e.response.status)
  }
  const tokenAfter = req.getToken()
  console.log('  请求后 localStorage token =', JSON.stringify(tokenAfter))
  console.log('  onUnauthorized 回调被调用次数 =', handlerCalls)
  const pass1 = handlerCalls === 1 && tokenAfter === ''
  console.log(`  判定：${pass1 ? 'PASS' : 'FAIL'}（401 必须同步登出）`)

  // ---------------- 用例 2：超时不应触发登出 ----------------
  console.log('\n=== 用例 2：请求超时（无 response）===')
  mode = 'timeout'
  req.setToken('keep-me-token')
  handlerCalls = 0
  try {
    await req.http({ url: '/auth/me' })
  } catch (e) {
    console.log('  请求被拒绝（预期）：', e.code || e.message)
  }
  const tokenAfter2 = req.getToken()
  console.log('  请求后 localStorage token =', JSON.stringify(tokenAfter2))
  console.log('  onUnauthorized 回调被调用次数 =', handlerCalls)
  const pass2 = handlerCalls === 0 && tokenAfter2 === 'keep-me-token'
  console.log(`  判定：${pass2 ? 'PASS' : 'FAIL'}（超时必须保留 token）`)

  // ---------------- 用例 3：5xx 也不应登出 ----------------
  console.log('\n=== 用例 3：后端 503（过载保护）===')
  mode = '503'
  req.setToken('keep-on-503')
  handlerCalls = 0
  try {
    await req.http({ url: '/ai/chat' })
  } catch (e) {
    console.log('  请求被拒绝（预期）：HTTP', e.response && e.response.status)
  }
  const tokenAfter3 = req.getToken()
  const pass3 = handlerCalls === 0 && tokenAfter3 === 'keep-on-503'
  console.log('  请求后 token =', JSON.stringify(tokenAfter3), '回调次数 =', handlerCalls)
  console.log(`  判定：${pass3 ? 'PASS' : 'FAIL'}（5xx 必须保留 token）`)

  console.log('\n===== 汇总 =====')
  console.log(`用例 1（401 登出）: ${pass1 ? 'PASS' : 'FAIL'}`)
  console.log(`用例 2（超时保留）: ${pass2 ? 'PASS' : 'FAIL'}`)
  console.log(`用例 3（5xx 保留）: ${pass3 ? 'PASS' : 'FAIL'}`)
  process.exit(pass1 && pass2 && pass3 ? 0 : 2)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
