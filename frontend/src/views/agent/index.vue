<template>
  <div class="page-agent">
    <div class="page-inner">
      <div class="page-header">
        <div>
          <h2 class="page-title">Agent 管理</h2>
          <p class="page-desc">创建、配置和管理智能体，支持状态管理、克隆和官方 Agent</p>
        </div>
        <a-space>
          <a-button @click="fetchOfficial">
            <crown-outlined />
            官方 Agent
          </a-button>
          <a-button type="primary" @click="openCreate">
            <plus-outlined />
            创建 Agent
          </a-button>
        </a-space>
      </div>

      <a-table
        :columns="columns"
        :data-source="agents"
        :loading="loading"
        row-key="id"
        :pagination="pagination"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <div class="agent-name-cell">
              <a-space>
                <a-tooltip :title="record.description">
                  <span class="agent-name">{{ record.name }}</span>
                </a-tooltip>
                <a-tag v-if="record.is_official" color="gold">官方</a-tag>
              </a-space>
            </div>
          </template>
          <template v-else-if="column.key === 'llm_config'">
            <a-tag v-if="record.llm_config_name" color="blue">{{ record.llm_config_name }}</a-tag>
            <a-tag v-else-if="record.llm_config_id" color="blue">ID: {{ record.llm_config_id }}</a-tag>
            <span v-else class="text-muted">未配置</span>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-badge :status="statusBadge(record.status)" :text="statusText(record.status)" />
          </template>
          <template v-else-if="column.key === 'temperature'">
            <span class="text-mono">{{ record.temperature ?? '—' }}</span>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-space :size="4" wrap>
              <a-button
                v-if="canDeploy(record.status)"
                type="link"
                size="small"
                :loading="actingId === record.id"
                @click="handleStatus(record, 'deploy')"
              >
                部署
              </a-button>
              <a-button
                v-if="canStart(record.status)"
                type="link"
                size="small"
                :loading="actingId === record.id"
                @click="handleStatus(record, 'start')"
              >
                启动
              </a-button>
              <a-button
                v-if="canPause(record.status)"
                type="link"
                size="small"
                :loading="actingId === record.id"
                @click="handleStatus(record, 'pause')"
              >
                暂停
              </a-button>
              <a-button
                v-if="canResume(record.status)"
                type="link"
                size="small"
                :loading="actingId === record.id"
                @click="handleStatus(record, 'resume')"
              >
                恢复
              </a-button>
              <a-button
                v-if="canStop(record.status)"
                type="link"
                size="small"
                danger
                :loading="actingId === record.id"
                @click="handleStatus(record, 'stop')"
              >
                停止
              </a-button>
              <a-divider type="vertical" />
              <a-button type="link" size="small" @click="openEdit(record)">编辑</a-button>
              <a-button type="link" size="small" @click="handleClone(record)">
                <copy-outlined />
                克隆
              </a-button>
              <a-popconfirm title="确定删除该 Agent？" @confirm="handleDelete(record)">
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
      :title="isEdit ? '编辑 Agent' : '创建 Agent'"
      :confirm-loading="submitting"
      width="640px"
      @ok="handleSubmit"
      @cancel="modalVisible = false"
    >
      <a-form ref="formRef" :model="form" :rules="rules" layout="vertical">
        <a-form-item label="Agent 名称" name="name">
          <a-input v-model:value="form.name" placeholder="给 Agent 起个名字" />
        </a-form-item>
        <a-form-item label="描述" name="description">
          <a-input v-model:value="form.description" placeholder="简短描述 Agent 的用途" />
        </a-form-item>
        <a-form-item label="LLM 配置" name="llm_config_id">
          <a-select
            v-model:value="form.llm_config_id"
            placeholder="选择 LLM 配置"
            :loading="llmLoading"
            allow-clear
          >
            <a-select-option v-for="c in llmConfigs" :key="c.id" :value="c.id">
              {{ c.name }} ({{ c.provider }} / {{ c.model_name }})
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="系统提示词 (System Prompt)" name="system_prompt">
          <div class="prompt-wrapper">
            <a-textarea
              v-model:value="form.system_prompt"
              :rows="5"
              placeholder="定义 Agent 的角色、能力和行为约束"
            />
            <a-button
              type="link"
              size="small"
              class="polish-btn"
              :loading="polishing"
              :disabled="!form.system_prompt || !form.system_prompt.trim()"
              @click="handlePolishPrompt"
            >
              <thunderbolt-outlined />
              AI 润色
            </a-button>
          </div>
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="8">
            <a-form-item label="温度 (Temperature)" name="temperature">
              <a-input-number
                v-model:value="form.temperature"
                :min="0"
                :max="2"
                :step="0.1"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="Top P" name="top_p">
              <a-input-number
                v-model:value="form.top_p"
                :min="0"
                :max="1"
                :step="0.1"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="Max Tokens" name="max_tokens">
              <a-input-number
                v-model:value="form.max_tokens"
                :min="1"
                :max="128000"
                :step="256"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
        </a-row>
      </a-form>
    </a-modal>

    <!-- 官方 Agent Modal -->
    <a-modal v-model:open="officialVisible" title="官方 Agent 模板" width="720px" :footer="null">
      <a-list
        :data-source="officialAgents"
        :loading="officialLoading"
        item-layout="horizontal"
      >
        <template #renderItem="{ item }">
          <a-list-item>
            <a-list-item-meta :title="item.name" :description="item.description">
              <template #avatar>
                <a-avatar style="background-color: #faad14">
                  <crown-outlined />
                </a-avatar>
              </template>
            </a-list-item-meta>
            <template #actions>
              <a-button type="primary" size="small" @click="handleCloneOfficial(item)">
                <plus-outlined />
                添加
              </a-button>
            </template>
          </a-list-item>
        </template>
        <template #header>
          <span style="color: #8c8c8c">点击「添加」可克隆官方 Agent 到你的列表</span>
        </template>
      </a-list>
    </a-modal>
    <!-- AI 润色对比弹窗 -->
    <a-modal
      v-model:open="polishVisible"
      title="AI 润色系统提示词"
      width="900px"
      :footer="null"
      :mask-closable="false"
    >
      <div class="polish-compare">
        <a-row :gutter="16">
          <a-col :span="12">
            <div class="polish-panel">
              <div class="polish-panel-header">
                <span class="polish-panel-title">原始提示词</span>
                <a-tag color="default">只读</a-tag>
              </div>
              <a-textarea
                :value="polishOriginal"
                :rows="16"
                readonly
                class="polish-textarea-readonly"
              />
            </div>
          </a-col>
          <a-col :span="12">
            <div class="polish-panel">
              <div class="polish-panel-header">
                <span class="polish-panel-title">润色结果</span>
                <a-tag color="purple">可编辑</a-tag>
              </div>
              <a-textarea
                v-model:value="polishResult"
                :rows="16"
                placeholder="润色后的提示词将显示在这里，您可以直接编辑修改"
              />
            </div>
          </a-col>
        </a-row>
        <div class="polish-footer">
          <a-space>
            <a-button
              type="primary"
              ghost
              :loading="polishing"
              :disabled="!polishResult || !polishResult.trim()"
              @click="handleRepolish"
            >
              <thunderbolt-outlined />
              再次 AI 润色
            </a-button>
          </a-space>
          <a-space>
            <a-button @click="polishVisible = false">取消</a-button>
            <a-button type="primary" @click="handleConfirmPolish">确认使用</a-button>
          </a-space>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  PlusOutlined,
  CopyOutlined,
  CrownOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons-vue'
