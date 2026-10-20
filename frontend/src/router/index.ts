import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useUserStore } from '@/stores/user'

const routes: RouteRecordRaw[] = [
  // 考生端
  { path: '/', name: 'home', component: () => import('@/views/student/Home.vue') },
  { path: '/volunteer', name: 'volunteer', component: () => import('@/views/student/Volunteer.vue') },
  { path: '/university', name: 'university', component: () => import('@/views/student/University.vue') },
  { path: '/ai-chat', name: 'ai-chat', component: () => import('@/views/student/AiChat.vue') },

  // 管理端
  {
    path: '/admin',
    name: 'admin',
    component: () => import('@/views/admin/Dashboard.vue'),
    meta: { requiresAdmin: true }
  },
  {
    path: '/admin/knowledge',
    name: 'admin-knowledge',
    component: () => import('@/views/admin/Knowledge.vue'),
    meta: { requiresAdmin: true }
  },
  {
    path: '/admin/rag-eval',
    name: 'admin-rag-eval',
    component: () => import('@/views/admin/RAGEval.vue'),
    meta: { requiresAdmin: true }
  },

  // 账号（0.12.0：注册 / 个人主页）
  { path: '/login', name: 'login', component: () => import('@/views/Login.vue') },
  { path: '/register', name: 'register', component: () => import('@/views/Register.vue') },
  {
    path: '/profile',
    name: 'profile',
    component: () => import('@/views/Profile.vue'),
    // 个人主页必须登录（画像与资料都挂在 user_id 上）
    meta: { requiresLogin: true }
  },
  {
    // 0.13.0：心理与画像空间（云端心理师 + 报告上传 + 画像展示）
    path: '/counselor',
    name: 'counselor',
    component: () => import('@/views/student/Counselor.vue'),
    meta: { requiresLogin: true }
  },
  {
    // 0.14.0：人机协同志愿规划（LangGraph HITL：生成初稿 → 人工干预 → 终稿）
    path: '/plan',
    name: 'plan',
    component: () => import('@/views/student/PlanGenerator.vue'),
    meta: { requiresLogin: true }
  },

  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

/**
 * 全局守卫（0.15.0 重写）。
 *
 * ## 旧实现的两个问题
 * 1. `await userStore.loadMe()` 无条件 `await`：`/auth/me` 一超时就卡住整个导航，
 *    随后 store 又把超时当登录失效清 token —— 刷新页面必掉登录；
 * 2. 失败后没有任何分流：无论「token 真过期」还是「后端暂时不可用」，
 *    用户都被丢到登录页，且看到的是「登录已过期」，误导性很强。
 *
 * ## 新策略
 * | 场景 | 处理 |
 * |---|---|
 * | `/auth/me` 成功 | 正常放行 |
 * | 401（真失效） | store 内部已 logout，落到下面的 requiresLogin 判断跳登录页 |
 * | 网络异常 + 目标页**不需要登录** | **直接放行**，页面自己降级展示 |
 * | 网络异常 + 目标页**需要登录** | 跳登录页并带 `reason=network`，提示「网络波动」而非「已过期」 |
 */
router.beforeEach(async (to, _from, next) => {
  const userStore = useUserStore()

  // 只在「有 token 但没有用户信息」时拉取（刷新后的首次导航），且 store 内有 60s 缓存
  if (userStore.isLogin && !userStore.user) {
    await userStore.loadMe()

    // 网络层失败：绝不能因此阻断公开页面
    if (userStore.meError === 'network') {
      const needsIdentity = !!(to.meta.requiresLogin || to.meta.requiresAdmin)
      if (!needsIdentity) {
        next()
        return
      }
      next({
        path: '/login',
        query: { redirect: to.fullPath, reason: 'network' }
      })
      return
    }
  }

  if (to.meta.requiresAdmin && userStore.role !== 'admin') {
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }
  // 0.12.0：个人主页需要登录
  if (to.meta.requiresLogin && !userStore.isLogin) {
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }
  next()
})

export default router
