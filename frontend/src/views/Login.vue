<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <h2>登录</h2>
      <p class="muted">管理员可进入知识库后台；考生登录后可保存档案并使用 AI 助手</p>

      <el-form :model="form" label-position="top" @submit.prevent>
        <el-form-item label="用户名">
          <el-input v-model="form.username" autocomplete="username" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            autocomplete="current-password"
            placeholder="请输入密码"
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-button type="primary" class="full" :loading="loading" @click="onSubmit">登 录</el-button>
      </el-form>

      <div class="tips muted">
        默认管理员：admin / admin123（由 backend/scripts/create_admin.py 创建）
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const router = useRouter()
const route = useRoute()

const loading = ref(false)
const form = reactive({ username: 'admin', password: 'admin123' })

async function onSubmit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const user = await userStore.login({ username: form.username, password: form.password })
    ElMessage.success(`欢迎，${user.username}`)
    const redirect = (route.query.redirect as string) || (user.role === 'admin' ? '/admin/knowledge' : '/')
    router.push(redirect)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 58px);
  padding: 30px 16px;
}
.login-card {
  width: 380px;
}
h2 {
  margin: 0 0 6px;
}
.full {
  width: 100%;
}
.tips {
  margin-top: 14px;
  font-size: 12px;
}
</style>
