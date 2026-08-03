<template>
  <div class="page-chat">
    <!-- 左侧会话列表 -->
    <div class="conv-sidebar">
      <div class="conv-sidebar-header">
        <span class="conv-sidebar-title">会话列表</span>
        <a-button type="primary" size="small" @click="openNewConv">
          <plus-outlined />
          新建
        </a-button>
      </div>
      <div class="conv-list">
        <a-spin :spinning="convLoading">
          <div v-if="conversations.length === 0 && !convLoading" class="conv-empty">
            <a-empty description="暂无会话" :image="Empty.PRESENTED_IMAGE_SIMPLE" />
          </div>
          <div
            v-for="conv in conversations"
            :key="conv.id"
            class="conv-item"
            :class="{ active: conv.id === currentConvId }"
            @click="selectConversation(conv)"
          >
            <div class="conv-item-main">
              <div class="conv-item-title">
                <message-outlined class="conv-item-icon" />
                <span class="conv-item-text">{{ conv.title || '未命名会话' }}</span>
              </div>
              <div class="conv-item-meta">
                <span v-if="conv.agent_name">{{ conv.agent_name }}</span>
                <span v-if="conv.updated_at">{{ formatTime(conv.updated_at) }}</span>
              </div>
            </div>
            <a-popconfirm title="删除该会话？" placement="top" @confirm.stop="handleDeleteConv(conv)">
              <a-button type="text" size="small" class="conv-del-btn" @click.stop>
                <delete-outlined />
              </a-button>
            </a-popconfirm>
          </div>
        </a-spin>
      </div>
    </div>

    <!-- 右侧对话区域 -->
    <div class="chat-area">
      <template v-if="currentConvId">
        <!-- 顶部信息 -->
        <div class="chat-header">
          <div class="chat-header-info">
            <a-space>
              <robot-outlined />
              <span class="chat-header-title">{{ currentConv?.title || '对话' }}</span>
              <a-tag v-if="currentConv?.agent_name" color="blue">{{ currentConv.agent_name }}</a-tag>
            </a-space>
          </div>
          <div class="chat-header-actions">
            <a-tooltip title="清空当前会话消息（仅界面）">
              <a-button type="text" size="small" @click="messages = []">
                <clear-outlined />
              </a-button>
            </a-tooltip>
          </div>
        </div>

        <!-- 消息列表 -->
        <div ref="msgListRef" class="msg-list">
          <div v-if="messages.length === 0 && !streaming" class="msg-empty">
            <a-empty description="开始与 Agent 对话吧" />
          </div>
          <div
            v-for="msg in messages"
            :key="msg.id || msg._temp_id"
            class="msg-row"
            :class="msg.role"
          >
            <div class="msg-avatar">
              <a-avatar v-if="msg.role === 'user'" style="background-color: #1677ff">
                <user-outlined />
              </a-avatar>
              <a-avatar v-else style="background-color: #52c41a">
                <robot-outlined />
              </a-avatar>
            </div>
            <div class="msg-content-col">
              <!-- 工具调用卡片（tool_call） -->
              <template
                v-if="msg.message_type === 'tool_call' || msg.tool_calls?.length"
              >
                <a-card type="inner" size="small" class="tool-call-card">
                  <template #title>
                    <span class="tool-call-title">
                      <tool-outlined />
                      调用工具
                      <a-spin v-if="msg._toolLoading" size="small" style="margin-left: 8px" />
                    </span>
                  </template>
                  <div class="tool-call-list">
                    <div
                      v-for="(tc, i) in (msg.tool_calls || [makeToolCall(msg)])"
                      :key="i"
                      class="tool-call-item"
                      :class="{ loading: msg._toolLoading && !tc.result }"
                    >
                      <div class="tool-call-name">
                        <span class="tool-name-mono">{{ tc.name || tc.tool_name || 'unknown' }}</span>
                      </div>
                      <div class="tool-call-args">
                        <div class="args-label">入参：</div>
                        <SpoilerBlock
                          :content="formatJSON(tc.arguments || tc.args || tc.input || {})"
                          :limit="200"
                          label-code
                        />
                      </div>
                      <div v-if="tc.error" class="tool-call-result result-error">
                        <div class="result-label">错误：</div>
                        <SpoilerBlock :content="String(tc.error)" :limit="200" error />
                      </div>
                      <div v-else-if="tc.result !== undefined && tc.result !== null" class="tool-call-result">
                        <div class="result-label">结果：</div>
                        <SpoilerBlock :content="formatJSON(tc.result)" :limit="200" success />
                      </div>
                    </div>
                  </div>
                </a-card>
              </template>

              <!-- 工具结果卡片（tool_result） -->
              <template v-else-if="msg.message_type === 'tool_result'">
                <a-card
                  type="inner"
                  size="small"
                  class="tool-result-card"
                  :class="{ 'is-error': !!msg.error }"
                >
                  <template #title>
                    <span class="tool-result-title" :class="{ 'is-error': !!msg.error }">
                      <template v-if="msg.error">
                        <close-circle-outlined />
                        工具失败
                      </template>
                      <template v-else>
                        <check-circle-outlined />
                        工具结果
                      </template>
                      <span class="tool-name-inline">
                        · {{ msg.tool_name || msg.name || '' }}
                      </span>
                    </span>
                  </template>
                  <div class="tool-result-body">
                    <SpoilerBlock
                      :content="formatJSON(msg.result ?? msg.content ?? msg.output ?? '')"
                      :limit="200"
                      :error="!!msg.error"
                      :success="!msg.error"
                      label-code
                    />
                  </div>
                </a-card>
              </template>

              <!-- 普通气泡 -->
              <div v-else class="msg-bubble">
                <div
                  class="msg-content markdown-body"
                  v-if="msg.content || msg.role === 'assistant'"
                  v-html="renderMarkdown(msg.content || '_（无文本内容）_')"
                ></div>
                <div class="msg-footer">
                  <span v-if="msg.created_at" class="msg-time">{{ formatTime(msg.created_at) }}</span>
                  <template v-if="msg.role === 'assistant' && !msg.message_type && !msg.tool_calls">
                    <!-- 停止生成时不显示 -->
                    <a-button
                      type="text"
                      size="small"
                      class="msg-copy-btn"
                      @click="copyMessage(msg.content)"
                    >
                      <copy-outlined />
                      复制
                    </a-button>
                  </template>
                </div>
              </div>
            </div>
          </div>
          <!-- 流式加载中的指示器 -->
          <div v-if="streaming && streamingText === ''" class="msg-row assistant">
            <div class="msg-avatar">
              <a-avatar style="background-color: #52c41a">
                <robot-outlined />
              </a-avatar>
            </div>
            <div class="msg-content-col">
              <div class="msg-bubble">
                <div class="msg-typing">
                  <a-spin size="small" />
                  <span class="msg-typing-text">正在生成回复...</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 浮动操作条：最后一条是 assistant 时显示 -->
        <div
          v-if="!streaming && messages.length && lastAssistantMessage && !lastAssistantMessage.message_type"
          class="msg-action-bar"
        >
          <a-tooltip title="重新生成">
            <a-button
              type="primary"
              ghost
              size="small"
              :loading="regenerating"
              :disabled="regenerating"
              @click="handleRegenerate"
            >
              <reload-outlined />
              重新生成
            </a-button>
          </a-tooltip>
        </div>

        <!-- 输入区域 -->
        <div class="chat-input-area">
          <a-textarea
            v-model:value="inputText"
            :auto-size="{ minRows: 1, maxRows: 6 }"
            placeholder="输入消息，按 Enter 发送，Shift+Enter 换行"
            class="chat-input"
            :disabled="streaming"
            @keydown="handleKeydown"
          />
          <div class="chat-input-actions">
            <a-button
              v-if="!streaming"
              type="primary"
              :disabled="!inputText.trim()"
              :loading="false"
              @click="handleSend"
            >
              <send-outlined />
              发送
            </a-button>
            <a-button v-else danger @click="handleStop">
              <stop-outlined />
              停止生成
            </a-button>
          </div>
        </div>
      </template>

      <div v-else class="chat-placeholder">
        <a-empty description="请选择左侧会话，或点击「新建」开始对话">
          <a-button type="primary" @click="openNewConv">
            <plus-outlined />
            新建会话
          </a-button>
        </a-empty>
      </div>
    </div>

    <!-- 新建会话 Modal -->
    <a-modal
      v-model:open="newConvVisible"
      title="新建会话"
      :confirm-loading="newConvSubmitting"
      @ok="handleCreateConv"
      @cancel="newConvVisible = false"
    >
      <a-form layout="vertical">
        <a-form-item label="选择 Agent" required>
          <a-select
            v-model:value="newConvForm.agent_id"
            placeholder="请选择 Agent"
            :loading="agentLoading"
            show-search
            option-filter-prop="label"
          >
            <a-select-option
              v-for="a in agentOptions"
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
        </a-form-item>
        <a-form-item label="会话标题">
          <a-input v-model:value="newConvForm.title" placeholder="可选，留空将自动生成" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick, watch, computed, defineComponent, h } from 'vue'
