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

router.beforeEach(async (to, _from, next) => {
  const userStore = useUserStore()
  if (userStore.isLogin && !userStore.user) {
    await userStore.loadMe()
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
