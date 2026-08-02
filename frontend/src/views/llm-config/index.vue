<template>
  <div class="page-llm-config">
    <div class="page-inner">
      <div class="page-header">
        <div>
          <h2 class="page-title">LLM 配置管理</h2>
          <p class="page-desc">管理大语言模型的接入配置，支持 OpenAI / Anthropic / Azure / DeepSeek 等多种提供商</p>
        </div>
        <a-button type="primary" @click="openCreate">
          <plus-outlined />
          新建配置
        </a-button>
      </div>

      <a-table
        :columns="columns"
        :data-source="configs"
        :loading="loading"
        row-key="id"
        :pagination="pagination"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'provider'">
            <a-tag :color="providerColor(record.provider)">{{ record.provider }}</a-tag>
          </template>
          <template v-else-if="column.key === 'is_default'">
            <a-tag v-if="record.is_default" color="green">默认</a-tag>
            <span v-else class="text-muted">—</span>
          </template>
          <template v-else-if="column.key === 'api_key'">
            <span class="text-mono">••••••••{{ maskKey(record.api_key) }}</span>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-space>
              <a-button type="link" size="small" :loading="testingId === record.id" @click="handleTest(record)">
                测试
              </a-button>
              <a-button type="link" size="small" @click="openEdit(record)">编辑</a-button>
              <a-popconfirm title="确定删除该配置？" @confirm="handleDelete(record)">
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
      :title="isEdit ? '编辑 LLM 配置' : '新建 LLM 配置'"
      :confirm-loading="submitting"
      width="600px"
      @ok="handleSubmit"
      @cancel="modalVisible = false"
    >
      <a-form ref="formRef" :model="form" :rules="rules" layout="vertical">
        <a-form-item label="配置名称" name="name">
          <a-input v-model:value="form.name" placeholder="例如：生产环境 OpenAI" />
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="提供商" name="provider">
              <a-select v-model:value="form.provider" placeholder="选择提供商" @change="handleProviderChange">
                <a-select-option v-for="p in providers" :key="p.value" :value="p.value">
                  {{ p.label }}
                </a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="模型名称" name="model_name">
              <a-input v-model:value="form.model_name" placeholder="例如：gpt-4o-mini" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item label="API Key" name="api_key">
          <a-input-password v-model:value="form.api_key" placeholder="sk-..." autocomplete="new-password" />
        </a-form-item>
        <a-form-item label="API Base URL" name="api_base_url">
          <a-input v-model:value="form.api_base_url" placeholder="https://api.openai.com/v1" />
        </a-form-item>

        <!-- 动态参数配置：根据 provider 支持的参数显示 -->
        <a-divider v-if="currentSupportedParams.length > 0" orientation="left">
          模型参数（仅显示该提供商支持的参数）
        </a-divider>
        
        <a-form-item v-if="currentSupportedParams.includes('temperature')" label="Temperature 温度" name="temperature">
          <a-slider
            v-model:value="form.default_params.temperature"
            :min="0"
            :max="2"
            :step="0.1"
            :marks="{ 0: '精确', 1: '平衡', 2: '创意' }"
          />
        </a-form-item>
        
        <a-form-item v-if="currentSupportedParams.includes('max_tokens')" label="Max Tokens 最大Token数" name="max_tokens">
          <a-input-number
            v-model:value="form.default_params.max_tokens"
            :min="1"
            :max="128000"
            :step="256"
            style="width: 100%"
            placeholder="例如：4096"
          />
        </a-form-item>
        
        <a-form-item v-if="currentSupportedParams.includes('top_p')" label="Top P" name="top_p">
          <a-slider
            v-model:value="form.default_params.top_p"
            :min="0"
            :max="1"
            :step="0.05"
            :marks="{ 0: '精准', 0.5: '平衡', 1: '多样' }"
          />
        </a-form-item>

        <a-form-item name="is_default">
          <a-switch v-model:checked="form.is_default" />
          <span class="ml-8">设为默认配置</span>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined } from '@ant-design/icons-vue'
import { llmConfigApi } from '@/api'

const configs = ref([])
const loading = ref(false)
const submitting = ref(false)
const testingId = ref(null)
const modalVisible = ref(false)
const isEdit = ref(false)
const formRef = ref()

// 各提供商支持的参数列表（从后端获取）
const providerParams = ref({})

const pagination = reactive({
  current: 1,
  pageSize: 20,
  total: 0,
  showSizeChanger: true,
  showTotal: (t) => `共 ${t} 条`,
})

const columns = [
  { title: '名称', dataIndex: 'name', key: 'name', ellipsis: true },
  { title: '提供商', dataIndex: 'provider', key: 'provider', width: 120 },
  { title: '模型', dataIndex: 'model_name', key: 'model_name', ellipsis: true },
  { title: 'API Key', dataIndex: 'api_key', key: 'api_key', ellipsis: true },
  { title: 'Base URL', dataIndex: 'api_base_url', key: 'api_base_url', ellipsis: true },
  { title: '默认', dataIndex: 'is_default', key: 'is_default', width: 80 },
  { title: '操作', key: 'action', width: 200, fixed: 'right' },
]

const providers = [
  { label: 'OpenAI', value: 'openai' },
  { label: 'Anthropic', value: 'claude' },
  { label: 'Azure OpenAI', value: 'azure' },
  { label: 'DeepSeek', value: 'deepseek' },
  { label: '通义千问 (Qwen)', value: 'qwen' },
  { label: 'Moonshot (Kimi)', value: 'moonshot' },
  { label: '智谱 AI (GLM)', value: 'zhipu' },
  { label: '百度文心', value: 'wenxin' },
  { label: 'Ollama (本地)', value: 'ollama' },
  { label: '其他', value: 'other' },
]