import { message, Empty } from 'ant-design-vue'
import {
  PlusOutlined,
  MessageOutlined,
  RobotOutlined,
  UserOutlined,
  DeleteOutlined,
  CopyOutlined,
  SendOutlined,
  StopOutlined,
  ClearOutlined,
  ToolOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
  DownOutlined,
  UpOutlined,
} from '@ant-design/icons-vue'
import { marked } from 'marked'
import { conversationApi, chatApi, agentApi } from '@/api'

// 折叠显示组件（内联）
const SpoilerBlock = defineComponent({
  name: 'SpoilerBlock',
  props: {
    content: { type: [String, Object, Array, Number], default: '' },
    limit: { type: Number, default: 200 },
    error: Boolean,
    success: Boolean,
    labelCode: Boolean,
  },
  setup(props) {
    const expanded = ref(false)
    const text = computed(() => {
      const c = props.content
      if (c === null || c === undefined) return ''
      if (typeof c === 'string') return c
      try { return JSON.stringify(c, null, 2) } catch (e) { return String(c) }
    })
    const shouldCollapse = computed(() => String(text.value).length > props.limit)
    const displayText = computed(() => {
      const t = String(text.value)
      if (shouldCollapse.value && !expanded.value) {
        return t.slice(0, props.limit) + '...'
      }
      return t
    })
    return () => {
      const cls = [
        'spoiler-block',
        props.error ? 'is-error' : '',
        props.success ? 'is-success' : '',
        props.labelCode ? 'is-code' : '',
      ].filter(Boolean).join(' ')
      return h('div', { class: cls }, [
        h('pre', { class: 'spoiler-pre' }, displayText.value),
        shouldCollapse.value
          ? h(
              'a',
              {
                class: 'spoiler-toggle',
                onClick: () => { expanded.value = !expanded.value },
              },
              expanded.value ? [h(UpOutlined), ' 收起'] : [h(DownOutlined), ' 展开查看']
            )
          : null,
      ])
    }
  },
})

