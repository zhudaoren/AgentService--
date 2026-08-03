<template>
  <div class="page-agent">
    <div class="page-inner">
      <div class="page-header">
        <div>
          <h2 class="page-title">Agent 管理</h2>
          <p class="page-desc">创建、配置和管理智能体，支持 MCP 服务与 Skill 技能绑定</p>
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
          <template v-else-if="column.key === 'bindings'">
            <div class="bindings-cell">
              <a-tag v-if="record.mcp_count || record.mcp_bindings_count" color="blue">
                <database-outlined />
                {{ record.mcp_count || record.mcp_bindings_count || 0 }} MCP
              </a-tag>
              <a-tag v-if="record.skill_count || record.skill_bindings_count" color="purple">
                <appstore-outlined />
                {{ record.skill_count || record.skill_bindings_count || 0 }} Skill
              </a-tag>
            </div>
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
              <a-button type="link" size="small" @click="openToolsDrawer(record)">
                <tool-outlined />
                工具
              </a-button>
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
      width="720px"
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

        <!-- P2 新增：MCP + Skill 绑定面板 -->
        <a-divider orientation="left">能力绑定</a-divider>

        <a-collapse v-model:activeKey="bindingsActiveKey">
          <!-- MCP 绑定 -->
          <a-collapse-panel key="mcp">
            <template #header>
              <div class="panel-header">
                <database-outlined />
                <span>MCP 服务绑定</span>
                <a-badge :count="mcpBindings.length" style="margin-left: 8px" />
              </div>
            </template>
            <div class="panel-actions">
              <a-button type="primary" size="small" @click="openMCPBindPicker">
                <plus-outlined />
                添加绑定
              </a-button>
            </div>
            <a-table
              :columns="mcpBindingColumns"
              :data-source="mcpBindings"
              :pagination="false"
              size="small"
              row-key="mcp_service_id"
              :locale="{ emptyText: '尚未绑定 MCP 服务' }"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'name'">
                  <span class="binding-name">{{ record.name || record.mcp_name || '-' }}</span>
                </template>
                <template v-else-if="column.key === 'mode'">
                  <a-tag :color="record.mode === 'sse' ? 'blue' : 'orange'">
                    {{ record.mode === 'sse' ? 'SSE' : (record.mode || 'STDIO') }}
                  </a-tag>
                </template>
                <template v-else-if="column.key === 'status'">
                  <a-tag :color="mcpStatusColor(record.status)">
                    {{ mcpStatusText(record.status) }}
                  </a-tag>
                </template>
                <template v-else-if="column.key === 'enabled'">
                  <a-switch
                    v-model:checked="record.enabled"
                    :checked-value="true"
                    :unchecked-value="false"
                  />
                </template>
                <template v-else-if="column.key === 'action'">
                  <a-popconfirm
                    title="确定移除该 MCP 绑定？"
                    @confirm="removeMCPBinding(record)"
                  >
                    <a-button type="link" size="small" danger>
                      <delete-outlined />
                      移除
                    </a-button>
                  </a-popconfirm>
                </template>
              </template>
            </a-table>
          </a-collapse-panel>

          <!-- Skill 绑定 -->
          <a-collapse-panel key="skill">
            <template #header>
              <div class="panel-header">
                <appstore-outlined />
                <span>Skill 技能绑定</span>
                <a-badge :count="skillBindings.length" style="margin-left: 8px" />
              </div>
            </template>
            <div class="panel-actions">
              <a-button type="primary" size="small" @click="openSkillBindPicker">
                <plus-outlined />
                添加绑定
              </a-button>
            </div>
            <a-table
              :columns="skillBindingColumns"
              :data-source="skillBindings"
              :pagination="false"
              size="small"
              row-key="skill_id"
              :locale="{ emptyText: '尚未绑定 Skill 技能' }"
            >
              <template #bodyCell="{ column, record, index }">
                <template v-if="column.key === 'name'">
                  <span class="binding-name">{{ record.name || record.skill_name || '-' }}</span>
                </template>
                <template v-else-if="column.key === 'priority'">
                  <a-input-number
                    v-model:value="record.priority"
                    :min="0"
                    :max="999"
                    size="small"
                    style="width: 100px"
                  />
                </template>
                <template v-else-if="column.key === 'enabled'">
                  <a-switch
                    v-model:checked="record.enabled"
                    :checked-value="true"
                    :unchecked-value="false"
                  />
                </template>
                <template v-else-if="column.key === 'action'">
                  <a-popconfirm
                    title="确定移除该 Skill 绑定？"
                    @confirm="removeSkillBinding(record)"
                  >
                    <a-button type="link" size="small" danger>
                      <delete-outlined />
                      移除
                    </a-button>
                  </a-popconfirm>
                </template>
              </template>
            </a-table>
          </a-collapse-panel>
        </a-collapse>
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

    <!-- MCP 选择器 Modal -->
    <a-modal
      v-model:open="mcpPickerVisible"
      title="选择要绑定的 MCP 服务"
      :confirm-loading="mcpPickerLoading"
      width="640px"
      @ok="handleConfirmMCPBind"
      @cancel="mcpPickerVisible = false"
    >
      <a-table
        :columns="mcpPickerColumns"
        :data-source="availableMCPs"
        :loading="mcpPickerLoading"
        :pagination="false"
        size="small"
        row-key="id"
        :row-selection="rowSelectionMCP"
        :locale="{ emptyText: '暂无可绑定的 MCP 服务' }"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'mode'">
            <a-tag :color="record.mode === 'sse' ? 'blue' : 'orange'">
              {{ record.mode === 'sse' ? 'SSE' : 'STDIO' }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="mcpStatusColor(record.status)">
              {{ mcpStatusText(record.status) }}
            </a-tag>
          </template>
        </template>
      </a-table>
    </a-modal>

    <!-- Skill 选择器 Modal -->
    <a-modal
      v-model:open="skillPickerVisible"
      title="选择要绑定的 Skill 技能"
      :confirm-loading="skillPickerLoading"
      width="640px"
      @ok="handleConfirmSkillBind"
      @cancel="skillPickerVisible = false"
    >
      <a-table
        :columns="skillPickerColumns"
        :data-source="availableSkills"
        :loading="skillPickerLoading"
        :pagination="false"
        size="small"
        row-key="id"
        :row-selection="rowSelectionSkill"
        :locale="{ emptyText: '暂无可绑定的 Skill 技能' }"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'category'">
            <a-tag>{{ record.category || '通用' }}</a-tag>
          </template>
        </template>
      </a-table>
    </a-modal>

    <!-- 工具汇总 Drawer -->
    <a-drawer
      v-model:open="toolsDrawerVisible"
      :title="`Agent 工具一览 - ${toolsAgent?.name || ''}`"
      width="760px"
      :mask-closable="false"
    >
      <a-spin :spinning="toolsDrawerLoading">
        <template v-if="toolsSummary">
          <div class="tools-summary-section">
            <div class="section-title">
              <database-outlined />
              MCP 服务 ({{ (toolsSummary.mcp_services || []).length }})
            </div>
            <a-collapse v-if="(toolsSummary.mcp_services || []).length">
              <a-collapse-panel
                v-for="m in (toolsSummary.mcp_services || [])"
                :key="m.id || m.mcp_service_id"
              >
                <template #header>
                  <div class="mcp-header">
                    <span>{{ m.name || m.mcp_name || '未命名 MCP' }}</span>
                    <a-space style="margin-left: 8px">
                      <a-tag :color="m.mode === 'sse' ? 'blue' : 'orange'">
                        {{ m.mode === 'sse' ? 'SSE' : 'STDIO' }}
                      </a-tag>
                      <a-badge :count="(m.tools || []).length" />
                    </a-space>
                  </div>
                </template>
                <div v-if="(m.tools || []).length" class="tools-grid">
                  <div v-for="t in m.tools" :key="t.name" class="tool-card">
                    <div class="tool-card-name">
                      <tool-outlined />
                      {{ t.name }}
                    </div>
                    <div class="tool-card-desc">{{ t.description || '-' }}</div>
                  </div>
                </div>
                <a-empty v-else description="暂无工具" />
              </a-collapse-panel>
            </a-collapse>
            <a-empty v-else description="暂无绑定的 MCP 服务" />
          </div>

          <a-divider />

          <div class="tools-summary-section">
            <div class="section-title">
              <appstore-outlined />
              Skill 技能 ({{ (toolsSummary.skills || []).length }})
            </div>
            <div v-if="(toolsSummary.skills || []).length" class="skills-list">
              <div
                v-for="s in (toolsSummary.skills || [])"
                :key="s.id || s.skill_id"
                class="skill-card"
              >
                <div class="skill-card-header">
                  <span class="skill-card-name">{{ s.name || s.skill_name || '未命名' }}</span>
                  <a-tag v-if="s.priority !== undefined">优先级 {{ s.priority }}</a-tag>
                </div>
                <div class="skill-card-level0">
                  <div class="level-label">Level 0 概要：</div>
                  <pre class="level0-pre">{{
                    s.level0 ||
                    s.summary ||
                    (s.levels || []).find((l) => (l.level ?? 0) === 0)?.prompt_text ||
                    s.description ||
                    '-'
                  }}</pre>
                </div>
              </div>
            </div>
            <a-empty v-else description="暂无绑定的 Skill 技能" />
          </div>
        </template>
      </a-spin>
    </a-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { message } from 'ant-design-vue'
import {
  PlusOutlined,
  CopyOutlined,
  CrownOutlined,
  ThunderboltOutlined,
  DatabaseOutlined,
  AppstoreOutlined,
  ToolOutlined,
  DeleteOutlined,
} from '@ant-design/icons-vue'
import {
  agentApi,
  llmConfigApi,
  mcpApi,
  skillApi,
  agentBindingApi,
} from '@/api'

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
  { title: '绑定', key: 'bindings', width: 180 },
  { title: '状态', key: 'status', width: 120 },
  { title: 'Temperature', key: 'temperature', width: 120 },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 180, ellipsis: true },
  { title: '操作', key: 'action', width: 420, fixed: 'right' },
]

