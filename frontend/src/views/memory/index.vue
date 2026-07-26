<template>
  <div class="page-memory">
    <div class="page-inner">
      <div class="page-header">
        <div>
          <h2 class="page-title">记忆管理</h2>
          <p class="page-desc">查看和编辑 Agent 的长期记忆，浏览短期记忆（会话上下文）</p>
        </div>
        <div class="header-controls">
          <a-select
            v-model:value="selectedAgentId"
            placeholder="选择 Agent"
            style="width: 280px"
            :loading="agentLoading"
            show-search
            option-filter-prop="label"
            @change="handleAgentChange"
          >
            <a-select-option
              v-for="a in agents"
              :key="a.id"
              :value="a.id"
              :label="a.name"
            >
              <a-space>
                <span>{{ a.name }}</span>
                <a-tag v-if="a.is_official" color="gold" style="margin: 0">官方</a-tag>
              </a-space>
            </a-select-option>
          </a-select>
        </div>
      </div>

      <a-card v-if="!selectedAgentId" class="empty-card">
        <a-empty description="请先选择一个 Agent 以查看其记忆" />
      </a-card>

      <a-tabs v-else v-model:activeKey="activeTab" class="memory-tabs">
        <!-- 长期记忆 -->
        <a-tab-pane key="long-term" tab="长期记忆">
          <a-spin :spinning="longTermLoading">
            <div class="section-toolbar">
              <a-space>
                <a-button type="primary" :loading="saving" @click="handleSaveLongTerm">
                  <save-outlined />
                  保存修改
                </a-button>
                <a-button @click="handleResetLongTerm">
                  <reload-outlined />
                  重置
                </a-button>
              </a-space>
              <a-button type="link" @click="fetchSummary">
                <info-circle-outlined />
                查看记忆摘要
              </a-button>
            </div>

            <a-alert
              v-if="longTermError"
              :message="longTermError"
              type="info"
              show-icon
              style="margin-bottom: 16px"
            />

            <a-row :gutter="16">
              <a-col :span="8">
                <a-card title="用户偏好 (user_profile)" size="small" class="mem-card">
                  <a-textarea
                    v-model:value="longTermForm.user_profile"
                    :rows="12"
                    placeholder='{"name":"...", "preferences":{...}}'
                    class="mem-textarea"
                  />
                  <p class="mem-hint">用户的个人信息与偏好（JSON）</p>
                </a-card>
              </a-col>
              <a-col :span="8">
                <a-card title="环境事实 (environment_facts)" size="small" class="mem-card">
                  <a-textarea
                    v-model:value="longTermForm.environment_facts"
                    :rows="12"
                    placeholder='["事实1", "事实2"]'
                    class="mem-textarea"
                  />
                  <p class="mem-hint">用户所在环境的关键事实（JSON 数组）</p>
                </a-card>
              </a-col>
              <a-col :span="8">
                <a-card title="经验教训 (experience)" size="small" class="mem-card">
                  <a-textarea
                    v-model:value="longTermForm.experience"
                    :rows="12"
                    placeholder='["经验1", "经验2"]'
                    class="mem-textarea"
                  />
                  <p class="mem-hint">从历史交互中沉淀的经验（JSON 数组）</p>
                </a-card>
              </a-col>
            </a-row>
          </a-spin>
        </a-tab-pane>

        <!-- 短期记忆 -->
        <a-tab-pane key="short-term" tab="短期记忆">
          <div class="section-toolbar">
            <span class="toolbar-label">选择会话：</span>
            <a-select
              v-model:value="selectedConvId"
              placeholder="选择会话查看短期记忆"
              style="width: 320px"
              :loading="convLoading"
              show-search
              option-filter-prop="label"
              @change="fetchShortTerm"
            >
              <a-select-option
                v-for="c in conversations"
                :key="c.id"
                :value="c.id"
                :label="c.title || '未命名会话'"
              >
                {{ c.title || '未命名会话' }}
                <span v-if="c.updated_at" class="conv-time">{{ formatTime(c.updated_at) }}</span>
              </a-select-option>
            </a-select>
            <a-button v-if="selectedConvId" @click="fetchShortTerm">
              <reload-outlined />
              刷新
            </a-button>
          </div>

          <a-spin :spinning="shortTermLoading">
            <a-empty
              v-if="!selectedConvId"
              description="请选择一个会话查看短期记忆"
            />
            <div v-else-if="shortTermMessages.length === 0 && !shortTermLoading" class="empty-block">
              <a-empty description="该会话暂无短期记忆数据" />
            </div>
            <div v-else class="short-term-list">
              <div
                v-for="(msg, idx) in shortTermMessages"
                :key="idx"
                class="stm-item"
                :class="msg.role || (msg.is_user ? 'user' : 'assistant')"
              >
                <div class="stm-role">
                  <a-tag :color="roleColor(msg)">
                    {{ roleText(msg) }}
                  </a-tag>
                  <span v-if="msg.created_at" class="stm-time">{{ formatTime(msg.created_at) }}</span>
                </div>
                <div class="stm-content markdown-body" v-html="renderMarkdown(msg.content || msg.text || '')"></div>
              </div>
            </div>
          </a-spin>
        </a-tab-pane>
      </a-tabs>
    </div>

    <!-- 记忆摘要 Modal -->
    <a-modal v-model:open="summaryVisible" title="记忆摘要" width="640px" :footer="null">
      <a-spin :spinning="summaryLoading">
        <div v-if="summary" class="summary-content">
          <a-descriptions :column="1" bordered size="small">
            <a-descriptions-item label="用户偏好">
              <pre class="summary-pre">{{ formatJson(summary.user_profile) }}</pre>
            </a-descriptions-item>
            <a-descriptions-item label="环境事实">
              <pre class="summary-pre">{{ formatJson(summary.environment_facts) }}</pre>
            </a-descriptions-item>
            <a-descriptions-item label="经验教训">
              <pre class="summary-pre">{{ formatJson(summary.experience) }}</pre>
            </a-descriptions-item>
            <a-descriptions-item v-if="summary.summary" label="综合摘要">
              {{ summary.summary }}
            </a-descriptions-item>
          </a-descriptions>
        </div>
        <a-empty v-else description="暂无摘要数据" />
      </a-spin>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  SaveOutlined,
  ReloadOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons-vue'