marked.setOptions({
  breaks: true,
  gfm: true,
})

// ============ 会话列表 ============
const conversations = ref([])
const currentConvId = ref(null)
const currentConv = ref(null)
const convLoading = ref(false)

// ============ 消息 ============
const messages = ref([])
const msgListRef = ref(null)

// ============ 输入与流式 ============
const inputText = ref('')
const streaming = ref(false)
const streamingText = ref('')
const regenerating = ref(false)
let abortController = null

// ============ 新建会话 ============
const newConvVisible = ref(false)
const newConvSubmitting = ref(false)
const agentOptions = ref([])
const agentLoading = ref(false)
const newConvForm = reactive({
  agent_id: undefined,
  title: '',
})

// 默认用户 ID
const DEFAULT_USER_ID = 'default_user'

// 最后一条 assistant 消息
const lastAssistantMessage = computed(() => {
  const list = messages.value
  for (let i = list.length - 1; i >= 0; i--) {
    if (list[i].role === 'assistant') return list[i]
  }
  return null
})

function makeToolCall(msg) {
  return {
    name: msg.tool_name || msg.name || '',
    arguments: msg.arguments || msg.args || msg.input || {},
    result: msg.result,
    error: msg.error,
  }
}

function formatJSON(v) {
  if (v === null || v === undefined) return ''
  if (typeof v === 'string') return v
  try { return JSON.stringify(v, null, 2) } catch (e) { return String(v) }
}

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