// 绑定面板
const bindingsActiveKey = ref(['mcp', 'skill'])
const originalMCPBindings = ref([])
const originalSkillBindings = ref([])
const mcpBindings = ref([])
const skillBindings = ref([])

const mcpBindingColumns = [
  { title: 'MCP 服务', key: 'name', ellipsis: true },
  { title: '模式', key: 'mode', width: 90 },
  { title: '状态', key: 'status', width: 100 },
  { title: '启用', key: 'enabled', width: 80 },
  { title: '操作', key: 'action', width: 90 },
]

const skillBindingColumns = [
  { title: 'Skill 名称', key: 'name', ellipsis: true },
  { title: '优先级', key: 'priority', width: 120 },
  { title: '启用', key: 'enabled', width: 80 },
  { title: '操作', key: 'action', width: 90 },
]

// MCP 选择器
const mcpPickerVisible = ref(false)
const mcpPickerLoading = ref(false)
const availableMCPs = ref([])
const selectedMCPRowKeys = ref([])
const rowSelectionMCP = computed(() => ({
  selectedRowKeys: selectedMCPRowKeys.value,
  onChange: (keys) => { selectedMCPRowKeys.value = keys },
}))

const mcpPickerColumns = [
  { title: '名称', dataIndex: 'name', key: 'name', ellipsis: true },
  { title: '模式', key: 'mode', width: 100 },
  { title: '状态', key: 'status', width: 100 },
  { title: '工具数', dataIndex: 'tool_count', key: 'tool_count', width: 90 },
]

