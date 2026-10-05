<template>
  <div class="page">
    <h2 class="title">查大学 / 查专业</h2>

    <el-card shadow="never">
      <el-form :inline="true" :model="query" class="filters">
        <el-form-item label="省份">
          <el-select
            v-model="query.school_province"
            placeholder="院校所在省份"
            clearable
            style="width: 140px"
          >
            <el-option v-for="p in provinceOptions" :key="p" :label="p" :value="p" />
          </el-select>
        </el-form-item>
        <el-form-item label="科类">
          <el-select v-model="query.category" style="width: 130px">
            <el-option label="物理类" value="物理类" />
            <el-option label="历史类" value="历史类" />
          </el-select>
        </el-form-item>
        <el-form-item label="批次">
          <el-select v-model="query.batch" style="width: 120px">
            <el-option label="本科批" value="本科批" />
            <el-option label="专科批" value="专科批" />
          </el-select>
        </el-form-item>
        <el-form-item label="院校">
          <el-input v-model="query.keyword" placeholder="院校名称关键字" clearable />
        </el-form-item>
        <el-form-item label="我的位次">
          <el-input v-model="query.rank" type="number" placeholder="可选，用于计算录取概率" style="width: 160px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="load">查询</el-button>
        </el-form-item>
      </el-form>

      <el-table :data="rows" v-loading="loading" size="small">
        <el-table-column prop="university_name" label="院校" min-width="180" />
        <el-table-column prop="school_province" label="省份" width="90" />
        <el-table-column prop="school_nature" label="性质" width="90" />
        <el-table-column prop="min_score" label="最低分" width="90" />
        <el-table-column prop="min_rank" label="最低位次" width="100" />
        <el-table-column label="概率" width="90">
          <template #default="{ row }">
            {{ row.probability != null ? row.probability + '%' : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link type="primary" @click="openMajors(row)">查专业</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          layout="prev, pager, next"
          :total="total"
          :page-size="query.page_size"
          :current-page="query.page"
          @current-change="(p: number) => { query.page = p; load() }"
        />
      </div>
    </el-card>

    <el-drawer v-model="drawer" :title="current ? current.university_name + ' · 专业录取' : ''" size="60%">
      <el-table :data="majors" size="small" v-loading="majorLoading">
        <el-table-column prop="major_name" label="专业" min-width="180" />
        <el-table-column prop="min_score" label="最低分" width="90" />
        <el-table-column prop="min_rank" label="最低位次" width="100" />
        <el-table-column prop="plan_count" label="计划数" width="90" />
        <el-table-column prop="tuition" label="学费" width="90" />
        <el-table-column prop="subject_req" label="选科要求" min-width="160" />
      </el-table>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { majorCountByProvince, listMajors, listUniversities } from '@/api/recommend'

const route = useRoute()

const query = reactive({
  school_province: '' as string,
  category: '物理类',
  batch: '本科批',
  keyword: '',
  rank: '',
  page: 1,
  page_size: 20
})

const rows = ref<any[]>([])
const total = ref(0)
const loading = ref(false)
const provinceOptions = ref<string[]>([])

const drawer = ref(false)
const current = ref<any>(null)
const majors = ref<any[]>([])
const majorLoading = ref(false)

async function loadProvinceOptions() {
  try {
    const res = await majorCountByProvince({ province: '河南', year: 2025, category: '物理类', batch: '本科批' })
    provinceOptions.value = (res.data || []).map((d) => d.province)
  } catch {
    provinceOptions.value = []
  }
}

async function load() {
  loading.value = true
  try {
    const res = await listUniversities({
      province: '河南',
      year: 2025,
      category: query.category,
      batch: query.batch,
      keyword: query.keyword || undefined,
      school_province: query.school_province || undefined,
      rank: query.rank || undefined,
      page: query.page,
      page_size: query.page_size
    })
    rows.value = res.items || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}

async function openMajors(row: any) {
  current.value = row
  drawer.value = true
  majorLoading.value = true
  try {
    const res = await listMajors({
      university_name: row.university_name,
      category: query.category,
      batch: query.batch
    })
    majors.value = res.items || []
  } finally {
    majorLoading.value = false
  }
}

// 支持从首页地图跳转：/university?province=浙江 / ?school_province=浙江
function applyRouteQuery() {
  const q = route.query
  const province = (q.school_province || q.province) as string | undefined
  if (province) query.school_province = province
  if (q.category) query.category = String(q.category)
  if (q.batch) query.batch = String(q.batch)
}

onMounted(async () => {
  applyRouteQuery()
  await loadProvinceOptions()
  await load()
})

watch(() => route.fullPath, async () => {
  applyRouteQuery()
  query.page = 1
  await load()
})
</script>

<style scoped>
.title {
  margin: 0 0 14px;
}
.filters {
  margin-bottom: 8px;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}
</style>