async function copyMessage(text) {
  try {
    await navigator.clipboard.writeText(text || '')
    message.success('已复制到剪贴板')
  } catch (e) {
    const ta = document.createElement('textarea')
    ta.value = text || ''
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand('copy')
      message.success('已复制到剪贴板')
    } catch (err) {
      message.error('复制失败')
    }
    document.body.removeChild(ta)
  }
}

// ============ 数据加载 ============
async function fetchConversations() {
  convLoading.value = true
  try {
    const res = await conversationApi.list({})
    conversations.value = Array.isArray(res)
      ? res
      : res?.items || res?.list || res?.data || []
  } catch (e) {
  } finally {
    convLoading.value = false
  }
}

async function fetchAgents() {
  agentLoading.value = true
  try {
    const res = await agentApi.list({ page: 1, page_size: 100 })
    agentOptions.value = Array.isArray(res)
      ? res
      : res?.items || res?.list || res?.data || []
  } catch (e) {
  } finally {
    agentLoading.value = false
  }
}

async function selectConversation(conv) {
  if (streaming.value) {
    message.warning('请先停止当前生成')
    return
  }
  currentConvId.value = conv.id
  currentConv.value = conv
  messages.value = []
  await loadMessages(conv.id)
}

async function loadMessages(convId) {
  try {
    const res = await conversationApi.messages(convId)
    const list = Array.isArray(res) ? res : res?.items || res?.list || res?.messages || res?.data || []
    messages.value = list.map((m) => ({
      ...m,
      role: m.role || (m.is_user ? 'user' : 'assistant'),
      content: m.content ?? m.text ?? '',
      message_type: m.message_type,
      tool_calls: m.tool_calls,
    }))
    await nextTick()
    scrollToBottom()
  } catch (e) {
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (msgListRef.value) {
      msgListRef.value.scrollTop = msgListRef.value.scrollHeight
    }
  })
}

// ============ 新建会话 ============
function openNewConv() {
  newConvForm.agent_id = undefined
  newConvForm.title = ''
  if (agentOptions.value.length === 0) fetchAgents()
  newConvVisible.value = true
}

async function handleCreateConv() {
  if (!newConvForm.agent_id) {
    message.warning('请选择 Agent')
    return
  }
  newConvSubmitting.value = true
  try {
    const title = newConvForm.title.trim() || `会话 ${new Date().toLocaleString('zh-CN')}`
    const res = await conversationApi.create({
      agent_id: newConvForm.agent_id,
      title,
      user_id: DEFAULT_USER_ID,
    })
    const conv = res?.id ? res : { id: res, agent_id: newConvForm.agent_id, title }
    newConvVisible.value = false
    await fetchConversations()
    await selectConversation(conv)
    message.success('会话已创建')
  } catch (e) {
  } finally {
    newConvSubmitting.value = false
  }
}