import { marked } from 'marked'
import { agentApi, conversationApi, memoryApi } from '@/api'

marked.setOptions({ breaks: true, gfm: true })

const agents = ref([])
const agentLoading = ref(false)
const selectedAgentId = ref(null)

const activeTab = ref('long-term')

// 长期记忆
const longTermLoading = ref(false)
const saving = ref(false)
const longTermError = ref('')
const longTermRaw = ref(null) // 原始返回
const longTermForm = reactive({
  user_profile: '',
  environment_facts: '',
  experience: '',
})

// 短期记忆
const conversations = ref([])
const convLoading = ref(false)
const selectedConvId = ref(null)
const shortTermLoading = ref(false)
const shortTermMessages = ref([])

// 摘要
const summaryVisible = ref(false)
const summaryLoading = ref(false)
const summary = ref(null)

function renderMarkdown(text) {
  if (!text) return ''
  try {
    return marked.parse(String(text))
  } catch (e) {
    return String(text)
  }
}

function formatTime(t) {
  if (!t) return ''
  try {
    const d = new Date(t)
    if (isNaN(d.getTime())) return t
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch (e) {
    return t
  }
}

function formatJson(v) {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'string') return v
  try {
    return JSON.stringify(v, null, 2)
  } catch (e) {
    return String(v)
  }
}

function roleText(m) {
  const r = m.role || (m.is_user ? 'user' : 'assistant')
  return r === 'user' ? '用户' : r === 'system' ? '系统' : 'Agent'
}

function roleColor(m) {
  const r = m.role || (m.is_user ? 'user' : 'assistant')
  return r === 'user' ? 'blue' : r === 'system' ? 'default' : 'green'
}

// ============ 数据加载 ============
async function fetchAgents() {
  agentLoading.value = true
  try {
    const res = await agentApi.list({ page: 1, page_size: 200 })
    agents.value = Array.isArray(res) ? res : res?.items || res?.list || res?.data || []
  } catch (e) {
  } finally {
    agentLoading.value = false
  }
}

async function handleAgentChange() {
  selectedConvId.value = null
  shortTermMessages.value = []
  await Promise.all([fetchLongTerm(), fetchConversations()])
}

