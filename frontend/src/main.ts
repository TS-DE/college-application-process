import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'
import { setUnauthorizedHandler } from './api/request'
import { useUserStore } from './stores/user'
import './styles/main.css'

const app = createApp(App)

// 0.15.1：pinia 实例必须在这里显式持有，供下面装配 401 回调时传入
const pinia = createPinia()

app.use(pinia)
app.use(router)
app.use(ElementPlus, { locale: zhCn })

/**
 * 装配「401 → 登出」回调（0.15.1）。
 *
 * 拦截器只会清 localStorage，Pinia 里的 `token`/`user` 仍在内存，
 * 导致导航栏继续显示已登录、而所有请求都 401。
 * 这里把 store 的 `logout()` 注入给基础设施层，让内存态与本地存储一起清空。
 *
 * 注意：必须传 `pinia` 实例——`useUserStore()` 在组件外调用时需要它，
 * 否则会拿不到已激活的 pinia。
 */
setUnauthorizedHandler(() => {
  useUserStore(pinia).logout()
})

app.mount('#app')
