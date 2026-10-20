/**
 * 验证（问题 2）：路由守卫对「公开页」不再 await /auth/me（0.15.1）
 *
 * 这是**结构断言**：直接读 src/router/index.ts 源码，确认
 *   ① 先算出 needsIdentity；
 *   ② needsIdentity 为 true 时才 await loadMe（并保留网络异常分流）；
 *   ③ 公开页走 `void userStore.loadMe()`（后台拉取，不 await），随后直接 next()。
 *
 * 为什么不做浏览器实测：本机未安装 playwright（无 chromium），
 * 而「导航耗时」必须在真实浏览器里量。脚本保证结构正确，
 * 耗时可按 README/CHANGELOG 里的步骤在浏览器中复核。
 *
 * 运行：node verify_guard.cjs
 */
const fs = require('fs')
const path = require('path')

const src = fs.readFileSync(path.join(__dirname, '../../src/router/index.ts'), 'utf8')

// 取出 beforeEach 函数体
const start = src.indexOf('router.beforeEach')
const body = start >= 0 ? src.slice(start) : ''

const checks = [
  {
    name: '① 先计算 needsIdentity',
    ok: /const\s+needsIdentity\s*=\s*!!\(\s*to\.meta\.requiresLogin\s*\|\|\s*to\.meta\.requiresAdmin\s*\)/.test(body)
  },
  {
    name: '② 需要身份时才 await loadMe',
    ok: /if\s*\(needsIdentity\)\s*\{[\s\S]{0,400}?await\s+userStore\.loadMe\(\)/.test(body)
  },
  {
    name: '③ 公开页用 void loadMe（不 await）',
    ok: /else\s*\{[\s\S]{0,400}?void\s+userStore\.loadMe\(\)/.test(body)
  },
  {
    name: '④ 公开页 loadMe 之后直接 next()（无阻塞判断）',
    ok: /void\s+userStore\.loadMe\(\)[\s\S]{0,200}?\n\s*\}\s*\n\s*\}/.test(body)
  },
  {
    name: '⑤ 保留网络异常分流（reason=network）',
    ok: /meError\s*===\s*'network'/.test(body) && /reason:\s*'network'/.test(body)
  }
]

console.log('=== 路由守卫结构验证（src/router/index.ts）===')
let allOk = true
for (const c of checks) {
  console.log(`  ${c.ok ? 'PASS' : 'FAIL'}  ${c.name}`)
  allOk = allOk && c.ok
}

// 额外：确认公开页分支里 loadMe 前面没有 await
const publicBlock = body.match(/else\s*\{([\s\S]{0,400}?)\}/)
if (publicBlock) {
  const block = publicBlock[1]
  const hasAwait = /await\s+userStore\.loadMe/.test(block)
  console.log(`  ${hasAwait ? 'FAIL' : 'PASS'}  ⑥ 公开页分支内不含 await loadMe`)
  allOk = allOk && !hasAwait
}

console.log('\n===== 汇总 =====')
console.log(allOk ? '结构验证全部通过' : '存在失败项')
process.exit(allOk ? 0 : 2)