async function fetchLongTerm() {
  if (!selectedAgentId.value) return
  longTermLoading.value = true
  longTermError.value = ''
  try {
    const res = await memoryApi.longTerm(selectedAgentId.value)
    longTermRaw.value = res
    // 兼容多种结构
    const data = res?.data || res?.memory || res || {}
    longTermForm.user_profile = stringifyField(data.user_profile)
    longTermForm.environment_facts = stringifyField(data.environment_facts)
    longTermForm.experience = stringifyField(data.experience)
    if (res?.message || res?.error) {
      longTermError.value = res.message || res.error
    }
  } catch (e) {
    longTermForm.user_profile = ''
    longTermForm.environment_facts = ''
    longTermForm.experience = ''
  } finally {
    longTermLoading.value = false
  }
}

function stringifyField(v) {
  if (v === null || v === undefined) return ''
  if (typeof v === 'string') return v
  try {
    return JSON.stringify(v, null, 2)
  } catch (e) {
    return String(v)
  }
}

function handleResetLongTerm() {
  fetchLongTerm()
}

async function handleSaveLongTerm() {
  if (!selectedAgentId.value) return
  // 校验 JSON
  const payload = {}
  for (const k of ['user_profile', 'environment_facts', 'experience']) {
    const raw = longTermForm[k].trim()
    if (!raw) {
      payload[k] = null
      continue
    }
    try {
      payload[k] = JSON.parse(raw)
    } catch (e) {
      message.error(`字段 [${k}] 不是合法的 JSON：${e.message}`)
      return
    }
  }
  saving.value = true
  try {
    await memoryApi.updateLongTerm(selectedAgentId.value, payload)
    message.success('长期记忆已保存')
    fetchLongTerm()
  } catch (e) {
  } finally {
    saving.value = false
  }
}

async function fetchConversations() {
  if (!selectedAgentId.value) return
  convLoading.value = true
  try {
    const res = await conversationApi.list({ agent_id: selectedAgentId.value })
    conversations.value = Array.isArray(res) ? res : res?.items || res?.list || res?.data || []
  } catch (e) {
  } finally {
    convLoading.value = false
  }
}

async function fetchShortTerm() {
  if (!selectedAgentId.value || !selectedConvId.value) return
  shortTermLoading.value = true
  try {
    const res = await memoryApi.shortTerm(selectedAgentId.value, selectedConvId.value)
    const list = Array.isArray(res)
      ? res
      : res?.items || res?.list || res?.messages || res?.data || []
    shortTermMessages.value = list.map((m) => ({
      ...m,
      role: m.role || (m.is_user ? 'user' : 'assistant'),
      content: m.content ?? m.text ?? '',
    }))
  } catch (e) {
    shortTermMessages.value = []
  } finally {
    shortTermLoading.value = false
  }
}

async function fetchSummary() {
  if (!selectedAgentId.value) return
  summaryVisible.value = true
  summaryLoading.value = true
  try {
    const res = await memoryApi.summary(selectedAgentId.value)
    summary.value = res?.data || res?.summary || res || null
  } catch (e) {
    summary.value = null
  } finally {
    summaryLoading.value = false
  }
}

onMounted(() => {
  fetchAgents()
})
</script>

<style scoped>
.page-memory {
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

.empty-card {
  margin-top: 40px;
}

.memory-tabs {
  background: #fff;
  padding: 16px;
  border-radius: 8px;
}

.section-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.toolbar-label {
  color: #595959;
}

.mem-card {
  margin-bottom: 16px;
}

.mem-textarea {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 12px;
}

.mem-hint {
  margin: 8px 0 0;
  color: #bfbfbf;
  font-size: 12px;
}

.empty-block {
  padding: 40px 0;
}

.short-term-list {
  max-height: 600px;
  overflow: auto;
}

.stm-item {
  padding: 12px 16px;
  border-radius: 6px;
  background: #fafafa;
  margin-bottom: 12px;
}

.stm-item.user {
  background: #e6f4ff;
}

.stm-role {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.stm-time {
  font-size: 11px;
  color: #bfbfbf;
}

.stm-content {
  font-size: 13px;
}

.summary-content {
  max-height: 60vh;
  overflow: auto;
}

.summary-pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.conv-time {
  margin-left: 8px;
  font-size: 11px;
  color: #bfbfbf;
}
</style>
