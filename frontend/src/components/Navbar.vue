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
        <router-link v-if="userStore.isAdmin" to="/admin/rag-eval">RAG 量化评估</router-link>
      </nav>

      <div class="right">
        <!-- 0.12.0：登录后右上角改为「头像 + 下拉菜单」 -->
        <el-dropdown v-if="userStore.isLogin" trigger="click" @command="onCommand">
          <div class="user-chip">
            <span class="avatar">{{ userStore.avatarText }}</span>
            <span class="uname">{{ userStore.displayName }}</span>
            <span class="caret">▾</span>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="profile">个人主页</el-dropdown-item>
              <el-dropdown-item command="profile-build">构建/查看画像</el-dropdown-item>
              <el-dropdown-item v-if="userStore.isAdmin" command="admin" divided>
                管理后台
              </el-dropdown-item>
              <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>

        <template v-else>
          <el-button size="small" @click="$router.push('/register')">注册</el-button>
          <el-button size="small" type="primary" @click="$router.push('/login')">登录</el-button>
        </template>
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

function onCommand(cmd: string) {
  switch (cmd) {
    case 'profile':
      router.push('/profile')
      break
    case 'profile-build':
      // 画像构建入口在 AI 助手页，带 query 让页面自动打开抽屉
      router.push({ path: '/ai-chat', query: { build: '1' } })
      break
    case 'admin':
      router.push('/admin/knowledge')
      break
    case 'logout':
      userStore.logout()
      ElMessage.success('已退出登录')
      router.push('/')
      break
  }
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
.user-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 20px;
  transition: background 0.2s;
  outline: none;
}
.user-chip:hover {
  background: #f2f4f7;
}
.avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
}
.uname {
  color: var(--text-sub);
  max-width: 90px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.caret {
  color: #9aa0a6;
  font-size: 11px;
}
</style>
