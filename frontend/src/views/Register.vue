<template>
  <div class="auth-wrap">
    <el-card class="auth-card">
      <h2>注册账号</h2>
      <p class="muted">注册后可使用 AI 助手、保存志愿档案并构建专属画像</p>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
        <el-form-item label="昵称" prop="nickname">
          <el-input v-model="form.nickname" maxlength="20" placeholder="怎么称呼你，如：小明" />
        </el-form-item>
        <el-form-item label="手机号" prop="phone">
          <el-input v-model="form.phone" maxlength="11" placeholder="11 位手机号" />
        </el-form-item>
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" autocomplete="username" placeholder="登录用，至少 2 位" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="至少 6 位"
          />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirm">
          <el-input
            v-model="form.confirm"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="再输入一次密码"
            @keyup.enter="onSubmit"
          />
        </el-form-item>

        <el-button type="primary" class="full" :loading="loading" @click="onSubmit">
          注 册
        </el-button>
      </el-form>

      <div class="tips muted">
        已有账号？<el-link type="primary" @click="$router.push('/login')">去登录</el-link>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()

const formRef = ref<FormInstance>()
const loading = ref(false)

const form = reactive({
  nickname: '',
  phone: '',
  username: '',
  password: '',
  confirm: ''
})

const rules: FormRules = {
  nickname: [{ required: true, message: '请填写昵称', trigger: 'blur' }],
  phone: [
    { required: true, message: '请填写手机号', trigger: 'blur' },
    { pattern: /^1\d{10}$/, message: '手机号需为 11 位且以 1 开头', trigger: 'blur' }
  ],
  username: [
    { required: true, message: '请填写用户名', trigger: 'blur' },
    { min: 2, max: 50, message: '用户名 2-50 位', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请填写密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' }
  ],
  confirm: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    {
      validator: (_r, value, cb) => {
        if (value !== form.password) cb(new Error('两次输入的密码不一致'))
        else cb()
      },
      trigger: 'blur'
    }
  ]
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await userStore.register({
      username: form.username.trim(),
      password: form.password,
      nickname: form.nickname.trim(),
      phone: form.phone.trim()
    })
    ElMessage.success('注册成功，请登录')
    router.push({ path: '/login', query: { username: form.username.trim() } })
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 58px);
  padding: 30px 16px;
}
.auth-card {
  width: 400px;
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
  text-align: center;
}
</style>
