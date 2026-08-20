<template>
  <div class="page-mcp">
    <div class="page-inner">
      <div class="page-header">
        <div>
          <h2 class="page-title">MCP 服务管理</h2>
          <p class="page-desc">
            管理MCP服务接入，支持Streamable HTTP、SSE(Legacy)远程模式和STDIO本地子进程模式，一键连接发现工具
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
            <a-select-option value="streamable_http">Streamable HTTP</a-select-option>
            <a-select-option value="sse">SSE (Legacy)</a-select-option>
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
        :scroll="{ x: 1160 }"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <a-tooltip :title="record.description">
              <span class="mcp-name">{{ record.name }}</span>
            </a-tooltip>
            <a-tag v-if="record.is_builtin" color="blue" style="margin-left: 6px">🛡️ 官方内置</a-tag>
          </template>
          <template v-else-if="column.key === 'mode'">
            <a-tag :color="modeColor(record.mode)">
              {{ modeText(record.mode) }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'endpoint'">
            <span v-if="record.mode === 'sse' || record.mode === 'streamable_http'" class="text-mono text-endpoint">
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
              <a-tooltip v-if="record.is_builtin" title="官方内置MCP服务不可删除">
                <a-popconfirm title="确定删除该 MCP 服务？" @confirm="handleDelete(record)">
                  <a-button type="link" size="small" danger :disabled="record.is_builtin">删除</a-button>
                </a-popconfirm>
              </a-tooltip>
              <a-popconfirm v-else title="确定删除该 MCP 服务？" @confirm="handleDelete(record)">
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
        <a-form-item :label="currentIsBuiltin ? '服务名称（官方内置，不可修改）' : '服务名称'" name="name">
          <a-input v-model:value="form.name" placeholder="例如：文件系统 MCP" :disabled="currentIsBuiltin" />
        </a-form-item>
        <a-form-item label="描述" name="description">
          <div class="description-wrapper">
            <a-textarea
              v-model:value="form.description"
              placeholder="选填，描述该 MCP 服务的用途（例如：提供文件读写、目录管理等能力的本地文件系统服务）"
              :auto-size="{ minRows: 3, maxRows: 6 }"
              show-count
              :maxlength="500"
            />
            <a-button
              type="link"
              size="small"
              class="polish-btn"
              :loading="polishingDesc"
              :disabled="!form.description || !form.description.trim()"
              @click="handlePolishDescription"
            >
              <thunderbolt-outlined />
              AI 润色
            </a-button>
          </div>
        </a-form-item>
        <a-form-item :label="currentIsBuiltin ? '连接模式（官方内置，不可修改）' : '连接模式'" name="mode">
          <a-radio-group v-model:value="form.mode" :disabled="currentIsBuiltin">
            <a-radio-button value="streamable_http">
              <global-outlined />
              Streamable HTTP
            </a-radio-button>
            <a-tooltip title="该方式被标记为 Legacy，将在12个月后废弃，建议迁移至 Streamable HTTP">
              <a-radio-button value="sse">
                <global-outlined />
                SSE (Legacy)
              </a-radio-button>
            </a-tooltip>
            <a-radio-button value="stdio">
              <code-outlined />
              STDIO 本地子进程
            </a-radio-button>
          </a-radio-group>
        </a-form-item>

        <!-- SSE / Streamable HTTP 模式配置 -->
        <template v-if="form.mode === 'sse' || form.mode === 'streamable_http'">
          <a-divider orientation="left">{{ form.mode === 'sse' ? 'SSE 连接配置 (Legacy)' : 'Streamable HTTP 连接配置' }}</a-divider>
          <a-form-item :label="(form.mode === 'sse' ? 'SSE URL' : 'HTTP URL') + (currentIsBuiltin ? '（官方内置，不可修改）' : '')" name="sse_url">
            <a-input
              v-model:value="form.sse_url"
              placeholder="https://example.com/mcp"
              :disabled="currentIsBuiltin"
            >
              <template #prefix>
                <link-outlined />
              </template>
            </a-input>
          </a-form-item>
          <a-form-item label="认证类型" name="auth_type">
            <a-radio-group v-model:value="form.auth_type">
              <a-radio-button value="none">无认证</a-radio-button>
              <a-radio-button value="bearer">Bearer Token</a-radio-button>
              <a-radio-button value="basic">Basic Auth</a-radio-button>
              <a-radio-button value="custom">自定义 Headers</a-radio-button>
              <a-radio-button value="oauth">OAuth 2.1</a-radio-button>
            </a-radio-group>
          </a-form-item>
          <!-- Bearer Token -->
          <a-form-item v-if="form.auth_type === 'bearer'" label="API Key / Token" name="api_key">
            <a-input-password
              v-model:value="apiKey"
              placeholder="输入 Bearer Token (将自动转为 Authorization: Bearer 头)"
            >
              <template #prefix>
                <lock-outlined />
              </template>
            </a-input-password>
            <div class="form-hint">填写后将自动添加 Authorization: Bearer {token} 请求头</div>
          </a-form-item>
          <!-- Basic Auth -->
          <template v-if="form.auth_type === 'basic'">
            <a-form-item label="用户名" name="basic_user">
              <a-input v-model:value="basicUser" placeholder="HTTP Basic Auth 用户名" />
            </a-form-item>
            <a-form-item label="密码" name="basic_pass">
              <a-input-password v-model:value="basicPass" placeholder="HTTP Basic Auth 密码" />
            </a-form-item>
            <div class="form-hint">将自动生成 Authorization: Basic base64(user:pass) 请求头</div>
          </template>
          <!-- 自定义 Headers -->
          <a-form-item v-if="form.auth_type === 'custom'" label="自定义 Headers" name="headers_text">
            <a-textarea
              v-model:value="headersText"
              :rows="3"
              placeholder="每行一个 Header，格式：Key: Value&#10;例如：&#10;X-API-Key: sk-xxx&#10;Authorization: Bearer token"
            />
            <div class="form-hint">每行一个 Header，格式为 Key: Value，提交后将转为 HTTP 请求头</div>
          </a-form-item>
          <!-- OAuth 2.1 + PKCE -->
          <template v-if="form.auth_type === 'oauth'">
            <a-alert
              message="OAuth 2.1 + PKCE"
              description="MCP 规范的 OAuth 授权流程: 自动发现授权服务器 → 动态客户端注册 → PKCE 授权码交换 → 令牌自动刷新。需先保存 MCP 服务配置后再发起授权。"
              type="info"
              show-icon
              style="margin-bottom: 16px"
            />
            <a-form-item label="Client ID" name="oauth_client_id">
              <a-input
                v-model:value="oauthClientId"
                placeholder="手动输入 Client ID (留空则自动动态注册)"
              />
            </a-form-item>
            <a-form-item label="Client Secret" name="oauth_client_secret">
              <a-input-password
                v-model:value="oauthClientSecret"
                placeholder="可选, 公共客户端 (PKCE) 无需填写"
              />
            </a-form-item>
            <a-form-item label="Scopes" name="oauth_scopes">
              <a-input
                v-model:value="oauthScopesText"
                placeholder="空格分隔的 scope 列表, 如: read write"
              />
              <div class="form-hint">如不填写, 将使用授权服务器返回的默认 scopes</div>
            </a-form-item>
            <!-- OAuth 状态和操作 -->
            <template v-if="isEdit && form.id">
              <a-divider orientation="left">OAuth 授权状态</a-divider>
              <a-form-item label="授权状态">
                <a-tag :color="oauthStatusColor">{{ oauthStatusText }}</a-tag>
              </a-form-item>
              <a-form-item v-if="oauthStatus === 'authorized'" label="令牌加密">
                <a-tag :color="oauthEncrypted ? 'green' : 'orange'">
                  <lock-outlined v-if="oauthEncrypted" />
                  <unlock-outlined v-else />
                  {{ oauthEncrypted ? '已加密存储' : '未加密(历史数据)' }}
                </a-tag>
              </a-form-item>
              <a-form-item v-if="oauthStatus === 'authorized'" label="受众验证">
                <a-tag :color="oauthAudienceValid ? 'green' : 'red'">
                  <safety-outlined v-if="oauthAudienceValid" />
                  <warning-outlined v-else />
                  {{ oauthAudienceValid ? '通过' : '不匹配' }}
                </a-tag>
                <a-tooltip v-if="!oauthAudienceValid && oauthAudienceWarning" :title="oauthAudienceWarning">
                  <info-circle-outlined style="margin-left: 6px; color: #ff4d4f" />
                </a-tooltip>
              </a-form-item>
              <a-alert
                v-if="oauthStatus === 'authorized' && !oauthAudienceValid && oauthAudienceWarning"
                :message="oauthAudienceWarning"
                type="warning"
                show-icon
                style="margin-bottom: 12px"
              />
              <a-space>
                <a-button type="primary" :loading="oauthAuthorizing" @click="handleOAuthAuthorize">
                  <thunderbolt-outlined /> 发起授权
                </a-button>
                <a-button :loading="oauthRefreshing" @click="handleOAuthRefresh" v-if="oauthStatus === 'authorized'">
                  刷新令牌
                </a-button>
                <a-button danger @click="handleOAuthRevoke" v-if="oauthStatus !== 'not_configured'">
                  撤销授权
                </a-button>
                <a-button @click="handleOAuthDiscover">发现授权服务器</a-button>
              </a-space>
            </template>
          </template>
        </template>

        <!-- STDIO 模式配置 -->
        <template v-else>
          <a-divider orientation="left">STDIO 子进程配置</a-divider>
          <a-form-item :label="currentIsBuiltin ? '启动命令（官方内置，不可修改）' : '启动命令'" name="command">
            <a-input
              v-model:value="stdioCommand"
              placeholder="python /path/mcp_server.py"
              :disabled="currentIsBuiltin"
            >
              <template #prefix>
                <code-outlined />
              </template>
            </a-input>
          </a-form-item>
          <a-form-item :label="currentIsBuiltin ? '启动参数 args（官方内置，不可修改）' : '启动参数 args'" name="args">
            <a-textarea
              v-model:value="stdioArgsText"
              :rows="3"
              placeholder="每行一个参数，例如：&#10;--port&#10;8080&#10;--verbose"
              :disabled="currentIsBuiltin"
            />
            <div class="form-hint">每行一个参数，提交后将转为 JSON 数组</div>
          </a-form-item>
          <a-form-item :label="currentIsBuiltin ? '环境变量 env（官方内置，不可修改）' : '环境变量 env'" name="env">
            <a-textarea
              v-model:value="stdioEnvText"
              :rows="3"
              placeholder="每行 KEY=VALUE，例如：&#10;API_KEY=sk-xxx&#10;DEBUG=true"
              :disabled="currentIsBuiltin"
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

    <!-- AI 润色描述对比弹窗 -->
    <a-modal
      v-model:open="polishDescVisible"
      title="AI 润色 MCP 服务描述"
      :footer="null"
      width="720px"
      @cancel="polishDescVisible = false"
    >
      <div class="polish-compare">
        <div class="polish-panel">
          <div class="polish-panel-header">
            <span class="polish-panel-title">原始描述</span>
          </div>
          <a-textarea
            :value="polishDescOriginal"
            :rows="8"
            readonly
            class="polish-textarea-readonly"
          />
        </div>
        <div class="polish-panel">
          <div class="polish-panel-header">
            <span class="polish-panel-title">润色结果</span>
            <a-button
              type="link"
              size="small"
              :loading="polishingDesc"
              :disabled="!polishDescResult"
              @click="handleRepolishDescription"
            >
              <thunderbolt-outlined />
              再次 AI 润色
            </a-button>
          </div>
          <a-textarea
            v-model:value="polishDescResult"
            :rows="8"
            placeholder="润色后的描述将显示在这里，您可以直接编辑修改"
          />
        </div>
      </div>
      <div class="polish-footer">
        <a-button
          type="primary"
          :disabled="!polishDescResult || !polishDescResult.trim()"
          @click="applyPolishedDescription"
        >
          确认使用
        </a-button>
        <a-button @click="polishDescVisible = false">取消</a-button>
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
  LockOutlined,
  UnlockOutlined,
  SafetyOutlined,
  WarningOutlined,
  InfoCircleOutlined,
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
import { mcpApi, toolApi, agentApi } from '@/api'

const services = ref([])
const loading = ref(false)
const submitting = ref(false)
const modalVisible = ref(false)
const isEdit = ref(false)
const currentIsBuiltin = ref(false)
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
  { title: '名称', dataIndex: 'name', key: 'name', width: 160, ellipsis: true },
  { title: '模式', key: 'mode', width: 130, ellipsis: true },
  { title: '地址 / 命令', key: 'endpoint', width: 280, ellipsis: true },
  { title: '状态', key: 'status', width: 90 },
  { title: '最后连接', dataIndex: 'last_connected_at', key: 'last_connected_at', width: 160 },
  { title: '工具', key: 'tools', width: 100 },
  { title: '操作', key: 'action', width: 340, fixed: 'right' },
]