import { agentApi, llmConfigApi } from '@/api'

const agents = ref([])
const loading = ref(false)
const submitting = ref(false)
const actingId = ref(null)
const modalVisible = ref(false)
const isEdit = ref(false)
const formRef = ref()

const llmConfigs = ref([])
const llmLoading = ref(false)

const officialVisible = ref(false)
const officialAgents = ref([])
const officialLoading = ref(false)
const polishing = ref(false)

// AI 润色对比弹窗状态
const polishVisible = ref(false)
const polishOriginal = ref('')
const polishResult = ref('')

const pagination = reactive({
  current: 1,
  pageSize: 20,
  total: 0,
  showSizeChanger: true,
  showTotal: (t) => `共 ${t} 条`,
})

const columns = [
  { title: 'Agent 名称', key: 'name', ellipsis: true },
  { title: 'LLM 配置', key: 'llm_config', width: 180 },
  { title: '状态', key: 'status', width: 120 },
  { title: 'Temperature', key: 'temperature', width: 120 },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 180, ellipsis: true },
  { title: '操作', key: 'action', width: 360, fixed: 'right' },
]

const defaultForm = () => ({
  name: '',
  description: '',
  system_prompt: '',
  llm_config_id: undefined,
  temperature: 0.7,
  top_p: 1.0,
  max_tokens: 2048,
})