// Skill 选择器
const skillPickerVisible = ref(false)
const skillPickerLoading = ref(false)
const availableSkills = ref([])
const selectedSkillRowKeys = ref([])
const rowSelectionSkill = computed(() => ({
  selectedRowKeys: selectedSkillRowKeys.value,
  onChange: (keys) => { selectedSkillRowKeys.value = keys },
}))

const skillPickerColumns = [
  { title: '名称', dataIndex: 'name', key: 'name', ellipsis: true },
  { title: '分类', key: 'category', width: 100 },
  { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
]

// 工具汇总 Drawer
const toolsDrawerVisible = ref(false)
const toolsAgent = ref(null)
const toolsDrawerLoading = ref(false)
const toolsSummary = ref(null)

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

function canDeploy(s) { return s === 'draft' }
function canStart(s) { return s === 'deployed' || s === 'stopped' }
function canPause(s) { return s === 'running' }
function canResume(s) { return s === 'paused' }
function canStop(s) { return s === 'running' || s === 'paused' || s === 'deployed' }

function mcpStatusText(s) {
  const map = { disconnected: '未连接', connecting: '连接中', connected: '已连接', error: '异常' }
  return map[s] || s || '未知'
}
function mcpStatusColor(s) {
  const map = { disconnected: 'default', connecting: 'gold', connected: 'green', error: 'red' }
  return map[s] || 'default'
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
async function openCreate() {
  isEdit.value = false
  Object.assign(form, defaultForm())
  mcpBindings.value = []
  skillBindings.value = []
  originalMCPBindings.value = []
  originalSkillBindings.value = []
  if (llmConfigs.value.length === 0) await fetchLlmConfigs()
  modalVisible.value = true
}

async function openEdit(record) {
  isEdit.value = true
  Object.assign(form, { ...defaultForm(), ...record })
  if (llmConfigs.value.length === 0) await fetchLlmConfigs()
  modalVisible.value = true
  // 加载当前绑定
  await loadBindings(record.id)
}

async function loadBindings(agentId) {
  try {
    const [mcpRes, skillRes] = await Promise.all([
      agentBindingApi.getMCPBindings(agentId).catch(() => []),
      agentBindingApi.getSkillBindings(agentId).catch(() => []),
    ])
    const mcpList = Array.isArray(mcpRes)
      ? mcpRes
      : mcpRes?.items || mcpRes?.list || mcpRes?.data || []
    const skillList = Array.isArray(skillRes)
      ? skillList
      : skillRes?.items || skillRes?.list || skillRes?.data || []
    mcpBindings.value = mcpList.map((b) => ({
      ...b,
      mcp_service_id: b.mcp_service_id ?? b.id,
      enabled: b.enabled !== false,
    }))
    skillBindings.value = skillList.map((b) => ({
      ...b,
      skill_id: b.skill_id ?? b.id,
      priority: b.priority ?? 100,
      enabled: b.enabled !== false,
    }))
    originalMCPBindings.value = JSON.parse(JSON.stringify(mcpBindings.value))
    originalSkillBindings.value = JSON.parse(JSON.stringify(skillBindings.value))
  } catch (e) {
    mcpBindings.value = []
    skillBindings.value = []
    originalMCPBindings.value = []
    originalSkillBindings.value = []
  }
}

async function handleSubmit() {
  try {
    await formRef.value.validate()
    submitting.value = true
    let savedAgentId = form.id
    if (isEdit.value) {
      await agentApi.update(form.id, { ...form })
      message.success('更新成功')
    } else {
      const res = await agentApi.create({ ...form })
      savedAgentId = res?.id || (typeof res === 'string' || typeof res === 'number' ? res : undefined)
      message.success('创建成功')
    }
    modalVisible.value = false

    // 同步绑定（如果是新建且拿到 id）
    if (savedAgentId) {
      await syncBindings(savedAgentId)
    }
    fetchList()
  } catch (e) {
  } finally {
    submitting.value = false
  }
}

async function syncBindings(agentId) {
  const origIdsMCP = new Set(originalMCPBindings.value.map((b) => String(b.mcp_service_id ?? b.id)))
  const currIdsMCP = new Set(mcpBindings.value.map((b) => String(b.mcp_service_id ?? b.id)))
  // 解绑（原值有，新值无）
  for (const b of originalMCPBindings.value) {
    const id = String(b.mcp_service_id ?? b.id)
    if (!currIdsMCP.has(id)) {
      try { await agentBindingApi.unbindMCP(agentId, b.mcp_service_id ?? b.id) } catch (e) {}
    }
  }
  // 新绑定（新值有，原值无）
  for (const b of mcpBindings.value) {
    const id = String(b.mcp_service_id ?? b.id)
    if (!origIdsMCP.has(id)) {
      try {
        await agentBindingApi.bindMCP(agentId, {
          mcp_service_id: b.mcp_service_id ?? b.id,
          enabled: b.enabled !== false,
        })
      } catch (e) {}
    }
  }
  // Skill
  const origIdsSkill = new Set(originalSkillBindings.value.map((b) => String(b.skill_id ?? b.id)))
  const currIdsSkill = new Set(skillBindings.value.map((b) => String(b.skill_id ?? b.id)))
  for (const b of originalSkillBindings.value) {
    const id = String(b.skill_id ?? b.id)
    if (!currIdsSkill.has(id)) {
      try { await agentBindingApi.unbindSkill(agentId, b.skill_id ?? b.id) } catch (e) {}
    }
  }
  for (const b of skillBindings.value) {
    const id = String(b.skill_id ?? b.id)
    if (!origIdsSkill.has(id)) {
      try {
        await agentBindingApi.bindSkill(agentId, {
          skill_id: b.skill_id ?? b.id,
          priority: b.priority ?? 100,
          enabled: b.enabled !== false,
        })
      } catch (e) {}
    }
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
    await agentApi.clone(item.id)
    message.success(`已添加官方 Agent [${item.name}]`)
    officialVisible.value = false
    fetchList()
  } catch (e) {}
}

// ============ AI 润色 ============
async function handlePolishPrompt() {
  if (!form.system_prompt || !form.system_prompt.trim()) return
  polishOriginal.value = form.system_prompt
  polishResult.value = ''
  polishVisible.value = true
  polishing.value = true
  try {
    const res = await agentApi.polishPrompt(form.system_prompt)
    if (res?.polished_prompt) {
      polishResult.value = res.polished_prompt
      if (res.fallback) message.warning('润色完成（已自动降级为模型默认参数）')
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
      if (res.fallback) message.warning('润色完成（已自动降级）')
      else message.success('AI 润色完成')
    } else message.warning('润色结果为空')
  } catch (e) {
    message.error('AI 润色失败')
  } finally {
    polishing.value = false
  }
}

function handleConfirmPolish() {
  if (!polishResult.value || !polishResult.value.trim()) {
    message.warning('润色结果为空')
    return
  }
  form.system_prompt = polishResult.value
  polishVisible.value = false
  message.success('已应用润色后的系统提示词')
}

// ============ MCP 绑定管理 ============
async function openMCPBindPicker() {
  selectedMCPRowKeys.value = []
  mcpPickerVisible.value = true
  mcpPickerLoading.value = true
  availableMCPs.value = []
  try {
    const res = await mcpApi.list({ page: 1, page_size: 200 })
    const list = Array.isArray(res) ? res : res?.items || res?.list || res?.data || []
    const boundIds = new Set(mcpBindings.value.map((b) => String(b.mcp_service_id ?? b.id)))
    availableMCPs.value = list.filter((m) => !boundIds.has(String(m.id)))
  } catch (e) {
    availableMCPs.value = []
  } finally {
    mcpPickerLoading.value = false
  }
}

function handleConfirmMCPBind() {
  if (selectedMCPRowKeys.value.length === 0) {
    message.warning('请选择要绑定的 MCP 服务')
    return
  }
  const toAdd = availableMCPs.value.filter((m) =>
    selectedMCPRowKeys.value.includes(m.id)
  )
  for (const m of toAdd) {
    mcpBindings.value.push({
      mcp_service_id: m.id,
      id: m.id,
      name: m.name,
      mode: m.mode,
      status: m.status,
      enabled: true,
    })
  }
  mcpPickerVisible.value = false
  message.success(`已添加 ${toAdd.length} 个 MCP 绑定`)
}

function removeMCPBinding(record) {
  mcpBindings.value = mcpBindings.value.filter(
    (b) => String(b.mcp_service_id ?? b.id) !== String(record.mcp_service_id ?? record.id)
  )
}

// ============ Skill 绑定管理 ============
async function openSkillBindPicker() {
  selectedSkillRowKeys.value = []
  skillPickerVisible.value = true
  skillPickerLoading.value = true
  availableSkills.value = []
  try {
    const res = await skillApi.list({ page: 1, page_size: 200 })
    const list = Array.isArray(res) ? res : res?.items || res?.list || res?.data || []
    const boundIds = new Set(skillBindings.value.map((b) => String(b.skill_id ?? b.id)))
    availableSkills.value = list.filter((s) => !boundIds.has(String(s.id)))
  } catch (e) {
    availableSkills.value = []
  } finally {
    skillPickerLoading.value = false
  }
}

function handleConfirmSkillBind() {
  if (selectedSkillRowKeys.value.length === 0) {
    message.warning('请选择要绑定的 Skill')
    return
  }
  const toAdd = availableSkills.value.filter((s) =>
    selectedSkillRowKeys.value.includes(s.id)
  )
  for (let i = 0; i < toAdd.length; i++) {
    const s = toAdd[i]
    skillBindings.value.push({
      skill_id: s.id,
      id: s.id,
      name: s.name,
      priority: (skillBindings.value.length || 0) * 10 + i,
      enabled: true,
    })
  }
  skillPickerVisible.value = false
  message.success(`已添加 ${toAdd.length} 个 Skill 绑定`)
}

function removeSkillBinding(record) {
  skillBindings.value = skillBindings.value.filter(
    (b) => String(b.skill_id ?? b.id) !== String(record.skill_id ?? record.id)
  )
}

// ============ 工具汇总 Drawer ============
async function openToolsDrawer(record) {
  toolsAgent.value = record
  toolsSummary.value = null
  toolsDrawerVisible.value = true
  toolsDrawerLoading.value = true
  try {
    const res = await agentBindingApi.getToolsSummary(record.id)
    toolsSummary.value = res || { mcp_services: [], skills: [] }
  } catch (e) {
    toolsSummary.value = { mcp_services: [], skills: [] }
  } finally {
    toolsDrawerLoading.value = false
  }
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

.bindings-cell {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
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

/* 绑定面板 */
.panel-header {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
}

.panel-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}

.binding-name {
  font-weight: 500;
  font-size: 13px;
}

/* 工具抽屉 */
.tools-summary-section {
  margin-bottom: 8px;
}

.section-title {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  color: #262626;
}

.mcp-header {
  display: inline-flex;
  align-items: center;
  font-weight: 500;
}

.tools-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}

.tool-card {
  background: #fafafa;
  border: 1px solid #f0f0f0;
  border-radius: 4px;
  padding: 8px 10px;
}

.tool-card-name {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
  font-weight: 600;
  color: #1677ff;
  margin-bottom: 4px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.tool-card-desc {
  font-size: 11px;
  color: #595959;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.skills-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.skill-card {
  background: #f9f0ff;
  border: 1px solid #d3adf7;
  border-radius: 6px;
  padding: 10px 12px;
}

.skill-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.skill-card-name {
  font-weight: 600;
  font-size: 13px;
  color: #531dab;
}

.skill-card-level0 {
  background: #fff;
  border-radius: 4px;
  padding: 8px 10px;
}

.level-label {
  font-size: 11px;
  color: #8c8c8c;
  margin-bottom: 4px;
}

.level0-pre {
  margin: 0;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #262626;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 120px;
  overflow: auto;
}
</style>
