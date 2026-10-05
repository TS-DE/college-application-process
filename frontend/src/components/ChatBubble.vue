<template>
  <div class="bubble" :class="role">
    <div class="avatar">{{ role === 'user' ? '我' : 'AI' }}</div>
    <div class="content">
      <div class="text">{{ text }}</div>
      <div v-if="sources && sources.length" class="sources">
        参考：
        <el-tag v-for="s in sources" :key="s" size="small" type="success">{{ s }}</el-tag>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  role: 'user' | 'ai'
  text: string
  sources?: string[]
}>()
</script>

<style scoped>
.bubble {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}
.bubble.user {
  flex-direction: row-reverse;
}
.avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: var(--primary-light);
  color: var(--primary);
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.bubble.user .avatar {
  background: var(--primary);
  color: #fff;
}
.content {
  max-width: 78%;
}
.text {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  box-shadow: var(--shadow);
}
.bubble.user .text {
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}
.sources {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