async function handleDeleteConv(conv) {
  try {
    await conversationApi.remove(conv.id)
    message.success('已删除')
    if (currentConvId.value === conv.id) {
      currentConvId.value = null
      currentConv.value = null
      messages.value = []
    }
    fetchConversations()
  } catch (e) {}
}

// ============ 发送消息（SSE 流式 + 工具事件） ============
function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    if (!streaming.value && inputText.value.trim()) {
      handleSend()
    }
  }
}

// 通用：开启流式，发送到 handlers，最后把 assistant 消息推到 messages
function startStream({ payload, isRegenerate = false }) {
  streaming.value = true
  streamingText.value = ''

  const assistantMsg = reactive({
    role: 'assistant',
    content: '',
    _temp_id: Date.now() + '_a_' + Math.random(),
    created_at: new Date().toISOString(),
  })
  messages.value.push(assistantMsg)

  const handlers = {
    onMessage: (data) => {
      // 工具调用事件
      if (data.type === 'tool_call' || data.event === 'tool_call') {
        appendToolCallMessage(data, assistantMsg)
        return
      }
      if (data.type === 'tool_result' || data.event === 'tool_result') {
        appendToolResultMessage(data)
        return
      }
      if (data.content) {
        assistantMsg.content += data.content
        streamingText.value = assistantMsg.content
        scrollToBottom()
      }
    },
    onDone: (data) => {
      streaming.value = false
      streamingText.value = ''
      regenerating.value = false
      if (data?.message_id) {
        assistantMsg.id = data.message_id
      }
      if (!assistantMsg.content && !assistantMsg.message_type && !assistantMsg.tool_calls) {
        assistantMsg.content = '_(未收到回复)_'
      }
      if (data?.fallback) {
        message.warning(data.fallback_message || '已自动降级为模型默认参数')
      }
      abortController = null
      scrollToBottom()
    },
    onError: (err) => {
      streaming.value = false
      streamingText.value = ''
      regenerating.value = false
      if (!assistantMsg.content) {
        assistantMsg.content = `⚠️ 发生错误：${err.message || '请求失败'}`
      }
      abortController = null
      scrollToBottom()
    },
  }

  abortController = isRegenerate
    ? chatApi.regenerate(payload, handlers)
    : chatApi.sendStream(payload, handlers)
}

function appendToolCallMessage(data, linkedAssistantMsg) {
  const toolCalls = data.tool_calls || [{
    name: data.name || data.tool_name,
    tool_name: data.tool_name || data.name,
    arguments: data.arguments || data.args || data.input || {},
  }]
  const msg = reactive({
    role: 'assistant',
    content: '',
    message_type: 'tool_call',
    tool_calls: toolCalls,
    _toolLoading: true,
    _linkedTempId: linkedAssistantMsg?._temp_id,
    _temp_id: Date.now() + '_tc_' + Math.random(),
    created_at: new Date().toISOString(),
  })
  messages.value.push(msg)
  scrollToBottom()
}

function appendToolResultMessage(data) {
  // 先尝试配对：如果前面 tool_call 正在 loading，更新其 loading 与 result
  const toolName = data.tool_name || data.name
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const m = messages.value[i]
    if (m.message_type === 'tool_call' && m._toolLoading) {
      const list = m.tool_calls || []
      for (const tc of list) {
        if (!tc.result && !tc.error && (!toolName || (tc.name || tc.tool_name) === toolName)) {
          if (data.error) tc.error = data.error
          else tc.result = data.result ?? data.content ?? data.output ?? ''
          m._toolLoading = false
          scrollToBottom()
          return
        }
      }
    }
  }
  const msg = reactive({
    role: 'assistant',
    content: '',
    message_type: 'tool_result',
    tool_name: data.tool_name || data.name,
    name: data.tool_name || data.name,
    result: data.result ?? data.content ?? data.output ?? '',
    error: data.error,
    _temp_id: Date.now() + '_tr_' + Math.random(),
    created_at: new Date().toISOString(),
  })
  messages.value.push(msg)
  scrollToBottom()
}

