<template>
  <el-dialog v-model="visible" title="上传知识库文件" width="520px" :close-on-click-modal="false">
    <el-upload
      drag
      :action="uploadUrl"
      :headers="headers"
      :show-file-list="true"
      :accept="'.pdf,.txt,.docx'"
      :before-upload="beforeUpload"
      :on-success="handleSuccess"
      :on-error="handleError"
    >
      <el-icon class="upload-icon"><UploadFilled /></el-icon>
      <div class="el-upload__text">将文件拖到此处，或<em>点击上传</em></div>
      <template #tip>
        <div class="el-upload__tip">支持 PDF、TXT、DOCX，单个文件不超过 20MB，上传后自动切片并向量化</div>
      </template>
    </el-upload>

    <div v-if="uploading" class="progress">
      <el-progress :percentage="90" :indeterminate="true" :show-text="false" />
      <span class="muted">正在解析并写入向量库，请稍候…</span>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, type UploadProps } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import { getToken } from '@/api/request'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'success'): void }>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v)
})

const uploading = ref(false)
const uploadUrl = '/api/knowledge/upload'
const headers = computed(() => ({ Authorization: `Bearer ${getToken()}` }))

const beforeUpload: UploadProps['beforeUpload'] = (file) => {
  const ok = /\.(pdf|txt|docx)$/i.test(file.name)
  if (!ok) {
    ElMessage.error('仅支持 PDF / TXT / DOCX 文件')
    return false
  }
  if (file.size > 20 * 1024 * 1024) {
    ElMessage.error('文件不能超过 20MB')
    return false
  }
  uploading.value = true
  return true
}

const handleSuccess: UploadProps['onSuccess'] = (resp: any) => {
  uploading.value = false
  if (resp?.code === 200) {
    ElMessage.success(`上传成功，切片 ${resp?.data?.chunk_count ?? 0} 段`)
    emit('success')
    visible.value = false
  } else {
    ElMessage.error(resp?.msg || '上传失败')
  }
}

const handleError: UploadProps['onError'] = (err: any) => {
  uploading.value = false
  let msg = '上传失败'
  try {
    const detail = JSON.parse(err?.message || '{}')?.detail
    msg = detail || msg
  } catch {
    /* ignore */
  }
  ElMessage.error(msg)
}
</script>

<style scoped>
.upload-icon {
  font-size: 52px;
  color: var(--primary);
}
.progress {
  margin-top: 12px;
}
</style>
