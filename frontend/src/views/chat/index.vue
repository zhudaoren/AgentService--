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
            <div class="msg-bubble">
              <div class="msg-content markdown-body" v-html="renderMarkdown(msg.content)"></div>
              <div class="msg-footer">
                <span v-if="msg.created_at" class="msg-time">{{ formatTime(msg.created_at) }}</span>
                <a-button
                  type="text"
                  size="small"
                  class="msg-copy-btn"
                  @click="copyMessage(msg.content)"
                >
                  <copy-outlined />
                  复制
                </a-button>
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
            <div class="msg-bubble">
              <div class="msg-typing">
                <a-spin size="small" />
                <span class="msg-typing-text">正在生成回复...</span>
              </div>
            </div>
          </div>
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
import { ref, reactive, onMounted, nextTick, watch } from 'vue'
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
} from '@ant-design/icons-vue'
import { marked } from 'marked'
import { conversationApi, chatApi, agentApi } from '@/api'

// 配置 marked
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

// 默认用户 ID（实际项目应从登录态获取）
const DEFAULT_USER_ID = 'default_user'

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
    await navigator.clipboard.writeText(text)
    message.success('已复制到剪贴板')
  } catch (e) {
    // 兜底
    const ta = document.createElement('textarea')
    ta.value = text
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
    const res = await agentApi.list({ page: 1, page_size: 200 })
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
    // 规范化字段：role / content
    messages.value = list.map((m) => ({
      ...m,
      role: m.role || (m.is_user ? 'user' : 'assistant'),
      content: m.content ?? m.text ?? '',
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

// ============ 发送消息（SSE 流式） ============
function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    if (!streaming.value && inputText.value.trim()) {
      handleSend()
    }
  }
}

async function handleSend() {
  const content = inputText.value.trim()
  if (!content || streaming.value) return

  // 推入用户消息
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

  // 创建一个占位的 assistant 消息
  const assistantMsg = reactive({
    role: 'assistant',
    content: '',
    _temp_id: Date.now() + '_a',
    created_at: new Date().toISOString(),
  })
  messages.value.push(assistantMsg)

  streaming.value = true
  streamingText.value = ''

  abortController = chatApi.sendStream(
    { conversation_id: currentConvId.value, content },
    {
      onMessage: (data) => {
        if (data.content) {
          assistantMsg.content += data.content
          streamingText.value = assistantMsg.content
          scrollToBottom()
        }
      },
      onDone: (data) => {
        streaming.value = false
        streamingText.value = ''
        if (data?.message_id) {
          assistantMsg.id = data.message_id
        }
        // 若没有收到任何内容，给出提示
        if (!assistantMsg.content) {
          assistantMsg.content = '_(未收到回复)_'
        }
        abortController = null
      },
      onError: (err) => {
        streaming.value = false
        streamingText.value = ''
        if (!assistantMsg.content) {
          assistantMsg.content = `⚠️ 发生错误：${err.message || '请求失败'}`
        }
        abortController = null
      },
    }
  )
}

async function handleStop() {
  // 优先调用后端停止接口
  try {
    await chatApi.stop(currentConvId.value)
  } catch (e) {}
  // 本地中断流
  if (abortController) {
    abortController.abort()
    abortController = null
  }
  streaming.value = false
  streamingText.value = ''
  message.info('已停止生成')
}

watch(currentConvId, () => {
  // 切换会话时取消流式
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
  padding: 20px;
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

.msg-bubble {
  max-width: 75%;
  padding: 12px 16px;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
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