async function handleSend() {
  const content = inputText.value.trim()
  if (!content || streaming.value) return

  const userMsg = {
    role: 'user',
    content,
    _temp_id: Date.now() + '_u',
    created_at: new Date().toISOString(),
  }
  messages.value.push(userMsg)
  inputText.value = ''
  await nextTick()
  scrollToBottom()

  startStream({
    payload: {
      conversation_id: currentConvId.value,
      content,
    },
  })
}

async function handleRegenerate() {
  if (streaming.value || regenerating.value) return
  // 回退：删除最后一条 user + assistant 消息对的 assistant
  // 简化实现：如果最后一条是 assistant，直接触发 regenerate
  let lastUserIndex = -1
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (messages.value[i].role === 'user') { lastUserIndex = i; break }
  }
  // 移除最后一条 assistant 消息（及其附带的 tool_call/tool_result）
  if (lastUserIndex >= 0) {
    // 找到从 lastUserIndex+1 到末尾的 assistant 消息，截断
    messages.value = messages.value.slice(0, lastUserIndex + 1)
  }

  regenerating.value = true
  const userMsg = messages.value[lastUserIndex] || {}
  startStream({
    payload: {
      conversation_id: currentConvId.value,
      content: userMsg.content || '',
    },
    isRegenerate: true,
  })
}

async function handleStop() {
  try { await chatApi.stop(currentConvId.value) } catch (e) {}
  if (abortController) {
    abortController.abort()
    abortController = null
  }
  streaming.value = false
  streamingText.value = ''
  regenerating.value = false
  // 把 tool_call 的 loading 关掉
  for (const m of messages.value) {
    if (m.message_type === 'tool_call') m._toolLoading = false
  }
  message.info('已停止生成')
}

watch(currentConvId, () => {
  if (streaming.value && abortController) {
    abortController.abort()
    abortController = null
    streaming.value = false
  }
})

onMounted(() => {
  fetchConversations()
  fetchAgents()
})
</script>

<style scoped>
.page-chat {
  display: flex;
  height: 100%;
  background: #f0f2f5;
  overflow: hidden;
}

/* 左侧会话列表 */
.conv-sidebar {
  width: 280px;
  flex-shrink: 0;
  background: #fff;
  border-right: 1px solid #f0f0f0;
  display: flex;
  flex-direction: column;
}

.conv-sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #f0f0f0;
}

.conv-sidebar-title {
  font-weight: 600;
  font-size: 14px;
}

.conv-list {
  flex: 1;
  overflow: auto;
  padding: 8px;
}

.conv-empty {
  padding: 40px 16px;
}

.conv-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.2s;
  margin-bottom: 4px;
}

.conv-item:hover {
  background: #f5f5f5;
}

.conv-item.active {
  background: #e6f4ff;
}

.conv-item-main {
  flex: 1;
  min-width: 0;
}

.conv-item-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #1f1f1f;
  font-weight: 500;
}

.conv-item-icon {
  color: #8c8c8c;
  font-size: 12px;
}

.conv-item-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-item-meta {
  display: flex;
  gap: 8px;
  margin-top: 2px;
  font-size: 11px;
  color: #bfbfbf;
}

.conv-del-btn {
  opacity: 0;
  transition: opacity 0.2s;
}

.conv-item:hover .conv-del-btn {
  opacity: 1;
}

/* 右侧对话区 */
.chat-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: #fff;
  position: relative;
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid #f0f0f0;
  background: #fafafa;
}

.chat-header-title {
  font-weight: 600;
}

.msg-list {
  flex: 1;
  overflow: auto;
  padding: 20px 20px 60px;
  background: #f7f8fa;
}

.msg-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.msg-row {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  max-width: 900px;
  margin-left: auto;
  margin-right: auto;
}

.msg-row.user {
  flex-direction: row-reverse;
}

.msg-avatar {
  flex-shrink: 0;
}