const form = reactive(defaultForm())

const rules = {
  name: [{ required: true, message: '请输入 Agent 名称' }],
  llm_config_id: [{ required: true, message: '请选择 LLM 配置' }],
}

// ============ 状态映射 ============
function statusText(s) {
  const map = {
    draft: '草稿',
    deployed: '已部署',
    running: '运行中',
    paused: '已暂停',
    stopped: '已停止',
    error: '异常',
  }
  return map[s] || s || '未知'
}

function statusBadge(s) {
  const map = {
    draft: 'default',
    deployed: 'processing',
    running: 'success',
    paused: 'warning',
    stopped: 'error',
    error: 'error',
  }
  return map[s] || 'default'
}

function canDeploy(s) {
  return s === 'draft'
}
function canStart(s) {
  return s === 'deployed' || s === 'stopped'
}
function canPause(s) {
  return s === 'running'
}
function canResume(s) {
  return s === 'paused'
}
function canStop(s) {
  return s === 'running' || s === 'paused' || s === 'deployed'
}

// ============ 数据加载 ============
async function fetchList() {
  loading.value = true
  try {
    const res = await agentApi.list({
      page: pagination.current,
      page_size: pagination.pageSize,
    })
    if (Array.isArray(res)) {
      agents.value = res
      pagination.total = res.length
    } else if (res?.items) {
      agents.value = res.items
      pagination.total = res.total ?? res.items.length
    } else if (res?.list) {
      agents.value = res.list
      pagination.total = res.total ?? res.list.length
    } else {
      agents.value = res?.data || []
      pagination.total = res?.total || agents.value.length
    }
  } catch (e) {
  } finally {
    loading.value = false
  }
}

async function fetchLlmConfigs() {
  llmLoading.value = true
  try {
    const res = await llmConfigApi.list({ page: 1, page_size: 100 })
    llmConfigs.value = Array.isArray(res) ? res : res?.items || res?.list || res?.data || []
  } catch (e) {
  } finally {
    llmLoading.value = false
  }
}

async function fetchOfficial() {
  officialVisible.value = true
  officialLoading.value = true
  try {
    const res = await agentApi.official()
    officialAgents.value = Array.isArray(res) ? res : res?.items || res?.list || res?.data || []
  } catch (e) {
  } finally {
    officialLoading.value = false
  }
}

function handleTableChange(pag) {
  pagination.current = pag.current
  pagination.pageSize = pag.pageSize
  fetchList()
}

// ============ 创建/编辑 ============
function openCreate() {
  isEdit.value = false
  Object.assign(form, defaultForm())
  if (llmConfigs.value.length === 0) fetchLlmConfigs()
  modalVisible.value = true
}