const defaultForm = () => ({
  id: undefined,
  name: '',
  description: '',
  mode: 'streamable_http',
  sse_url: '',
  auth_type: 'none',
  headers: {},
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
const apiKey = ref('')
const basicUser = ref('')
const basicPass = ref('')
const headersText = ref('')
// OAuth 相关
const oauthClientId = ref('')
const oauthClientSecret = ref('')
const oauthScopesText = ref('')
const oauthStatus = ref('not_configured')
const oauthAuthorizing = ref(false)
const oauthRefreshing = ref(false)
const oauthCallbackHandler = ref(null)
// 令牌加密 + 受众验证状态
const oauthEncrypted = ref(false)
const oauthAudienceValid = ref(true)
const oauthAudienceWarning = ref('')
// AI 润色描述
const polishingDesc = ref(false)
const polishDescVisible = ref(false)
const polishDescOriginal = ref('')
const polishDescResult = ref('')

const rules = {
  name: [{ required: true, message: '请输入服务名称' }],
  mode: [{ required: true, message: '请选择连接模式' }],
  sse_url: [
    {
      validator: (_, value) => {
        if ((form.mode === 'sse' || form.mode === 'streamable_http') && !value) {
          return Promise.reject(form.mode === 'sse' ? '请输入 SSE URL' : '请输入 HTTP URL')
        }
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

function modeText(m) {
  const map = {
    streamable_http: 'Streamable HTTP',
    sse: 'SSE (Legacy)',
    stdio: 'STDIO',
  }
  return map[m] || m || '未知'
}

function modeColor(m) {
  const map = {
    streamable_http: 'green',
    sse: 'blue',
    stdio: 'orange',
  }
  return map[m] || 'default'
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

// ============ AI 润色描述 ============
async function handlePolishDescription() {
  if (!form.description || !form.description.trim()) return
  polishingDesc.value = true
  try {
    const res = await agentApi.polishMcpDescription(form.description, form.mode)
    if (res?.polished_description) {
      polishDescOriginal.value = form.description
      polishDescResult.value = res.polished_description
      polishDescVisible.value = true
      if (res.fallback) {
        message.warning('润色完成（已自动降级为默认配置）')
      } else {
        message.success('AI 润色完成')
      }
    } else {
      message.warning('润色结果为空，请重试')
    }
  } catch (e) {
    message.error('AI 润色失败，请稍后重试')
  } finally {
    polishingDesc.value = false
  }
}

function applyPolishedDescription() {
  if (polishDescResult.value) {
    form.description = polishDescResult.value
    polishDescVisible.value = false
    message.success('描述已更新')
  }
}

async function handleRepolishDescription() {
  if (!polishDescResult.value) return
  polishingDesc.value = true
  try {
    const res = await agentApi.polishMcpDescription(polishDescResult.value, form.mode)
    if (res?.polished_description) {
      polishDescResult.value = res.polished_description
      if (res.fallback) {
        message.warning('润色完成（已自动降级）')
      } else {
        message.success('AI 润色完成')
      }
    } else {
      message.warning('润色结果为空')
    }
  } catch (e) {
    message.error('AI 润色失败')
  } finally {
    polishingDesc.value = false
  }
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
  currentIsBuiltin.value = false
  Object.assign(form, defaultForm())
  stdioCommand.value = ''
  stdioArgsText.value = ''
  stdioEnvText.value = ''
  apiKey.value = ''
  basicUser.value = ''
  basicPass.value = ''
  headersText.value = ''
  oauthClientId.value = ''
  oauthClientSecret.value = ''
  oauthScopesText.value = ''
  oauthStatus.value = 'not_configured'
  // 重置加密 + 受众验证状态
  oauthEncrypted.value = false
  oauthAudienceValid.value = true
  oauthAudienceWarning.value = ''
  modalVisible.value = true
}

function openEdit(record) {
  isEdit.value = true
  currentIsBuiltin.value = !!record.is_builtin
  Object.assign(form, {
    ...defaultForm(),
    ...record,
    stdio_config: record.stdio_config || { command: '', args: [], env: {} },
    auth_type: record.auth_type || 'none',
    headers: record.headers || {},
    oauth_config: record.oauth_config || {},
    oauth_status: record.oauth_status || 'not_configured',
  })
  stdioCommand.value = form.stdio_config?.command || ''
  stdioArgsText.value = (form.stdio_config?.args || []).join('\n')
  stdioEnvText.value = Object.entries(form.stdio_config?.env || {})
    .map(([k, v]) => `${k}=${v}`)
    .join('\n')
  // 根据 auth_type 回显认证信息
  const headers = record.headers || {}
  apiKey.value = ''
  basicUser.value = ''
  basicPass.value = ''
  headersText.value = ''
  // OAuth 回显
  const oauthConfig = record.oauth_config || {}
  oauthClientId.value = oauthConfig.client_id || ''
  oauthClientSecret.value = oauthConfig.client_secret || ''
  const scopes = oauthConfig.scopes || oauthConfig.scopes_supported || []
  oauthScopesText.value = Array.isArray(scopes) ? scopes.join(' ') : (scopes || '')
  oauthStatus.value = record.oauth_status || 'not_configured'

  if (form.auth_type === 'bearer') {
    const authHeader = headers['Authorization'] || ''
    if (authHeader.startsWith('Bearer ')) {
      apiKey.value = authHeader.slice(7)
    }
  } else if (form.auth_type === 'basic') {
    const authHeader = headers['Authorization'] || ''
    if (authHeader.startsWith('Basic ')) {
      try {
        const decoded = atob(authHeader.slice(6))
        const idx = decoded.indexOf(':')
        if (idx > 0) {
          basicUser.value = decoded.slice(0, idx)
          basicPass.value = decoded.slice(idx + 1)
        }
      } catch (e) {
        // base64 解码失败，忽略
      }
    }
  } else if (form.auth_type === 'custom') {
    headersText.value = Object.entries(headers)
      .map(([k, v]) => `${k}: ${v}`)
      .join('\n')
  }
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

function parseHeaders(text) {
  const headers = {}
  if (!text) return headers
  text.split('\n').forEach(line => {
    line = line.trim()
    if (!line) return
    const idx = line.indexOf(':')
    if (idx > 0) {
      const key = line.slice(0, idx).trim()
      const value = line.slice(idx + 1).trim()
      if (key) headers[key] = value
    }
  })
  return headers
}

function buildAuthHeaders() {
  const headers = {}
  if (form.auth_type === 'bearer') {
    if (apiKey.value) {
      headers['Authorization'] = `Bearer ${apiKey.value}`
    }
  } else if (form.auth_type === 'basic') {
    if (basicUser.value || basicPass.value) {
      const credentials = btoa(`${basicUser.value}:${basicPass.value}`)
      headers['Authorization'] = `Basic ${credentials}`
    }
  } else if (form.auth_type === 'custom') {
    Object.assign(headers, parseHeaders(headersText.value))
  }
  return headers
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
    if (form.mode === 'sse' || form.mode === 'streamable_http') {
      payload.sse_url = form.sse_url
      payload.auth_type = form.auth_type
      if (form.auth_type === 'oauth') {
        // OAuth 配置
        const oauthConfig = form.oauth_config || {}
        if (oauthClientId.value) oauthConfig.client_id = oauthClientId.value
        if (oauthClientSecret.value) oauthConfig.client_secret = oauthClientSecret.value
        if (oauthScopesText.value) {
          oauthConfig.scopes = oauthScopesText.value.split(/\s+/).filter(Boolean)
        }
        payload.oauth_config = oauthConfig
        payload.headers = {}
      } else {
        payload.headers = buildAuthHeaders()
      }
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

// ── OAuth 计算属性 ──────────────────────────────────────
const oauthStatusText = computed(() => {
  const map = {
    not_configured: '未配置',
    pending: '授权中',
    authorized: '已授权',
    expired: '已过期',
    error: '授权失败',
  }
  return map[oauthStatus.value] || oauthStatus.value
})

const oauthStatusColor = computed(() => {
  const map = {
    not_configured: 'default',
    pending: 'processing',
    authorized: 'success',
    expired: 'warning',
    error: 'error',
  }
  return map[oauthStatus.value] || 'default'
})

// ── OAuth 操作函数 ──────────────────────────────────────

// 发起 OAuth 授权
async function handleOAuthAuthorize() {
  if (!form.id) {
    message.warning('请先保存 MCP 服务配置')
    return
  }
  oauthAuthorizing.value = true
  try {
    // 先保存当前 OAuth 配置
    const oauthConfig = form.oauth_config || {}
    if (oauthClientId.value) oauthConfig.client_id = oauthClientId.value
    if (oauthClientSecret.value) oauthConfig.client_secret = oauthClientSecret.value
    if (oauthScopesText.value) {
      oauthConfig.scopes = oauthScopesText.value.split(/\s+/).filter(Boolean)
    }
    await mcpApi.oauthConfig(form.id, oauthConfig)

    // 发起授权
    const callbackBase = `${window.location.origin}`
    const resp = await mcpApi.oauthAuthorize(form.id, { callback_base_url: callbackBase })
    const authUrl = resp.data?.data?.authorization_url
    if (!authUrl) {
      message.error('获取授权 URL 失败')
      return
    }

    // 监听回调消息
    oauthCallbackHandler.value = (event) => {
      if (event.data?.type !== 'oauth_callback') return
      window.removeEventListener('message', oauthCallbackHandler.value)
      oauthCallbackHandler.value = null

      if (event.data.status === 'authorized') {
        message.success('OAuth 授权成功')
        oauthStatus.value = 'authorized'
        // 刷新 OAuth 状态
        fetchOAuthStatus(form.id)
      } else {
        message.error('OAuth 授权失败: ' + (event.data.error || '未知错误'))
        oauthStatus.value = 'error'
      }
    }
    window.addEventListener('message', oauthCallbackHandler.value)

    // 在新窗口打开授权 URL
    const popup = window.open(authUrl, '_blank', 'width=800,height=700')
    if (!popup) {
      message.warning('无法打开新窗口, 请检查浏览器弹窗设置. 授权链接已复制到剪贴板.')
      // 降级: 尝试复制 URL
      try {
        await navigator.clipboard.writeText(authUrl)
      } catch (e) {
        // 忽略
      }
    }

    // 轮询检查 OAuth 状态 (备用方案, 如果 postMessage 不工作)
    const pollInterval = setInterval(async () => {
      try {
        const statusResp = await mcpApi.oauthStatus(form.id)
        const status = statusResp.data?.data?.oauth_status
        if (status === 'authorized') {
          clearInterval(pollInterval)
          oauthStatus.value = 'authorized'
          message.success('OAuth 授权成功')
          oauthAuthorizing.value = false
        } else if (status === 'error') {
          clearInterval(pollInterval)
          oauthStatus.value = 'error'
          oauthAuthorizing.value = false
        }
      } catch (e) {
        // 忽略轮询错误
      }
    }, 3000)

    // 5 分钟后停止轮询
    setTimeout(() => {
      clearInterval(pollInterval)
      oauthAuthorizing.value = false
    }, 300000)
  } catch (e) {
    message.error('发起授权失败: ' + (e.message || '未知错误'))
    oauthAuthorizing.value = false
  }
}

// 刷新 OAuth 令牌
async function handleOAuthRefresh() {
  if (!form.id) return
  oauthRefreshing.value = true
  try {
    await mcpApi.oauthRefresh(form.id)
    message.success('令牌刷新成功')
    await fetchOAuthStatus(form.id)
  } catch (e) {
    message.error('令牌刷新失败: ' + (e.message || '未知错误'))
  } finally {
    oauthRefreshing.value = false
  }
}

// 撤销 OAuth 授权
async function handleOAuthRevoke() {
  if (!form.id) return
  try {
    await mcpApi.oauthRevoke(form.id)
    message.success('已撤销 OAuth 授权')
    oauthStatus.value = 'not_configured'
    // 重置加密 + 受众验证状态
    oauthEncrypted.value = false
    oauthAudienceValid.value = true
    oauthAudienceWarning.value = ''
  } catch (e) {
    message.error('撤销失败: ' + (e.message || '未知错误'))
  }
}

// 发现授权服务器
async function handleOAuthDiscover() {
  if (!form.id) return
  try {
    const resp = await mcpApi.oauthDiscover(form.id)
    const metadata = resp.data?.data
    if (metadata) {
      message.success(`发现授权服务器: ${metadata.issuer || '成功'}`)
      // 更新 form 中的 oauth_config
      form.oauth_config = { ...(form.oauth_config || {}), ...metadata }
      // 回显发现的 scopes
      if (metadata.scopes_supported && !oauthScopesText.value) {
        oauthScopesText.value = metadata.scopes_supported.join(' ')
      }
    }
  } catch (e) {
    message.error('发现授权服务器失败: ' + (e.message || '未知错误'))
  }
}

// 查询 OAuth 状态
async function fetchOAuthStatus(mcpId) {
  try {
    const resp = await mcpApi.oauthStatus(mcpId)
    const data = resp.data?.data
    if (data) {
      oauthStatus.value = data.oauth_status || 'not_configured'
      // 令牌加密状态 + 受众验证告警
      oauthEncrypted.value = !!data.encrypted
      oauthAudienceValid.value = data.audience_valid !== false
      oauthAudienceWarning.value = data.audience_warning || ''
    }
  } catch (e) {
    // 忽略
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

.page-mcp :deep(.ant-table) {
  table-layout: fixed;
}

.page-mcp :deep(.ant-table .ant-table-cell) {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.page-mcp :deep(.ant-table .ant-table-cell .ant-tag) {
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* AI 润色描述相关样式 */
.description-wrapper {
  position: relative;
  width: 100%;
}

.description-wrapper .polish-btn {
  position: absolute;
  right: 8px;
  bottom: -22px;
  font-size: 12px;
  color: #722ed1;
  padding: 0 4px;
  height: auto;
  line-height: 1.4;
}

.description-wrapper .polish-btn:hover {
  color: #9254de;
  background: rgba(114, 46, 209, 0.06);
}

.polish-compare {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
}

.polish-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  overflow: hidden;
}

.polish-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: #fafafa;
  border-bottom: 1px solid #f0f0f0;
}

.polish-panel-title {
  font-weight: 500;
  font-size: 14px;
  color: #333;
}

.polish-textarea-readonly {
  background: #f5f5f5;
  cursor: not-allowed;
}

.polish-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid #f0f0f0;
}

/* 调整 a-form-item 底部间距以容纳按钮 */
.page-mcp :deep(.ant-form-item) {
  margin-bottom: 28px;
}
</style>