.msg-content-col {
  max-width: 75%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.msg-row.user .msg-content-col { align-items: flex-end; }

.msg-bubble {
  padding: 12px 16px;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  width: 100%;
}

.msg-row.user .msg-bubble {
  background: #e6f4ff;
}

.msg-content {
  word-break: break-word;
}

.msg-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 6px;
  font-size: 11px;
  color: #bfbfbf;
}

.msg-copy-btn {
  font-size: 11px;
  color: #bfbfbf;
  padding: 0 4px;
  height: auto;
}

.msg-typing {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #8c8c8c;
  font-size: 13px;
}

/* 重新生成浮动条 */
.msg-action-bar {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  bottom: 120px;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(4px);
  padding: 6px 12px;
  border-radius: 20px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  z-index: 10;
}

/* 工具卡片 */
.tool-call-card,
.tool-result-card {
  margin: 0;
  width: 100%;
  border-radius: 8px;
  border: 1px solid #e0e7ff;
  background: #fff;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}

.tool-call-card :deep(.ant-card-head) {
  background: linear-gradient(180deg, #f0f5ff 0%, #ffffff 100%);
  border-bottom: 1px dashed #c7d2fe;
}

.tool-result-card :deep(.ant-card-head) {
  background: linear-gradient(180deg, #f6ffed 0%, #ffffff 100%);
  border-bottom: 1px dashed #b7eb8f;
}

.tool-result-card.is-error :deep(.ant-card-head) {
  background: linear-gradient(180deg, #fff2f0 0%, #ffffff 100%);
  border-bottom: 1px dashed #ffccc7;
}

.tool-call-title,
.tool-result-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 13px;
  color: #4338ca;
}

.tool-result-title { color: #389e0d; }
.tool-result-title.is-error { color: #cf1322; }

.tool-name-inline {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
  color: #595959;
  font-weight: 400;
}

.tool-call-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tool-call-item {
  padding: 8px 10px;
  background: #fafbff;
  border: 1px solid #eef0fc;
  border-radius: 6px;
}

.tool-call-item.loading {
  background: #fffbf0;
  border-color: #ffe58f;
}

.tool-call-name {
  margin-bottom: 6px;
}

.tool-name-mono {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
  font-weight: 600;
  color: #1677ff;
  background: #e6f4ff;
  padding: 2px 8px;
  border-radius: 4px;
  display: inline-block;
}

.tool-call-args,
.tool-call-result {
  margin-bottom: 4px;
}

.args-label,
.result-label {
  font-size: 11px;
  color: #8c8c8c;
  margin-bottom: 2px;
}

.tool-call-result.result-error .result-label { color: #cf1322; }

.tool-result-body {
  width: 100%;
}

/* Spoiler 折叠块（使用 :deep 渲染内联子组件 class） */
:deep(.spoiler-block) {
  border-radius: 4px;
  padding: 6px 8px;
}
:deep(.spoiler-block.is-code) {
  background: #f6f8fa;
  border: 1px solid #eaecef;
}
:deep(.spoiler-block.is-success) {
  background: #f6ffed;
  border: 1px solid #b7eb8f;
}
:deep(.spoiler-block.is-error) {
  background: #fff2f0;
  border: 1px solid #ffccc7;
}
:deep(.spoiler-pre) {
  margin: 0;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  color: #262626;
}
:deep(.spoiler-toggle) {
  display: inline-flex;
  align-items: center;
  margin-top: 4px;
  font-size: 12px;
  color: #1677ff;
  cursor: pointer;
  gap: 2px;
}
:deep(.spoiler-toggle:hover) { color: #0958d9; text-decoration: underline; }

/* 输入区 */
.chat-input-area {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  padding: 12px 20px 16px;
  background: #fff;
  border-top: 1px solid #f0f0f0;
}

.chat-input {
  flex: 1;
}

.chat-input-actions {
  flex-shrink: 0;
}

.chat-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