function openEdit(record) {
  isEdit.value = true
  Object.assign(form, {
    ...defaultForm(),
    ...record,
  })
  if (llmConfigs.value.length === 0) fetchLlmConfigs()
  modalVisible.value = true
}

async function handleSubmit() {
  try {
    await formRef.value.validate()
    submitting.value = true
    if (isEdit.value) {
      await agentApi.update(form.id, { ...form })
      message.success('更新成功')
    } else {
      await agentApi.create({ ...form })
      message.success('创建成功')
    }
    modalVisible.value = false
    fetchList()
  } catch (e) {
  } finally {
    submitting.value = false
  }
}

async function handleDelete(record) {
  try {
    await agentApi.remove(record.id)
    message.success('删除成功')
    fetchList()
  } catch (e) {}
}

async function handleStatus(record, action) {
  actingId.value = record.id
  try {
    await agentApi.status(record.id, action)
    message.success(`操作 [${action}] 已执行`)
    fetchList()
  } catch (e) {
  } finally {
    actingId.value = null
  }
}

async function handleClone(record) {
  try {
    await agentApi.clone(record.id)
    message.success('克隆成功')
    fetchList()
  } catch (e) {}
}

async function handleCloneOfficial(item) {
  try {
    // 官方 Agent 通过克隆接口添加
    await agentApi.clone(item.id)
    message.success(`已添加官方 Agent [${item.name}]`)
    officialVisible.value = false
    fetchList()
  } catch (e) {}
}

async function handlePolishPrompt() {
  if (!form.system_prompt || !form.system_prompt.trim()) return
  // 保存原始提示词，打开对比弹窗
  polishOriginal.value = form.system_prompt
  polishResult.value = ''
  polishVisible.value = true
  polishing.value = true
  try {
    const res = await agentApi.polishPrompt(form.system_prompt)
    if (res?.polished_prompt) {
      polishResult.value = res.polished_prompt
      if (res.fallback) {
        message.warning('润色完成（已自动降级为模型默认参数）')
      }
    } else {
      message.warning('润色结果为空，请重试')
    }
  } catch (e) {
    message.error('AI 润色失败，请稍后重试')
  } finally {
    polishing.value = false
  }
}

async function handleRepolish() {
  if (!polishResult.value || !polishResult.value.trim()) return
  polishing.value = true
  try {
    const res = await agentApi.polishPrompt(polishResult.value)
    if (res?.polished_prompt) {
      polishResult.value = res.polished_prompt
      if (res.fallback) {
        message.warning('润色完成（已自动降级为模型默认参数）')
      } else {
        message.success('AI 润色完成')
      }
    } else {
      message.warning('润色结果为空，请重试')
    }
  } catch (e) {
    message.error('AI 润色失败，请稍后重试')
  } finally {
    polishing.value = false
  }
}

function handleConfirmPolish() {
  if (!polishResult.value || !polishResult.value.trim()) {
    message.warning('润色结果为空，无法应用')
    return
  }
  form.system_prompt = polishResult.value
  polishVisible.value = false
  message.success('已应用润色后的系统提示词')
}

onMounted(() => {
  fetchList()
  fetchLlmConfigs()
})
</script>

<style scoped>
.page-agent {
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

.agent-name {
  font-weight: 500;
}

.text-muted {
  color: #bfbfbf;
}

.text-mono {
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.prompt-wrapper {
  position: relative;
}

.polish-btn {
  position: absolute;
  right: 4px;
  bottom: -28px;
  padding: 0 4px;
  font-size: 12px;
  color: #722ed1;
}

.polish-btn:hover {
  color: #531dab;
}

.polish-compare {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.polish-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.polish-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.polish-panel-title {
  font-weight: 600;
  font-size: 14px;
  color: #262626;
}

.polish-textarea-readonly {
  background: #fafafa;
}

.polish-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 8px;
  border-top: 1px solid #f0f0f0;
}
</style>
