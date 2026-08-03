<template>
  <div class="page-skill">
    <div class="page-inner">
      <div class="page-header">
        <div>
          <h2 class="page-title">技能库管理</h2>
          <p class="page-desc">
            管理Agent可调用的技能，支持本地文件导入和在线URL拉取，渐进式披露(3级加载)
          </p>
        </div>
        <a-space>
          <a-button type="primary" @click="openCreate">
            <plus-outlined />
            新建技能
          </a-button>
          <a-button @click="openImportLocal">
            <upload-outlined />
            本地导入
          </a-button>
          <a-button @click="openImportOnline">
            <cloud-download-outlined />
            在线导入
          </a-button>
        </a-space>
      </div>

      <div class="filter-bar">
        <a-space :size="12" wrap>
          <a-input
            v-model:value="filters.keyword"
            placeholder="搜索名称/描述"
            style="width: 240px"
            allow-clear
          >
            <template #prefix><search-outlined /></template>
          </a-input>
          <a-select
            v-model:value="filters.category"
            placeholder="分类"
            style="width: 160px"
            allow-clear
          >
            <a-select-option value="general">通用</a-select-option>
            <a-select-option value="programming">编程</a-select-option>
            <a-select-option value="document">文档</a-select-option>
            <a-select-option value="drawing">绘图</a-select-option>
            <a-select-option value="data">数据</a-select-option>
            <a-select-option value="other">其他</a-select-option>
          </a-select>
          <a-select
            v-model:value="filters.source"
            placeholder="来源"
            style="width: 160px"
            allow-clear
          >
            <a-select-option value="local">本地</a-select-option>
            <a-select-option value="online">在线</a-select-option>
            <a-select-option value="auto_generated">自动生成</a-select-option>
          </a-select>
          <a-switch
            v-model:checked="filters.enabled"
            checked-children="已启用"
            un-checked-children="未启用"
            @change="handleSearch"
          />
          <a-button type="primary" @click="handleSearch">
            <search-outlined />
            查询
          </a-button>
          <a-button @click="handleReset">
            <reload-outlined />
            重置
          </a-button>
        </a-space>
      </div>

      <a-table
        :columns="columns"
        :data-source="skills"
        :loading="loading"
        row-key="id"
        :pagination="pagination"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <div class="skill-name-cell">
              <div class="skill-name">{{ record.name }}</div>
              <a-tooltip :title="record.description">
                <div class="skill-desc">{{ truncate(record.description, 80) }}</div>
              </a-tooltip>
            </div>
          </template>
          <template v-else-if="column.key === 'category'">
            <a-tag :color="categoryColor(record.category)">{{ categoryText(record.category) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'version_source'">
            <div class="version-source">
              <span class="skill-version">v{{ record.version || '1.0.0' }}</span>
              <a-tag :color="sourceColor(record.source)" class="source-tag">
                {{ sourceText(record.source) }}
              </a-tag>
            </div>
          </template>
          <template v-else-if="column.key === 'levels'">
            <span class="levels-badge">
              <appstore-outlined />
              {{ (record.levels?.length || 0) > 0 ? `${record.levels.length}级${(record.levels?.length || 0) >= 3 ? '完整' : ''}` : '-' }}
            </span>
          </template>
          <template v-else-if="column.key === 'enabled'">
            <a-switch
              :checked="record.enabled !== false"
              :loading="togglingId === record.id"
              @change="(checked) => handleToggle(record, checked)"
            />
          </template>
          <template v-else-if="column.key === 'usage'">
            <div class="usage-cell">
              <div class="usage-count">
                <span class="text-label">调用:</span>
                <span class="text-mono">{{ record.usage_count || 0 }}</span>
              </div>
              <div class="success-rate">
                <span class="text-label">成功率:</span>
                <a-progress
                  :percent="Number(record.success_rate || 0) * 100"
                  :show-info="false"
                  size="small"
                  style="width: 80px; display: inline-block; vertical-align: middle"
                />
                <span class="rate-text">{{ ((record.success_rate || 0) * 100).toFixed(0) }}%</span>
              </div>
            </div>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-space :size="4" wrap>
              <a-button type="link" size="small" @click="openDetailDrawer(record)">
                <eye-outlined />
                详情
              </a-button>
              <a-button type="link" size="small" @click="openProgressiveDrawer(record)">
                <appstore-outlined />
                渐进式查看
              </a-button>
              <a-divider type="vertical" />
              <a-button type="link" size="small" @click="openEdit(record)">编辑</a-button>
              <a-popconfirm title="确定删除该技能？" @confirm="handleDelete(record)">
                <a-button type="link" size="small" danger>删除</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </div>

    <!-- 创建/编辑 Modal -->
    <a-modal
      v-model:open="modalVisible"
      :title="isEdit ? '编辑技能' : '新建技能'"
      :confirm-loading="submitting"
      width="680px"
      @ok="handleSubmit"
      @cancel="modalVisible = false"
    >
      <a-form ref="formRef" :model="form" :rules="rules" layout="vertical">
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="技能名称" name="name">
              <a-input v-model:value="form.name" placeholder="给技能起个名字" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="分类" name="category">
              <a-select v-model:value="form.category" placeholder="选择分类">
                <a-select-option value="general">通用</a-select-option>
                <a-select-option value="programming">编程</a-select-option>
                <a-select-option value="document">文档</a-select-option>
                <a-select-option value="drawing">绘图</a-select-option>
                <a-select-option value="data">数据</a-select-option>
                <a-select-option value="other">其他</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item label="描述" name="description">
          <a-input v-model:value="form.description" placeholder="简短描述该技能的用途" />
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="8">
            <a-form-item label="版本" name="version">
              <a-input v-model:value="form.version" placeholder="1.0.0" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="作者" name="author">
              <a-input v-model:value="form.author" placeholder="作者名称" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="标签" name="tags">
              <a-select
                v-model:value="form.tags"
                mode="tags"
                placeholder="回车添加标签"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
        </a-row>

        <a-divider orientation="left">技能内容（3级渐进式）</a-divider>

        <a-form-item label="Level 0 概要" name="level0">
          <a-textarea
            v-model:value="form.level0"
            :rows="3"
            placeholder="一句话/简短摘要，≤300字，最高优先级加载"
            :maxlength="300"
            show-count
          />
        </a-form-item>
        <a-form-item label="Level 1 完整正文" name="level1">
          <a-textarea
            v-model:value="form.level1"
            :rows="8"
            placeholder="完整技能说明，≤3000字，常规加载"
            :maxlength="3000"
            show-count
          />
        </a-form-item>

        <a-collapse v-model:activeKey="level2ActiveKey" :bordered="false">
          <a-collapse-panel key="level2" header="Level 2 深度说明（默认收起，高级场景加载，≤10000字）">
            <a-form-item label="Level 2 深度说明" name="level2">
              <a-textarea
                v-model:value="form.level2"
                :rows="12"
                placeholder="深度使用说明、边界条件、示例代码等，≤10000字"
                :maxlength="10000"
                show-count
              />
            </a-form-item>
          </a-collapse-panel>
        </a-collapse>
      </a-form>
    </a-modal>

    <!-- 本地导入 Modal (使用 a-upload customRequest) -->
    <a-modal
      v-model:open="importLocalVisible"
      title="本地导入技能文件"
      :confirm-loading="importLocalSubmitting"
      @ok="handleImportLocal"
      @cancel="importLocalVisible = false"
    >
      <div class="import-tip">
        <info-circle-outlined />
        支持格式：<span class="text-mono">.md</span> / <span class="text-mono">.skill</span> / <span class="text-mono">.json</span>
      </div>
      <a-upload-dragger
        v-model:file-list="importLocalFileList"
        :before-upload="() => false"
        :max-count="1"
        accept=".md,.skill,.json"
      >
        <p class="ant-upload-drag-icon">
          <inbox-outlined />
        </p>
        <p class="ant-upload-text">点击或拖拽文件到此处上传</p>
        <p class="ant-upload-hint">单个文件，导入后将自动解析生成 3 级 Level 内容</p>
      </a-upload-dragger>
    </a-modal>

    <!-- 在线导入 Modal -->
    <a-modal
      v-model:open="importOnlineVisible"
      title="在线导入技能"
      :confirm-loading="importOnlineSubmitting"
      @ok="handleImportOnline"
      @cancel="importOnlineVisible = false"
    >
      <a-form layout="vertical">
        <a-form-item label="源 URL" required>
          <a-input
            v-model:value="importOnlineForm.source_url"
            placeholder="https://example.com/skills/xxx.md"
          >
            <template #prefix>
              <link-outlined />
            </template>
          </a-input>
        </a-form-item>
        <a-form-item label="导入格式" required>
          <a-radio-group v-model:value="importOnlineForm.import_format">
            <a-radio-button value="markdown">Markdown (.md)</a-radio-button>
            <a-radio-button value="json">JSON (.json)</a-radio-button>
          </a-radio-group>
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 详情 Drawer -->
    <a-drawer
      v-model:open="detailDrawerVisible"
      :title="`技能详情 - ${currentSkill?.name || ''}`"
      width="640px"
    >
      <template v-if="currentSkill">
        <a-descriptions :column="2" bordered size="small">
          <a-descriptions-item label="名称">{{ currentSkill.name }}</a-descriptions-item>
          <a-descriptions-item label="分类">
            <a-tag :color="categoryColor(currentSkill.category)">
              {{ categoryText(currentSkill.category) }}
            </a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="版本">v{{ currentSkill.version || '1.0.0' }}</a-descriptions-item>
          <a-descriptions-item label="来源">
            <a-tag :color="sourceColor(currentSkill.source)">
              {{ sourceText(currentSkill.source) }}
            </a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="作者">{{ currentSkill.author || '-' }}</a-descriptions-item>
          <a-descriptions-item label="状态">
            <a-tag :color="currentSkill.enabled !== false ? 'green' : 'default'">
              {{ currentSkill.enabled !== false ? '已启用' : '已禁用' }}
            </a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="调用次数" :span="1">
            {{ currentSkill.usage_count || 0 }}
          </a-descriptions-item>
          <a-descriptions-item label="成功率" :span="1">
            {{ ((currentSkill.success_rate || 0) * 100).toFixed(1) }}%
          </a-descriptions-item>
          <a-descriptions-item label="标签" :span="2">
            <template v-if="currentSkill.tags?.length">
              <a-tag v-for="t in currentSkill.tags" :key="t" color="blue">{{ t }}</a-tag>
            </template>
            <span v-else class="text-muted">-</span>
          </a-descriptions-item>
          <a-descriptions-item label="描述" :span="2">
            {{ currentSkill.description || '-' }}
          </a-descriptions-item>
        </a-descriptions>

        <a-divider orientation="left">内容预览</a-divider>
        <div v-for="(lv, i) in (currentSkill.levels || [])" :key="i" class="level-preview">
          <div class="level-preview-title">
            <appstore-outlined />
            Level {{ lv.level ?? i }}
            <span class="level-meta">
              ({{ (lv.prompt_text || '').length }} 字符 / {{ lv.actual_tokens || 0 }} tokens / 预算 {{ lv.budget_tokens || '-' }})
            </span>
          </div>
          <pre class="level-preview-pre">{{ lv.prompt_text || '-' }}</pre>
        </div>
        <div v-if="!currentSkill.levels?.length" class="text-muted">暂无 Level 内容</div>
      </template>
    </a-drawer>

    <!-- 渐进式查看 Drawer -->
    <a-drawer
      v-model:open="progressiveDrawerVisible"
      :title="`渐进式查看 - ${progressiveSkill?.name || ''}`"
      width="720px"
      :mask-closable="false"
    >
      <template v-if="progressiveSkill">
        <a-tabs v-model:activeKey="progressiveActiveKey" @change="handleProgressiveTabChange">
          <a-tab-pane key="0" tab="Level 0 概要" />
          <a-tab-pane key="1" tab="Level 1 完整" />
          <a-tab-pane key="2" tab="Level 2 深度" />
        </a-tabs>

        <div class="progressive-content">
          <div v-if="progressiveLoading" class="progressive-loading">
            <a-spin size="large" />
          </div>
          <template v-else>
            <div class="token-info">
              <div class="token-info-title">
                <info-circle-outlined />
                Token 预算占用
              </div>
              <div class="token-progress">
                <div class="token-row">
                  <span class="token-label">实际使用</span>
                  <span class="token-value text-mono">{{ progressiveData?.actual_tokens || 0 }} tokens</span>
                </div>
                <a-progress
                  :percent="tokenPercent"
                  :status="tokenStatus"
                  :show-info="false"
                  style="margin: 8px 0"
                />
                <div class="token-row">
                  <span class="token-label">预算上限</span>
                  <span class="token-value text-mono">{{ progressiveData?.budget_tokens || '-' }} tokens</span>
                </div>
              </div>
              <div class="token-hint">
                <bulb-outlined />
                更高 Level 提供更详细说明，但会消耗更多上下文窗口。根据场景智能选择加载层级。
              </div>
            </div>

            <a-divider orientation="left">内容</a-divider>
            <div class="prompt-text-wrapper">
              <pre class="prompt-text-pre">{{ progressiveData?.prompt_text || '暂无内容' }}</pre>
            </div>
          </template>
        </div>
      </template>
    </a-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  PlusOutlined,
  UploadOutlined,
  CloudDownloadOutlined,
  SearchOutlined,
  ReloadOutlined,
  EyeOutlined,
  AppstoreOutlined,
  InfoCircleOutlined,
  InboxOutlined,
  LinkOutlined,
  BulbOutlined,
} from '@ant-design/icons-vue'
import { skillApi } from '@/api'

const skills = ref([])
const loading = ref(false)
const submitting = ref(false)
const togglingId = ref(null)
const modalVisible = ref(false)
const isEdit = ref(false)
const formRef = ref()
const level2ActiveKey = ref([])

const filters = reactive({
  keyword: '',
  category: undefined,
  source: undefined,
  enabled: undefined,
})

const pagination = reactive({
  current: 1,
  pageSize: 20,
  total: 0,
  showSizeChanger: true,
  showTotal: (t) => `共 ${t} 条`,
})

const columns = [
  { title: '名称 / 描述', key: 'name', width: 260, ellipsis: true },
  { title: '分类', key: 'category', width: 100 },
  { title: '版本 / 来源', key: 'version_source', width: 160 },
  { title: 'Level', key: 'levels', width: 110 },
  { title: '启用', key: 'enabled', width: 80 },
  { title: '调用 / 成功率', key: 'usage', width: 200 },
  { title: '操作', key: 'action', width: 260, fixed: 'right' },
]

const defaultForm = () => ({
  id: undefined,
  name: '',
  description: '',
  category: 'general',
  version: '1.0.0',
  author: '',
  tags: [],
  level0: '',
  level1: '',
  level2: '',
})

const form = reactive(defaultForm())

const rules = {
  name: [{ required: true, message: '请输入技能名称' }],
  category: [{ required: true, message: '请选择分类' }],
  level0: [{ max: 300, message: 'Level 0 不能超过 300 字' }],
  level1: [{ max: 3000, message: 'Level 1 不能超过 3000 字' }],
  level2: [{ max: 10000, message: 'Level 2 不能超过 10000 字' }],
}

function truncate(s, len) {
  if (!s) return ''
  const str = String(s)
  return str.length > len ? str.slice(0, len) + '...' : str
}

function categoryText(c) {
  const map = {
    general: '通用',
    programming: '编程',
    document: '文档',
    drawing: '绘图',
    data: '数据',
    other: '其他',
  }
  return map[c] || c || '其他'
}

function categoryColor(c) {
  const map = {
    general: 'default',
    programming: 'blue',
    document: 'purple',
    drawing: 'magenta',
    data: 'cyan',
    other: 'default',
  }
  return map[c] || 'default'
}

function sourceText(s) {
  const map = {
    local: '本地',
    online: '在线',
    auto_generated: '自动生成',
  }
  return map[s] || s || '未知'
}

function sourceColor(s) {
  const map = {
    local: 'green',
    online: 'blue',
    auto_generated: 'default',
  }
  return map[s] || 'default'
}

async function fetchList() {
  loading.value = true
  try {
    const params = {
      page: pagination.current,
      page_size: pagination.pageSize,
    }
    if (filters.keyword) params.keyword = filters.keyword
    if (filters.category) params.category = filters.category
    if (filters.source) params.source = filters.source
    if (filters.enabled !== undefined && filters.enabled !== null) {
      params.enabled = filters.enabled
    }
    const res = await skillApi.list(params)
    if (Array.isArray(res)) {
      skills.value = res
      pagination.total = res.length
    } else if (res?.items) {
      skills.value = res.items
      pagination.total = res.total ?? res.items.length
    } else if (res?.list) {
      skills.value = res.list
      pagination.total = res.total ?? res.list.length
    } else {
      skills.value = res?.data || []
      pagination.total = res?.total || skills.value.length
    }
  } catch (e) {
  } finally {
    loading.value = false
  }
}

function handleTableChange(pag) {
  pagination.current = pag.current
  pagination.pageSize = pag.pageSize
  fetchList()
}

function handleSearch() {
  pagination.current = 1
  fetchList()
}

function handleReset() {
  filters.keyword = ''
  filters.category = undefined
  filters.source = undefined
  filters.enabled = undefined
  pagination.current = 1
  fetchList()
}

function openCreate() {
  isEdit.value = false
  Object.assign(form, defaultForm())
  level2ActiveKey.value = []
  modalVisible.value = true
}

function openEdit(record) {
  isEdit.value = true
  const levels = record.levels || []
  Object.assign(form, {
    ...defaultForm(),
    ...record,
    level0: levels.find((l) => (l.level ?? 0) === 0)?.prompt_text || record.level0 || '',
    level1: levels.find((l) => (l.level ?? 1) === 1)?.prompt_text || record.level1 || '',
    level2: levels.find((l) => (l.level ?? 2) === 2)?.prompt_text || record.level2 || '',
    tags: record.tags || [],
  })
  level2ActiveKey.value = form.level2 ? ['level2'] : []
  modalVisible.value = true
}

function buildLevelsPayload() {
  const levels = []
  if (form.level0 && form.level0.trim()) {
    levels.push({ level: 0, prompt_text: form.level0.trim() })
  }
  if (form.level1 && form.level1.trim()) {
    levels.push({ level: 1, prompt_text: form.level1.trim() })
  }
  if (form.level2 && form.level2.trim()) {
    levels.push({ level: 2, prompt_text: form.level2.trim() })
  }
  return levels
}

async function handleSubmit() {
  try {
    await formRef.value.validate()
    submitting.value = true
    const payload = {
      name: form.name,
      description: form.description,
      category: form.category,
      version: form.version,
      author: form.author,
      tags: form.tags,
      levels: buildLevelsPayload(),
    }
    if (isEdit.value) {
      await skillApi.update(form.id, payload)
      message.success('更新成功')
    } else {
      await skillApi.create(payload)
      message.success('创建成功')
    }
    modalVisible.value = false
    fetchList()
  } catch (e) {
  } finally {
    submitting.value = false
  }
}

async function handleToggle(record, enabled) {
  togglingId.value = record.id
  try {
    await skillApi.toggle(record.id, enabled)
    message.success(enabled ? '已启用' : '已禁用')
    record.enabled = enabled
  } catch (e) {
    record.enabled = !enabled
  } finally {
    togglingId.value = null
  }
}

async function handleDelete(record) {
  try {
    await skillApi.remove(record.id)
    message.success('删除成功')
    fetchList()
  } catch (e) {}
}

// ============ 本地导入 ============
const importLocalVisible = ref(false)
const importLocalFileList = ref([])
const importLocalSubmitting = ref(false)

function openImportLocal() {
  importLocalFileList.value = []
  importLocalVisible.value = true
}

async function handleImportLocal() {
  if (importLocalFileList.value.length === 0) {
    message.warning('请先选择文件')
    return
  }
  const file = importLocalFileList.value[0].originFileObj || importLocalFileList.value[0]
  const formData = new FormData()
  formData.append('file', file)
  importLocalSubmitting.value = true
  try {
    await skillApi.importLocal(formData)
    message.success('导入成功，已生成 3 级 Level')
    importLocalVisible.value = false
    fetchList()
  } catch (e) {
  } finally {
    importLocalSubmitting.value = false
  }
}

// ============ 在线导入 ============
const importOnlineVisible = ref(false)
const importOnlineSubmitting = ref(false)
const importOnlineForm = reactive({
  source_url: '',
  import_format: 'markdown',
})

function openImportOnline() {
  importOnlineForm.source_url = ''
  importOnlineForm.import_format = 'markdown'
  importOnlineVisible.value = true
}

async function handleImportOnline() {
  if (!importOnlineForm.source_url || !importOnlineForm.source_url.trim()) {
    message.warning('请输入源 URL')
    return
  }
  importOnlineSubmitting.value = true
  try {
    await skillApi.importOnline({
      source_url: importOnlineForm.source_url.trim(),
      import_format: importOnlineForm.import_format,
    })
    message.success('在线导入成功')
    importOnlineVisible.value = false
    fetchList()
  } catch (e) {
  } finally {
    importOnlineSubmitting.value = false
  }
}

// ============ 详情 Drawer ============
const detailDrawerVisible = ref(false)
const currentSkill = ref(null)

function openDetailDrawer(record) {
  currentSkill.value = record
  detailDrawerVisible.value = true
}

// ============ 渐进式查看 Drawer ============
const progressiveDrawerVisible = ref(false)
const progressiveSkill = ref(null)
const progressiveActiveKey = ref('0')
const progressiveLoading = ref(false)
const progressiveData = ref(null)

const tokenPercent = computed(() => {
  const actual = progressiveData.value?.actual_tokens || 0
  const budget = progressiveData.value?.budget_tokens || 0
  if (!budget) return 0
  return Math.min(100, Math.round((actual / budget) * 100))
})

const tokenStatus = computed(() => {
  const p = tokenPercent.value
  if (p >= 90) return 'exception'
  if (p >= 70) return 'normal'
  return 'active'
})

function openProgressiveDrawer(record) {
  progressiveSkill.value = record
  progressiveActiveKey.value = '0'
  progressiveDrawerVisible.value = true
  progressiveData.value = null
  loadProgressive('0')
}

async function handleProgressiveTabChange(key) {
  progressiveActiveKey.value = key
  loadProgressive(key)
}

async function loadProgressive(level) {
  if (!progressiveSkill.value) return
  progressiveLoading.value = true
  progressiveData.value = null
  try {
    const data = await skillApi.progressive(progressiveSkill.value.id, Number(level))
    progressiveData.value = data || {
      level: Number(level),
      prompt_text: '',
      actual_tokens: 0,
      budget_tokens: 0,
    }
  } catch (e) {
    const levels = progressiveSkill.value.levels || []
    const lv = levels.find((l) => (l.level ?? 0) === Number(level))
    progressiveData.value = lv || {
      level: Number(level),
      prompt_text: '',
      actual_tokens: 0,
      budget_tokens: 0,
    }
  } finally {
    progressiveLoading.value = false
  }
}

onMounted(() => {
  fetchList()
})
</script>

<style scoped>
.page-skill {
  height: 100%;
  overflow: auto;
  background: #f0f2f5;
}

.page-inner {
  padding: 20px;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
}

.page-title {
  margin: 0 0 4px;
  font-size: 20px;
  font-weight: 600;
}

.page-desc {
  margin: 0;
  color: #8c8c8c;
  font-size: 13px;
}

.filter-bar {
  background: #fff;
  padding: 16px;
  border-radius: 6px;
  margin-bottom: 16px;
}

.skill-name-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.skill-name {
  font-weight: 500;
  font-size: 14px;
  color: #262626;
}

.skill-desc {
  font-size: 12px;
  color: #8c8c8c;
}

.version-source {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.skill-version {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
  color: #595959;
}

.source-tag {
  align-self: flex-start;
  margin: 0;
}

.levels-badge {
  color: #722ed1;
  font-weight: 500;
  font-size: 13px;
}

.usage-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.usage-count,
.success-rate {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.text-label {
  color: #8c8c8c;
}

.rate-text {
  font-size: 11px;
  color: #595959;
  margin-left: 4px;
}

.text-muted {
  color: #bfbfbf;
}

.text-mono {
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.import-tip {
  margin-bottom: 16px;
  padding: 8px 12px;
  background: #e6f4ff;
  border-radius: 4px;
  font-size: 13px;
  color: #1677ff;
  display: flex;
  align-items: center;
  gap: 6px;
}

.level-preview {
  margin-bottom: 16px;
}

.level-preview-title {
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 6px;
  color: #595959;
  display: flex;
  align-items: center;
  gap: 6px;
}

.level-meta {
  font-weight: 400;
  font-size: 12px;
  color: #8c8c8c;
}

.level-preview-pre {
  margin: 0;
  padding: 12px;
  background: #fafafa;
  border: 1px solid #f0f0f0;
  border-radius: 4px;
  max-height: 200px;
  overflow: auto;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.progressive-content {
  position: relative;
}

.progressive-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 300px;
}

.token-info {
  background: #fafafa;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  padding: 16px;
}

.token-info-title {
  font-weight: 600;
  font-size: 13px;
  color: #262626;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.token-progress {
  background: #fff;
  border: 1px solid #f0f0f0;
  border-radius: 4px;
  padding: 12px;
}

.token-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.token-label {
  font-size: 12px;
  color: #8c8c8c;
}

.token-value {
  font-size: 13px;
  color: #262626;
}

.token-hint {
  margin-top: 12px;
  padding: 8px 12px;
  background: #fffbe6;
  border-radius: 4px;
  font-size: 12px;
  color: #d46b08;
  display: flex;
  align-items: center;
  gap: 6px;
}

.prompt-text-wrapper {
  margin-top: 16px;
}

.prompt-text-pre {
  margin: 0;
  padding: 16px;
  background: #001529;
  color: #e6f4ff;
  border-radius: 6px;
  max-height: 400px;
  overflow: auto;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