// 默认参数模板
const DEFAULT_PARAMS_TEMPLATE = {
  temperature: 0.7,
  max_tokens: 4096,
  top_p: 0.9,
}

const defaultForm = () => ({
  name: '',
  provider: 'openai',
  model_name: '',
  api_key: '',
  api_base_url: '',
  is_default: false,
  default_params: { ...DEFAULT_PARAMS_TEMPLATE },
})

const form = reactive(defaultForm())

// 当前选择的提供商支持的参数列表
const currentSupportedParams = computed(() => {
  return providerParams.value[form.provider] || []
})

// 提供商变更时，重置默认参数
function handleProviderChange(provider) {
  const supported = providerParams.value[provider] || []
  const newParams = {}
  if (supported.includes('temperature')) newParams.temperature = 0.7
  if (supported.includes('max_tokens')) newParams.max_tokens = 4096
  if (supported.includes('top_p')) newParams.top_p = 0.9
  form.default_params = newParams
}

const rules = {
  name: [{ required: true, message: '请输入配置名称' }],
  provider: [{ required: true, message: '请选择提供商' }],
  model_name: [{ required: true, message: '请输入模型名称' }],
}

function providerColor(p) {
  const map = {
    openai: 'green',
    anthropic: 'purple',
    azure: 'blue',
    deepseek: 'cyan',
    qwen: 'orange',
    moonshot: 'geekblue',
    zhipu: 'magenta',
    wenxin: 'red',
    ollama: 'gold',
  }
  return map[p] || 'default'
}

function maskKey(key) {
  if (!key) return ''
  const s = String(key)
  return s.length > 4 ? s.slice(-4) : s
}

async function fetchList() {
  loading.value = true
  try {
    const res = await llmConfigApi.list({
      page: pagination.current,
      page_size: pagination.pageSize,
    })
    // 兼容多种返回结构
    if (Array.isArray(res)) {
      configs.value = res
      pagination.total = res.length
    } else if (res?.items) {
      configs.value = res.items
      pagination.total = res.total ?? res.items.length
    } else if (res?.list) {
      configs.value = res.list
      pagination.total = res.total ?? res.list.length
    } else {
      configs.value = res?.data || []
      pagination.total = res?.total || configs.value.length
    }
  } catch (e) {
    // 错误已由拦截器提示
  } finally {
    loading.value = false
  }
}

function handleTableChange(pag) {
  pagination.current = pag.current
  pagination.pageSize = pag.pageSize
  fetchList()
}

function openCreate() {
  isEdit.value = false
  Object.assign(form, defaultForm())
  modalVisible.value = true
}

function openEdit(record) {
  isEdit.value = true
  const baseForm = defaultForm()
  // 编辑时回填掩码密钥（如 sk-***xxxx），让输入框显示黑点密文
  // 用户不修改则提交时自动跳过，需要更换时直接清空输入新值
  const maskedKey = record.api_key_masked || record.api_key || ''
  Object.assign(form, baseForm, {
    ...record,
    api_key: maskedKey,
    default_params: record.default_params || { ...DEFAULT_PARAMS_TEMPLATE },
  })
  modalVisible.value = true
}

async function handleSubmit() {
  try {
    await formRef.value.validate()
    submitting.value = true
    
    // 构建提交数据，清理掉不支持的参数
    const supported = providerParams.value[form.provider] || []
    const cleanedParams = {}
    for (const key of supported) {
      if (form.default_params[key] !== undefined && form.default_params[key] !== null) {
        cleanedParams[key] = form.default_params[key]
      }
    }
    
    const payload = {
      name: form.name,
      provider: form.provider,
      model_name: form.model_name,
      api_key: form.api_key,
      api_base_url: form.api_base_url,
      is_default: form.is_default,
      default_params: cleanedParams,
    }

    if (isEdit.value) {
      // 如果 api_key 未修改（仍是掩码值），则不传该字段
      const maskedKey = form.api_key_masked || ''
      if (!payload.api_key || payload.api_key === maskedKey) {
        delete payload.api_key
      }
      delete payload.api_key_masked
      await llmConfigApi.update(form.id, payload)
      message.success('更新成功')
    } else {
      await llmConfigApi.create(payload)
      message.success('创建成功')
    }
    modalVisible.value = false
    fetchList()
  } catch (e) {
    // 校验或请求错误
  } finally {
    submitting.value = false
  }
}

async function handleDelete(record) {
  try {
    await llmConfigApi.remove(record.id)
    message.success('删除成功')
    fetchList()
  } catch (e) {}
}

async function handleTest(record) {
  testingId.value = record.id
  try {
    const res = await llmConfigApi.test(record.id)
    const ok = res?.success ?? res?.ok ?? res?.status === 'ok'
    if (ok || res === true) {
      // 若后端降级使用了默认参数，给出提示
      if (res?.fallback) {
        message.warning(`配置 [${record.name}] ${res.message || '已自动降级为模型默认参数'}`)
      } else {
        message.success(`配置 [${record.name}] 连通性测试通过`)
      }
    } else {
      message.warning(`测试完成：${res?.message || res?.error || '未返回详细信息'}`)
    }
  } catch (e) {
    // 错误已提示
  } finally {
    testingId.value = null
  }
}

async function fetchProviderParams() {
  try {
    const data = await llmConfigApi.getProviderParams()
    providerParams.value = data || {}
  } catch (e) {
    // 如果接口不可用，使用默认空配置
    console.warn('获取提供商参数配置失败，使用默认配置')
    providerParams.value = {}
  }
}

onMounted(async () => {
  await fetchProviderParams()
  fetchList()
})
</script>

<style scoped>
.page-llm-config {
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

.text-muted {
  color: #bfbfbf;
}

.text-mono {
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.ml-8 {
  margin-left: 8px;
}
</style>
