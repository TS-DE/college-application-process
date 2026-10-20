<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <h2>登录</h2>
      <p class="muted">管理员可进入知识库后台；考生登录后可保存档案并使用 AI 助手</p>

      <!-- 0.15.0：区分「网络波动」与「登录已过期」，避免误导用户重复输密码 -->
      <el-alert
        v-if="networkReason"
        class="net-alert"
        type="warning"
        :closable="false"
        show-icon
        title="网络波动，请重试"
        description="刚才只是网络没连上，你的登录状态仍然有效。重新登录或稍后刷新即可。"
      />

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
        还没有账号？<el-link type="primary" @click="$router.push('/register')">立即注册</el-link>
      </div>
      <div class="tips muted">
        默认管理员：admin / admin123（由 backend/scripts/create_admin.py 创建）
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { isNetworkError } from '@/api/request'

const userStore = useUserStore()
const router = useRouter()
const route = useRoute()

const loading = ref(false)

/** 0.15.0：路由守卫因网络问题跳转过来时，query 里会带 reason=network */
const networkReason = computed(() => route.query.reason === 'network')
// 0.12.0：注册成功后会带 username 回到登录页，自动回填
const form = reactive({
  username: (route.query.username as string) || 'admin',
  password: (route.query.username as string) ? '' : 'admin123'
})

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
  } catch (error) {
    // 提示语由 axios 响应拦截器统一弹出（避免重复弹两条）；
    // 这里只区分「连不上后端」的情况并打日志，便于排查。
    if (isNetworkError(error)) {
      console.warn('[LOGIN] 网络异常，登录请求未送达：', (error as any)?.message)
    }
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
/* 0.15.0：网络波动提示，与表单留出呼吸感 */
.net-alert {
  margin: 10px 0 4px;
}
.net-alert :deep(.el-alert__title) {
  font-size: 13px;
}
.net-alert :deep(.el-alert__description) {
  font-size: 12px;
  line-height: 1.6;
  margin-top: 2px;
}
.full {
  width: 100%;
}
.tips {
  margin-top: 14px;
  font-size: 12px;
}
</style>
