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

  // 登录
  { path: '/login', name: 'login', component: () => import('@/views/Login.vue') },

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
  next()
})

export default router
