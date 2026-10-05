<template>
  <header class="navbar">
    <div class="inner">
      <div class="brand" @click="$router.push('/')">
        <span class="logo">高</span>
        <span class="name">高考志愿填报</span>
      </div>

      <nav class="menu">
        <router-link to="/">首页</router-link>
        <router-link to="/volunteer">志愿填报</router-link>
        <router-link to="/university">查大学</router-link>
        <router-link to="/ai-chat">AI 助手</router-link>
        <router-link v-if="userStore.isAdmin" to="/admin/knowledge">知识库管理</router-link>
      </nav>

      <div class="right">
        <template v-if="userStore.isLogin">
          <el-tag :type="userStore.isAdmin ? 'danger' : 'info'" size="small">
            {{ userStore.isAdmin ? '管理员' : '考生' }}
          </el-tag>
          <span class="uname">{{ userStore.username }}</span>
          <el-button link type="primary" @click="onLogout">退出</el-button>
        </template>
        <el-button v-else size="small" type="primary" @click="$router.push('/login')">登录</el-button>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const router = useRouter()

onMounted(() => {
  if (userStore.isLogin && !userStore.user) userStore.loadMe()
})

function onLogout() {
  userStore.logout()
  ElMessage.success('已退出登录')
  router.push('/')
}
</script>

<style scoped>
.navbar {
  background: #fff;
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 20;
}
.inner {
  max-width: 1180px;
  margin: 0 auto;
  height: 58px;
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 0 16px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-weight: 700;
}
.logo {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: var(--primary);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
}
.menu {
  display: flex;
  gap: 18px;
  flex: 1;
  font-size: 14px;
  color: var(--text-sub);
}
.menu a.router-link-exact-active {
  color: var(--primary);
  font-weight: 600;
}
.right {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}
.uname {
  color: var(--text-sub);
}
</style>
