<template>
  <div class="page-mcp">
    <div class="page-inner">
      <div class="page-header">
        <div>
          <h2 class="page-title">MCP 服务管理</h2>
          <p class="page-desc">
            管理MCP服务接入，支持SSE远程模式和STDIO本地子进程模式，一键连接发现工具
          </p>
        </div>
        <a-button type="primary" @click="openCreate">
          <plus-outlined />
          新建 MCP 服务
        </a-button>
      </div>

      <div class="filter-bar">
        <a-space :size="12" wrap>
          <a-input
            v-model:value="filters.keyword"
            placeholder="搜索名称/地址"
            style="width: 240px"
            allow-clear
          >
            <template #prefix><search-outlined /></template>
          </a-input>
          <a-select
            v-model:value="filters.mode"
            placeholder="模式"
            style="width: 140px"
            allow-clear
          >
            <a-select-option value="sse">SSE</a-select-option>
            <a-select-option value="stdio">STDIO</a-select-option>
          </a-select>
          <a-select
            v-model:value="filters.status"
            placeholder="状态"
            style="width: 140px"
            allow-clear
          >
            <a-select-option value="disconnected">未连接</a-select-option>
            <a-select-option value="connecting">连接中</a-select-option>
            <a-select-option value="connected">已连接</a-select-option>
            <a-select-option value="error">异常</a-select-option>
          </a-select>
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
        :data-source="services"
        :loading="loading"
        row-key="id"
        :pagination="pagination"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <a-tooltip :title="record.description">
              <span class="mcp-name">{{ record.name }}</span>
            </a-tooltip>
          </template>
          <template v-else-if="column.key === 'mode'">
            <a-tag :color="record.mode === 'sse' ? 'blue' : 'orange'">
              {{ record.mode === 'sse' ? 'SSE' : 'STDIO' }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'endpoint'">
            <span v-if="record.mode === 'sse'" class="text-mono text-endpoint">
              {{ record.sse_url || '-' }}
            </span>
            <span v-else class="text-mono text-endpoint">
              {{ record.stdio_config?.command || '-' }}
            </span>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">
              {{ statusText(record.status) }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'last_connected_at'">
            <span v-if="record.last_connected_at">{{ formatTime(record.last_connected_at) }}</span>
            <span v-else class="text-muted">未连接</span>
          </template>
          <template v-else-if="column.key === 'tools'">
            <span v-if="record.tool_count || record.tools_count" class="tools-count">
              <tool-outlined />
              {{ record.tool_count || record.tools_count || 0 }} 个工具
            </span>
            <span v-else class="text-muted">-</span>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-space :size="4" wrap>
              <a-button
                v-if="record.status !== 'connected' && record.status !== 'connecting'"
                type="link"
                size="small"
                :loading="connectingId === record.id"
                @click="handleConnect(record)"
              >
                <link-outlined />
                连接
              </a-button>
              <a-button
                v-else
                type="link"
                size="small"
                :loading="disconnectingId === record.id"
                @click="handleDisconnect(record)"
              >
                <scissor-outlined />
                断开
              </a-button>
              <a-button
                type="link"
                size="small"
                :loading="discoveringId === record.id"
                :disabled="record.status !== 'connected'"
                @click="handleDiscover(record)"
              >
                <thunderbolt-outlined />
                发现工具
              </a-button>
              <a-button type="link" size="small" @click="openToolsDrawer(record)">
                <database-outlined />
                查看工具
              </a-button>
              <a-divider type="vertical" />
              <a-button type="link" size="small" @click="openEdit(record)">编辑</a-button>
              <a-popconfirm title="确定删除该 MCP 服务？" @confirm="handleDelete(record)">
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
      :title="isEdit ? '编辑 MCP 服务' : '新建 MCP 服务'"
      :confirm-loading="submitting"
      width="640px"
      @ok="handleSubmit"
      @cancel="modalVisible = false"
    >
      <a-form ref="formRef" :model="form" :rules="rules" layout="vertical">
        <a-form-item label="服务名称" name="name">
          <a-input v-model:value="form.name" placeholder="例如：文件系统 MCP" />
        </a-form-item>
        <a-form-item label="描述" name="description">
          <a-input v-model:value="form.description" placeholder="选填，描述该 MCP 服务的用途" />
        </a-form-item>
        <a-form-item label="连接模式" name="mode">
          <a-radio-group v-model:value="form.mode">
            <a-radio-button value="sse">
              <global-outlined />
              SSE 远程
            </a-radio-button>
            <a-radio-button value="stdio">
              <code-outlined />
              STDIO 本地子进程
            </a-radio-button>
          </a-radio-group>
        </a-form-item>

        <!-- SSE 模式配置 -->
        <template v-if="form.mode === 'sse'">
          <a-divider orientation="left">SSE 连接配置</a-divider>
          <a-form-item label="SSE URL" name="sse_url">
            <a-input
              v-model:value="form.sse_url"
              placeholder="https://example.com/mcp"
              :prefix="$createElement ? '' : ''"
            >
              <template #prefix>
                <link-outlined />
              </template>
            </a-input>
          </a-form-item>
        </template>

        <!-- STDIO 模式配置 -->
        <template v-else>
          <a-divider orientation="left">STDIO 子进程配置</a-divider>
          <a-form-item label="启动命令" name="command">
            <a-input
              v-model:value="stdioCommand"
              placeholder="python /path/mcp_server.py"
            >
              <template #prefix>
                <code-outlined />
              </template>
            </a-input>
          </a-form-item>
          <a-form-item label="启动参数 args" name="args">
            <a-textarea
              v-model:value="stdioArgsText"
              :rows="3"
              placeholder="每行一个参数，例如：&#10;--port&#10;8080&#10;--verbose"
            />
            <div class="form-hint">每行一个参数，提交后将转为 JSON 数组</div>
          </a-form-item>
          <a-form-item label="环境变量 env" name="env">
            <a-textarea
              v-model:value="stdioEnvText"
              :rows="3"
              placeholder="每行 KEY=VALUE，例如：&#10;API_KEY=sk-xxx&#10;DEBUG=true"
            />
            <div class="form-hint">每行 KEY=VALUE，提交后将转为 JSON 对象</div>
          </a-form-item>
        </template>
      </a-form>
    </a-modal>

    <!-- 工具列表 Drawer -->
    <a-drawer
      v-model:open="toolsDrawerVisible"
      :title="`${currentMCP?.name || ''} - 工具列表`"
      width="720px"
      :mask-closable="false"
    >
      <a-table
        :columns="toolsColumns"
        :data-source="toolsList"
        :loading="toolsLoading"
        row-key="name"
        :pagination="toolsPagination"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <span class="tool-name">{{ record.name }}</span>
          </template>
          <template v-else-if="column.key === 'description'">
            <a-tooltip :title="record.description">
              <span class="tool-desc">{{ truncate(record.description, 80) }}</span>
            </a-tooltip>
          </template>
          <template v-else-if="column.key === 'enabled'">
            <a-switch
              :checked="record.enabled !== false"
              :loading="togglingTool === record.name"
              @change="(checked) => handleToggleTool(record, checked)"
            />
          </template>
          <template v-else-if="column.key === 'usage_count'">
            <span class="text-mono">{{ record.usage_count || 0 }}</span>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-button type="link" size="small" @click="openTestTool(record)">
              <play-circle-outlined />
              测试
            </a-button>
          </template>
        </template>
      </a-table>
    </a-drawer>

    <!-- 工具测试 Modal -->
    <a-modal
      v-model:open="testToolVisible"
      :title="`测试工具：${testingTool?.name || ''}`"
      :confirm-loading="testToolSubmitting"
      width="640px"
      ok-text="运行"
      @ok="handleRunTestTool"
      @cancel="testToolVisible = false"
    >
      <div class="test-tool-section">
        <div class="section-title">
          <file-text-outlined />
          入参（JSON）
        </div>
        <a-textarea
          v-model:value="testToolInput"
          :rows="8"
          placeholder='{&#10;  "param1": "value1",&#10;  "param2": 123&#10;}'
          class="json-textarea"
        />
      </div>
      <div v-if="testToolResult !== null" class="test-tool-section">
        <div class="section-title" :class="{ 'success': !testToolResult?.error, 'error': testToolResult?.error }">
          <template v-if="testToolResult?.error">
            <close-circle-outlined />
            执行失败
          </template>
          <template v-else>
            <check-circle-outlined />
            执行结果
          </template>
        </div>
        <div class="result-wrapper" :class="{ 'result-error': testToolResult?.error }">
          <pre class="result-pre">{{ formatResult(testToolResult) }}</pre>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  PlusOutlined,
  SearchOutlined,
  ReloadOutlined,
  ToolOutlined,
  LinkOutlined,
  ScissorOutlined,
  ThunderboltOutlined,
  DatabaseOutlined,
  GlobalOutlined,
  CodeOutlined,
  PlayCircleOutlined,
  FileTextOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons-vue'
import { mcpApi, toolApi } from '@/api'

const services = ref([])
const loading = ref(false)
const submitting = ref(false)
const modalVisible = ref(false)
const isEdit = ref(false)
const formRef = ref()
const connectingId = ref(null)
const disconnectingId = ref(null)
const discoveringId = ref(null)

const filters = reactive({
  keyword: '',
  mode: undefined,
  status: undefined,
})

const pagination = reactive({
  current: 1,
  pageSize: 20,
  total: 0,
  showSizeChanger: true,
  showTotal: (t) => `共 ${t} 条`,
})

const columns = [
  { title: '名称', dataIndex: 'name', key: 'name', width: 180, ellipsis: true },
  { title: '模式', key: 'mode', width: 90 },
  { title: '地址 / 命令', key: 'endpoint', ellipsis: true },
  { title: '状态', key: 'status', width: 110 },
  { title: '最后连接', dataIndex: 'last_connected_at', key: 'last_connected_at', width: 170 },
  { title: '工具', key: 'tools', width: 110 },
  { title: '操作', key: 'action', width: 420, fixed: 'right' },
]

const defaultForm = () => ({
  id: undefined,
  name: '',
  description: '',
  mode: 'sse',
  sse_url: '',
  stdio_config: {
    command: '',
    args: [],
    env: {},
  },
})

const form = reactive(defaultForm())

const stdioCommand = ref('')
const stdioArgsText = ref('')
const stdioEnvText = ref('')

const rules = {
  name: [{ required: true, message: '请输入服务名称' }],
  mode: [{ required: true, message: '请选择连接模式' }],
  sse_url: [
    {
      validator: (_, value) => {
        if (form.mode === 'sse' && !value) return Promise.reject('请输入 SSE URL')
        return Promise.resolve()
      },
    },
  ],
  command: [
    {
      validator: () => {
        if (form.mode === 'stdio' && !stdioCommand.value) return Promise.reject('请输入启动命令')
        return Promise.resolve()
      },
    },
  ],
}

function statusText(s) {
  const map = {
    disconnected: '未连接',
    connecting: '连接中',
    connected: '已连接',
    error: '异常',
  }
  return map[s] || s || '未知'
}

function statusColor(s) {
  const map = {
    disconnected: 'default',
    connecting: 'gold',
    connected: 'green',
    error: 'red',
  }
  return map[s] || 'default'
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

function truncate(s, len) {
  if (!s) return ''
  const str = String(s)
  return str.length > len ? str.slice(0, len) + '...' : str
}

async function fetchList() {
  loading.value = true
  try {
    const params = {
      page: pagination.current,
      page_size: pagination.pageSize,
    }
    if (filters.keyword) params.keyword = filters.keyword
    if (filters.mode) params.mode = filters.mode
    if (filters.status) params.status = filters.status
    const res = await mcpApi.list(params)
    if (Array.isArray(res)) {
      services.value = res
      pagination.total = res.length
    } else if (res?.items) {
      services.value = res.items
      pagination.total = res.total ?? res.items.length
    } else if (res?.list) {
      services.value = res.list
      pagination.total = res.total ?? res.list.length
    } else {
      services.value = res?.data || []
      pagination.total = res?.total || services.value.length
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
  filters.mode = undefined
  filters.status = undefined
  pagination.current = 1
  fetchList()
}

function openCreate() {
  isEdit.value = false
  Object.assign(form, defaultForm())
  stdioCommand.value = ''
  stdioArgsText.value = ''
  stdioEnvText.value = ''
  modalVisible.value = true
}

function openEdit(record) {
  isEdit.value = true
  Object.assign(form, {
    ...defaultForm(),
    ...record,
    stdio_config: record.stdio_config || { command: '', args: [], env: {} },
  })
  stdioCommand.value = form.stdio_config?.command || ''
  stdioArgsText.value = (form.stdio_config?.args || []).join('\n')
  stdioEnvText.value = Object.entries(form.stdio_config?.env || {})
    .map(([k, v]) => `${k}=${v}`)
    .join('\n')
  modalVisible.value = true
}

function buildStdioConfig() {
  const args = stdioArgsText.value
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
  const env = {}
  stdioEnvText.value
    .split('\n')
    .map((s) => s.trim())
    .filter((l) => l.includes('='))
    .forEach((line) => {
      const idx = line.indexOf('=')
      const k = line.slice(0, idx).trim()
      const v = line.slice(idx + 1).trim()
      if (k) env[k] = v
    })
  return {
    command: stdioCommand.value,
    args,
    env,
  }
}

async function handleSubmit() {
  try {
    await formRef.value.validate()
    submitting.value = true
    const payload = {
      name: form.name,
      description: form.description,
      mode: form.mode,
    }
    if (form.mode === 'sse') {
      payload.sse_url = form.sse_url
    } else {
      payload.stdio_config = buildStdioConfig()
    }
    if (isEdit.value) {
      await mcpApi.update(form.id, payload)
      message.success('更新成功')
    } else {
      await mcpApi.create(payload)
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
    await mcpApi.remove(record.id)
    message.success('删除成功')
    fetchList()
  } catch (e) {}
}

async function handleConnect(record) {
  connectingId.value = record.id
  try {
    await mcpApi.connect(record.id)
    message.success(`已发起连接 [${record.name}]`)
    await fetchList()
    setTimeout(async () => {
      try {
        discoveringId.value = record.id
        await mcpApi.discover(record.id)
        message.success(`发现工具完成 [${record.name}]`)
      } catch (e) {
      } finally {
        discoveringId.value = null
      }
      fetchList()
    }, 800)
  } catch (e) {
  } finally {
    connectingId.value = null
  }
}

async function handleDisconnect(record) {
  disconnectingId.value = record.id
  try {
    await mcpApi.disconnect(record.id)
    message.success(`已断开 [${record.name}]`)
    fetchList()
  } catch (e) {
  } finally {
    disconnectingId.value = null
  }
}

async function handleDiscover(record) {
  discoveringId.value = record.id
  try {
    await mcpApi.discover(record.id)
    message.success('发现工具完成')
    fetchList()
    if (toolsDrawerVisible.value && currentMCP.value?.id === record.id) {
      fetchToolsList()
    }
  } catch (e) {
  } finally {
    discoveringId.value = null
  }
}

// ============ 工具列表抽屉 ============
const toolsDrawerVisible = ref(false)
const currentMCP = ref(null)
const toolsList = ref([])
const toolsLoading = ref(false)
const togglingTool = ref(null)
const toolsPagination = reactive({
  current: 1,
  pageSize: 50,
  total: 0,
  showSizeChanger: true,
  showTotal: (t) => `共 ${t} 个工具`,
})

const toolsColumns = [
  { title: '工具名称', key: 'name', width: 180 },
  { title: '描述', key: 'description', ellipsis: true },
  { title: '启用', key: 'enabled', width: 80 },
  { title: '调用次数', key: 'usage_count', width: 90 },
  { title: '操作', key: 'action', width: 80 },
]

async function openToolsDrawer(record) {
  currentMCP.value = record
  toolsDrawerVisible.value = true
  toolsList.value = []
  fetchToolsList()
}

async function fetchToolsList() {
  if (!currentMCP.value) return
  toolsLoading.value = true
  try {
    const res = await mcpApi.listTools(currentMCP.value.id, {
      page: toolsPagination.current,
      page_size: toolsPagination.pageSize,
    })
    if (Array.isArray(res)) {
      toolsList.value = res
      toolsPagination.total = res.length
    } else if (res?.items) {
      toolsList.value = res.items
      toolsPagination.total = res.total ?? res.items.length
    } else if (res?.list) {
      toolsList.value = res.list
      toolsPagination.total = res.total ?? res.list.length
    } else {
      toolsList.value = res?.data || res?.tools || []
      toolsPagination.total = res?.total || toolsList.value.length
    }
  } catch (e) {
  } finally {
    toolsLoading.value = false
  }
}

async function handleToggleTool(tool, enabled) {
  if (!currentMCP.value) return
  togglingTool.value = tool.name
  try {
    await mcpApi.toggleTool(currentMCP.value.id, tool.name, enabled)
    message.success(enabled ? '已启用' : '已禁用')
    tool.enabled = enabled
  } catch (e) {
    tool.enabled = !enabled
  } finally {
    togglingTool.value = null
  }
}

// ============ 工具测试 Modal ============
const testToolVisible = ref(false)
const testingTool = ref(null)
const testToolInput = ref('{}')
const testToolResult = ref(null)
const testToolSubmitting = ref(false)

function openTestTool(tool) {
  testingTool.value = tool
  testToolInput.value = '{}'
  testToolResult.value = null
  testToolVisible.value = true
}

function formatResult(r) {
  if (r === null || r === undefined) return ''
  try {
    if (typeof r === 'string') return r
    return JSON.stringify(r, null, 2)
  } catch (e) {
    return String(r)
  }
}

async function handleRunTestTool() {
  if (!testingTool.value || !currentMCP.value) return
  let argsObj = {}
  try {
    const trimmed = (testToolInput.value || '').trim()
    if (trimmed) {
      argsObj = JSON.parse(trimmed)
    }
  } catch (e) {
    message.error('入参 JSON 格式错误')
    return
  }
  testToolSubmitting.value = true
  testToolResult.value = null
  try {
    const res = await toolApi.call({
      mcp_service_id: currentMCP.value.id,
      tool_name: testingTool.value.name,
      arguments: argsObj,
    })
    testToolResult.value = { success: true, ...(res || {}) }
  } catch (e) {
    testToolResult.value = { error: true, message: e.message || '调用失败' }
  } finally {
    testToolSubmitting.value = false
  }
}

onMounted(() => {
  fetchList()
})
</script>

<style scoped>
.page-mcp {
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

.mcp-name {
  font-weight: 500;
}

.tools-count {
  color: #595959;
  font-size: 13px;
}

.text-muted {
  color: #bfbfbf;
}

.text-mono {
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.text-endpoint {
  font-size: 12px;
  color: #595959;
}

.form-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #8c8c8c;
}

.tool-name {
  font-weight: 500;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 13px;
}

.tool-desc {
  font-size: 12px;
  color: #595959;
}

.test-tool-section {
  margin-bottom: 16px;
}

.section-title {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 8px;
  color: #262626;
  display: flex;
  align-items: center;
  gap: 6px;
}

.section-title.success {
  color: #52c41a;
}

.section-title.error {
  color: #ff4d4f;
}

.json-textarea {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
}

.result-wrapper {
  background: #f6ffed;
  border: 1px solid #b7eb8f;
  border-radius: 4px;
  padding: 12px;
  max-height: 300px;
  overflow: auto;
}

.result-wrapper.result-error {
  background: #fff2f0;
  border-color: #ffccc7;
}

.result-pre {
  margin: 0;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
