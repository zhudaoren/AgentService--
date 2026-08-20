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
              <a-tooltip v-if="currentConv?.agent_name || currentConv?.agent_id" title="点击查看/调整智能体配置">
                <span class="agent-config-tag" @click="openAgentConfig">
                  <a-tag color="blue">
                    <robot-outlined />
                    {{ currentConv.agent_name || '智能体' }}
                    <setting-outlined class="agent-config-icon" />
                  </a-tag>
                </span>
              </a-tooltip>
            </a-space>
          </div>
          <div class="chat-header-actions">
            <!-- 搜索框 -->
            <a-input-search
              v-if="searchVisible"
              v-model:value="searchText"
              placeholder="搜索对话内容..."
              size="small"
              style="width: 240px"
              @search="doSearch"
              @change="onSearchChange"
            >
              <template #enterButton>
                <a-button size="small"><search-outlined /></a-button>
              </template>
            </a-input-search>
            <a-space>
              <span v-if="searchMatches.length > 0" class="search-nav">
                <a-button type="text" size="small" @click="navigateMatch(-1)"><left-outlined /></a-button>
                <span class="search-count">{{ currentMatchIndex + 1 }}/{{ searchMatches.length }}</span>
                <a-button type="text" size="small" @click="navigateMatch(1)"><right-outlined /></a-button>
              </span>
              <a-tooltip title="搜索对话">
                <a-button type="text" size="small" @click="searchVisible = !searchVisible">
                  <search-outlined v-if="!searchVisible" />
                  <close-outlined v-else />
                </a-button>
              </a-tooltip>
              <a-tooltip title="清空当前会话消息（仅界面）">
                <a-button type="text" size="small" @click="messages = []">
                  <clear-outlined />
                </a-button>
              </a-tooltip>
            </a-space>
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
              <div v-if="msg.role === 'user'" class="avatar-circle avatar-user">
                <user-outlined />
              </div>
              <div v-else class="avatar-circle avatar-agent">
                <robot-outlined />
              </div>
            </div>
            <div class="msg-content-col" :class="{ 'search-highlight': msg._searchMatch }">
              <!-- 发送者名称 -->
              <div class="msg-sender">
                <span v-if="msg.role === 'user'" class="sender-name sender-user">我</span>
                <span v-else class="sender-name sender-agent">
                  {{ currentConv?.agent_name || '智能体' }}
                </span>
              </div>

              <!-- 用户消息直接显示 -->
              <div v-if="msg.role === 'user'" class="user-message-wrap">
                <div class="msg-bubble user-bubble">
                  <div class="msg-content markdown-body" v-html="renderMarkdown(msg.content, searchText)"></div>
                </div>
                <div v-if="msg.attachments?.length" class="user-attachments">
                  <template v-for="(att, idx) in msg.attachments" :key="'att-' + (msg.id || msg._temp_id) + '-' + idx">
                    <a-image v-if="att.type === 'image'" :src="att.data_url || att.url" style="max-width:220px; margin: 4px 4px 0 0;" :preview="true" />
                    <div v-else-if="att.type === 'audio'" class="audio-chip" style="margin:4px 0">
                      <audio controls :src="att.data_url || att.url"></audio>
                      <span class="audio-name">{{ att.name }}</span>
                    </div>
                  </template>
                </div>
                <div class="user-msg-footer" v-if="!streaming || !msg._temp_id">
                  <span v-if="msg.created_at" class="msg-time">{{ formatTime(msg.created_at) }}</span>
                  <button class="msg-action-btn" @click="copyMessage(msg.content)">
                    <copy-outlined />
                    <span>复制</span>
                  </button>
                  <button class="msg-action-btn" @click="handleRollbackUserMsg(msg)" :disabled="streaming">
                    <undo-outlined />
                    <span>回撤</span>
                  </button>
                  <button class="msg-action-btn" @click="handleDeleteUserMsg(msg)" :disabled="streaming">
                    <delete-outlined />
                    <span>删除</span>
                  </button>
                </div>
              </div>

              <!-- Agent消息（区块顺序：工作模式 → 思考 → 计划 → 技能 → 工具 → 最终回答） -->
              <div v-else class="assistant-content" :class="{ 'is-error': msg._is_error }">
                <!-- 1. 工作模式提示 -->
                <div v-if="msg.workflow_mode" class="workflow-mode-block">
                  <span class="workflow-mode-value" :class="'mode-' + msg.workflow_mode">
                    {{ formatWorkflowMode(msg.workflow_mode) }}
                  </span>
                </div>

                <!-- 2. 思考过程（thinking） - 可折叠 -->
                <div v-if="msg.thinking || msg._thinkingActive || msg._thinkingMigrated" class="thinking-block" :class="{ collapsed: msg._thinkingCollapsed, active: msg._thinkingActive }">
                  <div class="thinking-header" @click="msg._thinkingCollapsed = !msg._thinkingCollapsed">
                    <div class="thinking-header-left">
                      <span class="thinking-icon-wrap" :class="{ 'is-thinking': msg._thinkingActive }">
                        <bulb-outlined class="thinking-icon" />
                      </span>
                      <span class="thinking-label" v-if="msg._thinkingActive">深度思考中</span>
                      <span class="thinking-label" v-else>已深度思考</span>
                      <a-spin v-if="msg._thinkingActive" size="small" class="thinking-spinner" />
                      <span v-if="!msg._thinkingActive && msg._thinkingDuration" class="thinking-duration">
                        用时 {{ formatDuration(msg._thinkingDuration) }}
                      </span>
                      <span v-if="msg._thinkingActive && msg._thinkingStartTime" class="thinking-duration thinking-duration-live">
                        {{ formatLiveDuration(msg._thinkingStartTime) }}
                      </span>
                      <span v-if="msg.thinkingIteration !== undefined && msg.thinkingIteration > 0" class="thinking-iteration">第 {{ msg.thinkingIteration + 1 }} 轮</span>
                    </div>
                    <down-outlined class="thinking-toggle" :class="{ rotated: msg._thinkingCollapsed }" />
                  </div>
                  <div v-show="!msg._thinkingCollapsed" class="thinking-content markdown-body">
                    <template v-if="msg.thinking" v-for="(seg, tIdx) in splitMermaidSegmentsText(msg.thinking)" :key="'th-' + (msg.id || msg._temp_id) + '-' + tIdx">
                      <MermaidBlock v-if="seg.type === 'mermaid'" :code="seg.code" title="思考中的设计图" />
                      <div v-else v-html="renderMarkdown(seg.text, searchText)"></div>
                    </template>
                    <div v-else-if="msg._thinkingMigrated && !msg._thinkingActive" class="thinking-empty">
                      <span class="thinking-empty-text">💡 思考过程已迁移至最终回答</span>
                    </div>
                    <div v-else-if="msg._thinkingActive" class="thinking-empty">
                      <span class="thinking-empty-text">思考中...</span>
                    </div>
                    <span v-if="msg._thinkingActive" class="streaming-cursor thinking-cursor"></span>
                  </div>
                </div>

                <!-- 3. Plan-and-Execute 计划卡片 -->
                <div v-if="msg.plan_steps?.length" class="plan-container" :class="{ collapsed: msg._planCollapsed }">
                  <div class="plan-header" @click="msg._planCollapsed = !msg._planCollapsed">
                    <div class="plan-header-left">
                      <span class="plan-icon-wrap">
                        <ordered-list-outlined />
                      </span>
                      <span class="plan-header-title">
                        执行计划
                        <span class="plan-steps-count">{{ msg.plan_steps.length }} 步</span>
                      </span>
                      <span v-if="msg.plan_duration_ms" class="plan-duration">
                        生成用时 {{ formatDuration(msg.plan_duration_ms) }}
                      </span>
                    </div>
                    <down-outlined class="plan-toggle" :class="{ rotated: msg._planCollapsed }" />
                  </div>
                  <div v-show="!msg._planCollapsed" class="plan-content">
                    <div v-if="msg.plan_summary" class="plan-summary">{{ msg.plan_summary }}</div>
                    <div class="plan-steps">
                      <div
                        v-for="(step, i) in msg.plan_steps"
                        :key="step.id || i"
                        class="plan-step"
                        :class="{
                          'is-completed': step._status === 'done',
                          'is-executing': step._status === 'executing',
                          'is-pending': !step._status || step._status === 'pending',
                        }"
                      >
                        <div class="step-indicator">
                          <span v-if="step._status === 'done'" class="step-icon step-done">
                            <check-circle-filled />
                          </span>
                          <span v-else-if="step._status === 'executing'" class="step-icon step-executing">
                            <loading-outlined />
                          </span>
                          <span v-else class="step-icon step-pending">{{ i + 1 }}</span>
                        </div>
                        <div class="step-body">
                          <div class="step-title">{{ step.title }}</div>
                          <div v-if="step.description" class="step-desc">{{ step.description }}</div>
                          <div v-if="step.tools_needed?.length" class="step-tools">
                            <span v-for="(tool, ti) in step.tools_needed.slice(0, 3)" :key="ti" class="step-tool-tag">
                              {{ tool }}
                            </span>
                            <span v-if="step.tools_needed.length > 3" class="step-tool-more">+{{ step.tools_needed.length - 3 }}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- 4. 技能使用卡片 -->
                <div v-if="msg.skills_used?.length" class="skills-container" :class="{ collapsed: msg._skillsCollapsed }">
                  <div class="skills-header" @click="msg._skillsCollapsed = !msg._skillsCollapsed">
                    <div class="skills-header-left">
                      <span class="skills-icon-wrap">
                        <bulb-outlined />
                      </span>
                      <span class="skills-header-title">
                        使用技能
                        <span class="skills-count">{{ msg.skills_used.length }}</span>
                      </span>
                    </div>
                    <down-outlined class="skills-toggle" :class="{ rotated: msg._skillsCollapsed }" />
                  </div>
                  <div v-show="!msg._skillsCollapsed" class="skills-list">
                    <div
                      v-for="(skill, i) in msg.skills_used"
                      :key="i"
                      class="skill-item"
                    >
                      <div class="skill-info">
                        <span class="skill-name">{{ skill.name }}</span>
                        <span v-if="skill.category" class="skill-category">[{{ skill.category }}]</span>
                        <span v-if="skill.description" class="skill-desc"> - {{ skill.description }}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- 5. 工具调用卡片 -->
                <template v-if="msg.tool_calls?.length">
                  <div class="tool-calls-container" :class="{ collapsed: msg._toolsCollapsed }">
                    <div class="tool-calls-header" @click="msg._toolsCollapsed = !msg._toolsCollapsed">
                      <div class="tool-calls-header-left">
                        <span class="tool-calls-icon-wrap" :class="{ 'is-loading': msg._toolLoading }">
                          <tool-outlined />
                        </span>
                        <span class="tool-calls-header-title">
                          调用工具
                          <span class="tool-calls-count">{{ msg.tool_calls.length }}</span>
                        </span>
                        <a-spin v-if="msg._toolLoading" size="small" class="tool-calls-spinner" />
                      </div>
                      <down-outlined class="tools-toggle" :class="{ rotated: msg._toolsCollapsed }" />
                    </div>
                    <div v-show="!msg._toolsCollapsed" class="tool-call-list">
                      <div
                        v-for="(tc, i) in msg.tool_calls"
                        :key="i"
                        class="tool-call-item"
                        :class="{ loading: msg._toolLoading && !tc.result && !tc.error, 'has-result': tc.result !== undefined && tc.result !== null, 'has-error': !!tc.error }"
                      >
                        <div class="tool-call-header">
                          <span class="tool-call-name-wrap">
                            <span class="tool-name-mono">{{ tc.name || tc.tool_name || 'unknown' }}</span>
                          </span>
                          <span v-if="tc.status === 'success' || (tc.result !== undefined && tc.result !== null)" class="tool-status status-success">
                            <check-circle-outlined /> 完成
                          </span>
                          <span v-else-if="tc.error" class="tool-status status-error">
                            <close-circle-outlined /> 失败
                          </span>
                          <span v-else class="tool-status status-loading">
                            <loading-outlined /> 执行中
                          </span>
                        </div>
                        <div class="tool-call-body">
                          <div class="tool-call-section" v-if="tc.arguments || tc.args">
                            <div class="section-label">入参</div>
                            <SpoilerBlock
                              :content="formatJSON(tc.arguments || tc.args || {})"
                              :limit="200"
                              label-code
                            />
                          </div>
                          <div class="tool-call-section" v-if="tc.error">
                            <div class="section-label error-label">错误</div>
                            <SpoilerBlock :content="String(tc.error)" :limit="200" error />
                          </div>
                          <div class="tool-call-section" v-else-if="tc.result !== undefined && tc.result !== null && tc.result !== ''">
                            <div class="section-label">结果</div>
                            <SpoilerBlock :content="formatJSON(tc.result)" :limit="200" success />
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </template>

                <!-- 6. 最终回答 -->
                <div v-if="msg.content" class="answer-block" :class="{ collapsed: msg._answerCollapsed }">
                  <div class="answer-header" @click="msg._answerCollapsed = !msg._answerCollapsed">
                    <div class="answer-header-left">
                      <span class="answer-icon-wrap">
                        <message-outlined class="answer-icon" />
                      </span>
                      <span class="answer-label">最终回答</span>
                    </div>
                    <down-outlined class="answer-toggle" :class="{ rotated: msg._answerCollapsed }" />
                  </div>
                  <div v-show="!msg._answerCollapsed" class="answer-content">
                    <div class="msg-content markdown-body assistant-text" :class="{ 'is-error-content': msg._is_error }">
                      <template v-for="(seg, segIdx) in splitMermaidSegmentsText(msg.content)" :key="'ans-' + (msg.id || msg._temp_id) + '-' + segIdx">
                        <MermaidBlock v-if="seg.type === 'mermaid'" :code="seg.code" title="软件设计图" />
                        <div v-else v-html="renderMarkdown(seg.text, searchText)"></div>
                      </template>
                      <span v-if="streaming && msg._temp_id && msg.content" class="streaming-cursor"></span>
                    </div>
                    <div class="msg-footer" v-if="msg.content && !streaming">
                      <span v-if="msg.created_at" class="msg-time">{{ formatTime(msg.created_at) }}</span>
                      <template v-if="!msg._is_error">
                        <button class="msg-action-btn" @click="copyMessage(msg.content)">
                          <copy-outlined />
                          <span>复制</span>
                        </button>
                        <button class="msg-action-btn" @click="handleRetry(msg)">
                          <reload-outlined />
                          <span>重试</span>
                        </button>
                      </template>
                      <button v-else class="msg-action-btn" @click="handleRetry(msg)">
                        <reload-outlined />
                        <span>重试</span>
                      </button>
                    </div>
                  </div>
                </div>
                <!-- 流式加载中的内联指示器（消息已创建但尚无内容时） -->
                <div v-if="streaming && msg._temp_id && !msg.content && !msg.thinking && !msg._thinkingActive && !msg._thinkingMigrated && (!msg.tool_calls || msg.tool_calls.length === 0) && (!msg.plan_steps || msg.plan_steps.length === 0) && (!msg.skills_used || msg.skills_used.length === 0)" class="inline-loading">
                  <span class="typing-dots">
                    <span class="dot"></span>
                    <span class="dot"></span>
                    <span class="dot"></span>
                  </span>
                  <span class="inline-loading-text">正在思考...</span>
                </div>
              </div>
            </div>
          </div>
          <!-- 流式加载中的指示器（仅在尚未创建任何 assistant 消息时显示） -->
          <div v-if="streaming && !hasAssistantMessage" class="msg-row assistant loading-indicator">
            <div class="msg-avatar">
              <div class="avatar-circle avatar-agent">
                <robot-outlined />
              </div>
            </div>
            <div class="msg-content-col">
              <div class="msg-sender">
                <span class="sender-name sender-agent">
                  {{ currentConv?.agent_name || '智能体' }}
                </span>
              </div>
              <div class="assistant-content">
                <div class="msg-typing">
                  <span class="typing-dots">
                    <span class="dot"></span>
                    <span class="dot"></span>
                    <span class="dot"></span>
                  </span>
                  <span class="msg-typing-text">正在思考...</span>
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
          <div style="flex:1; display:flex; flex-direction:column; gap:8px;">
            <a-textarea
              v-model:value="inputText"
              :auto-size="{ minRows: 1, maxRows: 6 }"
              placeholder="输入消息，按 Enter 发送，Shift+Enter 换行"
              class="chat-input"
              :disabled="streaming"
              @keydown="handleKeydown"
            />
            <div v-if="attachments.length" class="attachment-bar">
              <div v-for="(att,i) in attachments" :key="att.id" class="attachment-chip">
                <img v-if="att.type==='image'" class="att-thumb" :src="att.data_url" />
                <span v-else class="att-audio-icon">🎵</span>
                <div class="att-meta">
                  <div class="att-name">{{ att.name }}</div>
                  <div class="att-size">{{ formatSize(att.size) }}</div>
                </div>
                <a-button type="link" size="small" danger @click="removeAttachment(i)">×</a-button>
              </div>
            </div>
            <div class="chat-input-toolbar">
              <a-upload
                :multiple="true"
                :before-upload="beforeAttachmentUpload"
                :show-upload-list="false"
                accept="image/*,audio/*"
              >
                <a-button type="text" :title="'上传附件（图片/音频）'">📎 附件</a-button>
              </a-upload>
            </div>
          </div>
          <div class="chat-input-actions">
            <a-button
              v-if="!streaming"
              type="primary"
              :disabled="!inputText.trim() && attachments.length === 0"
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

    <!-- 智能体配置 Modal -->
    <a-modal
      v-model:open="agentConfigVisible"
      title="智能体配置"
      :confirm-loading="agentConfigSaving"
      width="680px"
      @ok="handleSaveAgentConfig"
      @cancel="agentConfigVisible = false"
    >
      <a-spin :spinning="agentConfigLoading">
        <a-form layout="vertical" v-if="agentConfigForm.id">
          <a-descriptions :column="2" size="small" bordered class="agent-config-desc">
            <a-descriptions-item label="Agent 名称">
              {{ agentConfigForm.name || '-' }}
            </a-descriptions-item>
            <a-descriptions-item label="状态">
              <a-tag :color="agentConfigForm.status === 'running' ? 'green' : 'default'">
                {{ agentConfigForm.status === 'running' ? '运行中' : '已停止' }}
              </a-tag>
            </a-descriptions-item>
            <a-descriptions-item label="描述" :span="2">
              {{ agentConfigForm.description || '无' }}
            </a-descriptions-item>
            <a-descriptions-item label="LLM 配置" :span="2">
              {{ agentConfigForm.llm_config_name || agentConfigForm.llm_config_id || '未配置' }}
            </a-descriptions-item>
          </a-descriptions>

          <a-divider orientation="left" style="font-size: 13px; margin: 16px 0 12px">可调整参数</a-divider>

          <a-form-item label="系统提示词 (System Prompt)" name="system_prompt">
            <a-textarea
              v-model:value="agentConfigForm.system_prompt"
              :rows="6"
              placeholder="定义 Agent 的角色、能力和行为约束"
            />
          </a-form-item>
          <a-row :gutter="16">
            <a-col :span="8">
              <a-form-item label="温度 (Temperature)">
                <a-input-number
                  v-model:value="agentConfigForm.temperature"
                  :min="0"
                  :max="2"
                  :step="0.1"
                  style="width: 100%"
                />
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item label="Top P">
                <a-input-number
                  v-model:value="agentConfigForm.top_p"
                  :min="0"
                  :max="1"
                  :step="0.1"
                  style="width: 100%"
                />
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item label="Max Tokens">
                <a-input-number
                  v-model:value="agentConfigForm.max_tokens"
                  :min="1"
                  :max="128000"
                  :step="256"
                  style="width: 100%"
                />
              </a-form-item>
            </a-col>
          </a-row>
          <div class="agent-config-tip">
            <info-circle-outlined />
            修改后将立即生效，后续对话使用新的配置参数。
          </div>
        </a-form>
      </a-spin>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted, nextTick, watch, computed, defineComponent, h } from 'vue'
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
  CheckCircleFilled,
  CloseCircleOutlined,
  ReloadOutlined,
  DownOutlined,
  UpOutlined,
  SearchOutlined,
  LeftOutlined,
  RightOutlined,
  BulbOutlined,
  SettingOutlined,
  InfoCircleOutlined,
  LoadingOutlined,
  OrderedListOutlined,
  UndoOutlined,
  CloseOutlined,
} from '@ant-design/icons-vue'
import { marked } from 'marked'
import MermaidBlock from '@/components/MermaidBlock.vue'
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

// ============ 附件上传 ============
const attachments = ref([]) // [{id, type, mime, name, data_url, size}]
const maxAttSize = 8 * 1024 * 1024        // 8MB per file
const maxTotalSize = 30 * 1024 * 1024     // 30MB total

function formatSize(bytes) {
  if (!bytes || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let n = bytes
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

function removeAttachment(i) {
  attachments.value.splice(i, 1)
}

function beforeAttachmentUpload(file) {
  const mime = file.type || ''
  const isImage = mime.startsWith('image/')
  const isAudio = mime.startsWith('audio/')
  if (!isImage && !isAudio) {
    message.warning('仅支持图片/音频附件')
    return false
  }
  if (file.size > maxAttSize) {
    message.warning(`单文件不能超过 ${formatSize(maxAttSize)}`)
    return false
  }
  const totalNow = attachments.value.reduce((s, a) => s + (a.size || 0), 0) + file.size
  if (totalNow > maxTotalSize) {
    message.warning(`附件总大小不能超过 ${formatSize(maxTotalSize)}`)
    return false
  }
  if (isAudio && file.size > maxAttSize) {
    message.warning(`音频超过 ${formatSize(maxAttSize)}，已跳过`)
    return false
  }
  const reader = new FileReader()
  reader.onload = (e) => {
    attachments.value.push({
      id: Date.now() + '_' + Math.random().toString(36).slice(2, 8),
      type: isImage ? 'image' : 'audio',
      mime,
      name: file.name,
      size: file.size,
      data_url: e.target.result,
    })
  }
  reader.readAsDataURL(file)
  return false // 阻止 ant-design 自动上传
}

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

// ============ 搜索 ============
const searchVisible = ref(false)
const searchText = ref('')
const searchMatches = ref([])
const currentMatchIndex = ref(-1)

// ============ 智能体配置弹窗 ============
const agentConfigVisible = ref(false)
const agentConfigLoading = ref(false)
const agentConfigSaving = ref(false)
const agentConfigForm = reactive({
  id: undefined,
  name: '',
  description: '',
  status: '',
  llm_config_id: undefined,
  llm_config_name: '',
  system_prompt: '',
  temperature: 0.7,
  top_p: 1.0,
  max_tokens: 2048,
})

function onSearchChange() {
  if (!searchText.value.trim()) {
    searchMatches.value = []
    currentMatchIndex.value = -1
    // 清除高亮
    messages.value.forEach(m => { m._searchMatch = false })
  }
}

function doSearch() {
  const query = searchText.value.trim().toLowerCase()
  if (!query) {
    searchMatches.value = []
    currentMatchIndex.value = -1
    // 清除所有搜索相关状态
    messages.value.forEach(m => { 
      m._searchMatch = false
      m._thinkingCollapsed = false  // 重置思考块折叠状态
    })
    return
  }
  // 清除旧高亮
  messages.value.forEach(m => { m._searchMatch = false })
  // 查找匹配的消息
  const matches = []
  messages.value.forEach((m, idx) => {
    const content = (m.content || '').toLowerCase()
    const thinking = (m.thinking || '').toLowerCase()
    const toolCallsText = (m.tool_calls || []).map(tc => 
      `${tc.name || ''} ${tc.tool_name || ''} ${JSON.stringify(tc.arguments || tc.args || {})}`
    ).join(' ').toLowerCase()
    if (content.includes(query) || thinking.includes(query) || toolCallsText.includes(query)) {
      matches.push(idx)
      m._searchMatch = true
      // 展开思考块以便查看高亮
      if (thinking.includes(query)) {
        m._thinkingCollapsed = false
      }
      // 展开工具调用块以便查看高亮
      if (toolCallsText.includes(query)) {
        m._toolsCollapsed = false
      }
    }
  })
  searchMatches.value = matches
  if (matches.length > 0) {
    currentMatchIndex.value = 0
    scrollToMessage(matches[0])
  } else {
    currentMatchIndex.value = -1
    message.info('未找到匹配内容')
  }
}

function navigateMatch(direction) {
  if (searchMatches.value.length === 0) return
  currentMatchIndex.value = (currentMatchIndex.value + direction + searchMatches.value.length) % searchMatches.value.length
  const msgIdx = searchMatches.value[currentMatchIndex.value]
  // 确保展开思考块和工具调用块
  const msg = messages.value[msgIdx]
  if (msg) {
    if ((msg.thinking || '').toLowerCase().includes(searchText.value.trim().toLowerCase())) {
      msg._thinkingCollapsed = false
    }
    if ((msg.tool_calls || []).some(tc => 
      `${tc.name || ''} ${tc.tool_name || ''} ${JSON.stringify(tc.arguments || tc.args || {})}`.toLowerCase().includes(searchText.value.trim().toLowerCase())
    )) {
      msg._toolsCollapsed = false
    }
  }
  scrollToMessage(msgIdx)
}

function scrollToMessage(msgIndex) {
  nextTick(() => {
    const el = msgListRef.value?.children[msgIndex]
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      el.classList.add('search-flash')
      setTimeout(() => el.classList.remove('search-flash'), 1500)
    }
  })
}

// 最后一条 assistant 消息
const lastAssistantMessage = computed(() => {
  const list = messages.value
  for (let i = list.length - 1; i >= 0; i--) {
    if (list[i].role === 'assistant') return list[i]
  }
  return null
})

// 最后一条 assistant 消息是否已有内容（思考、回答、工具、计划任一存在即认为有内容）
const lastAssistantHasContent = computed(() => {
  const msg = lastAssistantMessage.value
  if (!msg) return false
  return !!(msg.content || msg.thinking || msg._thinkingActive || msg._thinkingMigrated 
    || (msg.tool_calls && msg.tool_calls.length > 0)
    || (msg.plan_steps && msg.plan_steps.length > 0))
})

// 是否已有 assistant 消息（用于控制加载指示器不重复显示）
const hasAssistantMessage = computed(() => {
  return messages.value.some(m => m.role === 'assistant')
})

// ============ 错误与工具提示友好化 ============

/**
 * 将后端返回的技术性错误信息转换为用户可理解的中文提示
 */
function humanizeError(raw) {
  if (!raw) return '未知错误'
  const s = String(raw).trim()

  // 1. 常见的工具/服务类错误
  if (/HTTP\s*5\d{2}/.test(s) || /服务不可用|service.*unavailable|5\d{2}/i.test(s)) {
    return '依赖的工具服务暂时不可用（可能正在重启或过载），建议稍后重试'
  }
  if (/HTTP\s*408|timeout|timed.?out|超时/i.test(s)) {
    return '请求超时，可能是网络较慢或工具执行耗时过长，建议稍后重试'
  }
  if (/HTTP\s*4\d{2}/.test(s)) {
    const m = s.match(/message["']?\s*[:=]\s*["']([^"']{3,80})["']/)
    if (m) return `请求参数有误：${m[1]}`
    return '请求被拒绝（参数无效或没有权限），可检查 Agent 配置后重试'
  }
  if (/mcp_service_id|mcp_service_name|必须提供.*mcp/i.test(s)) {
    return '当前 Agent 绑定的 MCP 工具信息不完整，请在 Agent 配置页面重新绑定 MCP 服务'
  }
  if (/调用工具.*失败|工具.*失败|tool.*fail/i.test(s)) {
    const toolName = (s.match(/tool[_\s-]*name["']?\s*[:=]\s*["'](\w+)["']/i) || [])[1]
      || (s.match(/调用工具\s+(\w+)/i) || [])[1]
      || ''
    return toolName
      ? `工具「${toolName}」调用失败，请稍后重试，或联系管理员检查该 MCP 服务状态`
      : 'Agent 绑定的某个工具调用失败，请稍后重试'
  }
  if (/Data too long|column.*too long|1406/i.test(s)) {
    return '保存消息失败（内容过长），请减少输入长度或分多次提问'
  }
  if (/LLM|模型|model|api.?key|401|403.*key/i.test(s)) {
    return 'AI 模型调用失败，请检查 LLM 配置（API Key 是否有效、是否欠费）'
  }
  if (/conversation.?not.?found|会话.*不存在|agent.*not.?found|Agent.*不存在/i.test(s)) {
    return '当前会话或 Agent 已被删除，请新建会话后重试'
  }
  if (/连接.*拒绝|connection.*refused|ECONNREFUSED|network.*error|未连接/i.test(s)) {
    return '无法连接到后端服务，请确认 chat-svc 是否正常启动，以及网络是否通畅'
  }
  if (/AbortError|aborted|已中止/i.test(s)) {
    return '请求已被用户主动取消'
  }

  // 2. 如果是标准 JSON，提取 message/detail
  try {
    const firstBrace = s.indexOf('{')
    if (firstBrace >= 0) {
      const json = JSON.parse(s.slice(firstBrace))
      const detail = json.detail || json.message || json.error || json.msg
      if (detail && typeof detail === 'string' && detail.length <= 120) {
        return detail
      }
    }
  } catch (_) {}

  // 3. 纯文本过长 → 截短并说明
  if (s.length > 160) {
    return s.slice(0, 160) + '…（错误详情已截断，可查看后端日志了解完整信息）'
  }

  return s
}

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

function escapeRegExp(string) {
  try {
    return String(string).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  } catch (e) {
    return String(string)
  }
}

/**
 * 安全版关键词高亮：避免使用动态 new RegExp（会因特殊字符/半切分触发 SyntaxError）
 * 使用多次 indexOf + 字符串切片拼接实现，100% 无正则语法错误风险
 */
function highlightKeywords(text, keywords) {
  if (!text || !keywords || !keywords.trim()) return text
  try {
    const haystack = String(text)
    const needle = keywords.trim()
    const needleLower = needle.toLowerCase()
    // 特殊字符或单字符场景：直接安全搜索，不构造任何 RegExp
    const hlOpen = "<span class='search-highlight-keyword'>"
    const hlClose = "</span>"
    let result = ''
    let pos = 0
    const lowerText = haystack.toLowerCase()
    // 限制最多替换 200 次，防止极端场景卡死
    let replacements = 0
    while (pos < haystack.length && replacements < 200) {
      const idx = lowerText.indexOf(needleLower, pos)
      if (idx < 0) break
      // 拷贝 [pos, idx) 的原文
      result += haystack.slice(pos, idx)
      // 包裹匹配片段（保持原大小写）
      result += hlOpen + haystack.slice(idx, idx + needle.length) + hlClose
      pos = idx + needle.length
      replacements++
    }
    if (replacements === 0) return haystack
    result += haystack.slice(pos)
    return result
  } catch (e) {
    return String(text)
  }
}

function renderMarkdown(text, keywords = '') {
  if (!text) return ''
  try {
    let content = String(text)
    if (keywords && keywords.trim()) {
      content = highlightKeywords(content, keywords)
    }
    try {
      return marked.parse(content)
    } catch (mdErr) {
      // marked 解析失败：降级为 HTML 转义后的纯文本
      const escaped = content
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\n/g, '<br/>')
      return escaped
    }
  } catch (e) {
    // 终极回退：纯文本（保留换行）
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br/>')
  }
}

// ============ Mermaid 代码块分段渲染支持 ============
function extractMermaidBlocks(content) {
  if (!content) return { text: content || '', blocks: [] }
  const blocks = []
  const regex = /```mermaid\s*\n([\s\S]*?)```/g
  let i = 0
  const text = content.replace(regex, (match, code) => {
    blocks.push({ index: i++, code: code.trim() })
    return `\n__MERMAID_BLOCK_PLACEHOLDER_${i - 1}__\n`
  })
  return { text, blocks }
}
function splitMermaidSegments(content) {
  const { text, blocks } = extractMermaidBlocks(content)
  const out = []
  text.split(/__MERMAID_BLOCK_PLACEHOLDER_(\d+)__/g).forEach((chunk, k) => {
    if (k % 2 === 0) {
      if (chunk) out.push({ type: 'text', text: chunk })
    } else {
      const idx = parseInt(chunk, 10)
      const blk = blocks[idx]
      if (blk) out.push({ type: 'mermaid', code: blk.code })
    }
  })
  return out
}
const splitMermaidSegmentsText = (raw) => splitMermaidSegments(raw || '')

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

function handleRetry(msg) {
  const idx = messages.value.indexOf(msg)
  if (idx < 0) return
  if (streaming.value) return
  let userMsg = null
  let userIdx = -1
  for (let i = idx - 1; i >= 0; i--) {
    if (messages.value[i].role === 'user') {
      userMsg = messages.value[i]
      userIdx = i
      break
    }
  }
  if (userMsg) {
    // 删除当前 agent 消息及之后的所有消息
    messages.value.splice(idx, messages.value.length - idx)
    message.info('正在重新生成回答…')
    regenerating.value = true
    startStream({
      payload: {
        conversation_id: currentConvId.value,
        content: userMsg.content,
        attachments: userMsg.attachments || [],
      },
      isRegenerate: true,
    })
  } else {
    message.warning('未找到对应的用户提问，请直接在输入框重新输入')
  }
}

// ---------- 用户消息操作：复制 / 删除 / 回撤 ----------
/**
 * 回撤（回退到该用户消息发起前的状态）
 * - 移除该用户消息及之后的所有消息
 * - 将用户消息内容填回输入框并聚焦，等待用户编辑或重新发送
 */
async function handleRollbackUserMsg(msg) {
  if (streaming.value) {
    message.warning('请先等待当前生成完成或手动停止')
    return
  }
  const idx = messages.value.indexOf(msg)
  if (idx < 0) return
  const originalText = msg.content
  messages.value.splice(idx, messages.value.length - idx)
  inputText.value = originalText
  message.success('已回退到该消息前，内容已填入输入框，可编辑后重新发送')
  await nextTick()
  const textarea = document.querySelector('.chat-input-area textarea') || document.querySelector('.chat-input-area .ant-input')
  if (textarea) textarea.focus()
}

/**
 * 删除单条用户消息及之后的所有消息
 */
function handleDeleteUserMsg(msg) {
  if (streaming.value) {
    message.warning('请先等待当前生成完成或手动停止')
    return
  }
  const idx = messages.value.indexOf(msg)
  if (idx < 0) return
  messages.value.splice(idx, messages.value.length - idx)
  message.success('已删除该消息及后续对话')
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
    message.error(humanizeError(e?.message || e || '加载会话列表失败'))
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
    message.error(humanizeError(e?.message || e || '加载 Agent 列表失败'))
  } finally {
    agentLoading.value = false
  }
}

async function selectConversation(conv) {
  if (streaming.value) {
    message.warning('请先点击「停止生成」，再切换其他会话')
    return
  }
  currentConvId.value = conv.id
  currentConv.value = conv
  messages.value = []
  await loadMessages(conv.id)
}

// 规范化 tool_calls：后端存储格式兼容
// 后端可能存储为 [ ... ] 或 { "calls": [ ... ], "_plan_steps": [...], "_skills_used": [...] }
// 返回：{ calls, planSteps, skillsUsed, planDurationMs }
function normalizeToolCalls(raw) {
  if (!raw) return { calls: [], planSteps: [], skillsUsed: [], planDurationMs: 0 }
  let calls = []
  if (Array.isArray(raw)) {
    calls = raw
  } else if (raw && typeof raw === 'object') {
    if (Array.isArray(raw.calls)) calls = raw.calls
    else if (Array.isArray(raw.tool_calls)) calls = raw.tool_calls
  }
  // 附加元信息（刷新后恢复用）
  const planSteps = Array.isArray(raw?._plan_steps) ? raw._plan_steps : []
  const skillsUsed = Array.isArray(raw?._skills_used) ? raw._skills_used : []
  const planDurationMs = raw?._plan_duration_ms || 0
  return { calls, planSteps, skillsUsed, planDurationMs }
}

async function loadMessages(convId) {
  try {
    // 传 page_size=200 确保一次性加载全部消息，避免分页截断导致最新消息丢失
    const res = await conversationApi.messages(convId, { page: 1, page_size: 200 })
    const list = Array.isArray(res) ? res : res?.items || res?.list || res?.messages || res?.data || []
    const rawMessages = list.map((m) => {
      const messageType = m.message_type || 'assistant'
      let role = m.role
      if (!role) {
        if (messageType === 'user') {
          role = 'user'
        } else {
          role = 'assistant'
        }
      }
      const normalizedTc = normalizeToolCalls(m.tool_calls)
      let toolName = m.tool_name || m.name || ''
      let toolResult = m.result
      let toolError = m.error
      const tcCalls = normalizedTc.calls || []
      if (!toolName && tcCalls.length > 0) {
        toolName = tcCalls[0].tool_name || tcCalls[0].name || ''
      }
      if (messageType === 'tool_result' && m.tool_results) {
        const results = Array.isArray(m.tool_results) ? m.tool_results : (m.tool_results.results || m.tool_results.calls || [])
        if (results.length > 0) {
          const r = results[0]
          if (!toolName) toolName = r.tool_name || r.name || ''
          if (toolResult === undefined) toolResult = r.result ?? r.output ?? r.content
          if (toolError === undefined) toolError = r.error || r.error_message || ''
        }
      }
      // 从持久化字段恢复计划/技能（如果原消息没有，用 tool_calls 里附加的元信息）
      const restoredPlanSteps = (Array.isArray(m.plan_steps) && m.plan_steps.length)
        ? m.plan_steps
        : normalizedTc.planSteps
      const restoredSkillsUsed = (Array.isArray(m.skills_used) && m.skills_used.length)
        ? m.skills_used
        : normalizedTc.skillsUsed
      const restoredPlanDuration = (m.plan_duration_ms ?? normalizedTc.planDurationMs) || 0
      return {
        ...m,
        role,
        content: m.content ?? m.text ?? '',
        message_type: messageType,
        attachments: m.attachments || null,
        tool_calls: tcCalls,
        tool_name: toolName,
        name: toolName,
        result: toolResult,
        error: toolError,
        _toolsCollapsed: false,
        _toolLoading: false,
        _planCollapsed: false,
        plan_steps: restoredPlanSteps.map((s, i) => ({
          ...s,
          _status: s._status || 'done',
        })),
        skills_used: restoredSkillsUsed,
        plan_duration_ms: restoredPlanDuration,
      }
    })
    
    // 合并 tool_call 和 tool_result 消息到相邻的 assistant 消息
    const mergedMessages = []
    let pendingToolCalls = []
    
    for (let i = 0; i < rawMessages.length; i++) {
      const msg = rawMessages[i]
      
      if (msg.message_type === 'tool_call' && msg.tool_calls?.length) {
        // 收集工具调用
        pendingToolCalls.push(...msg.tool_calls.map(tc => ({
          ...tc,
          // 只有当没有结果和错误、且没有已明确 status 时才设为 loading，
          // 否则保留原始状态（例如持久化里的 success/failed）
          status: (tc.status === 'success' || tc.status === 'failed')
            ? tc.status
            : ((tc.result !== undefined && tc.result !== null) || tc.error) ? (tc.status || 'success') : 'loading',
        })))
        continue  // 跳过独立的 tool_call 消息
      }
      
      if (msg.message_type === 'tool_result') {
        // 将工具结果更新到待处理的工具调用中
        // 1. 解析所有可能的结果数据（处理单个或多个结果）
        let resultsToProcess = []
        if (Array.isArray(msg.tool_results)) {
          resultsToProcess = msg.tool_results
        } else if (msg.tool_results && Array.isArray(msg.tool_results.results)) {
          resultsToProcess = msg.tool_results.results
        } else if (msg.tool_results && Array.isArray(msg.tool_results.calls)) {
          resultsToProcess = msg.tool_results.calls
        } else {
          // 如果没有嵌套数组结构，尝试用顶层字段构造一个结果（兼容单结果场景或预处理后结构）
          const fallbackName = msg.tool_name || msg.name || ''
          const fallbackResult = msg.result
          const fallbackError = msg.error
          if (fallbackName || fallbackResult !== undefined || fallbackError) {
            resultsToProcess.push({
              tool_name: fallbackName,
              name: fallbackName,
              result: fallbackResult,
              error: fallbackError,
            })
          }
        }

        // 2. 遍历所有结果，更新到 pendingToolCalls
        for (const r of resultsToProcess) {
          const rToolName = r.tool_name || r.name || ''
          if (!rToolName) continue
          
          // 找到对应的 tc 更新状态
          for (const tc of pendingToolCalls) {
            if ((tc.name || tc.tool_name) === rToolName && !tc.result && !tc.error) {
              if (r.error) {
                tc.error = r.error
                tc.status = 'failed'
              } else {
                tc.result = r.result
                tc.status = 'success'
              }
              break // 每个 tc 只匹配一次
            }
          }
        }
        continue  // 跳过独立的 tool_result 消息
      }
      
      // 如果是 user 消息，先清空待处理的工具调用（理论上不会有）
      if (msg.role === 'user') {
        mergedMessages.push(msg)
        pendingToolCalls = []
        continue
      }
      
      // assistant 消息：合并之前收集的工具调用
      if (msg.role === 'assistant') {
        if (pendingToolCalls.length > 0) {
          msg.tool_calls = [...(msg.tool_calls || []), ...pendingToolCalls]
          msg._toolsCollapsed = false
          pendingToolCalls = []
        }
        // 如果这个 assistant 消息本身就有 tool_calls（历史数据），合并
        if (msg.tool_calls?.length && msg.content) {
          msg._toolsCollapsed = false
        }
        // 如果有 thinking 内容，设置 _thinkingMigrated 以便显示思考区块
        if (msg.thinking) {
          msg._thinkingMigrated = true
          msg._thinkingCollapsed = false
          msg._thinkingActive = false
          msg._thinkingDuration = null
        }
        // 初始化计划/技能相关字段（兼容历史消息）
        if (!msg.plan_steps) {
          msg.plan_steps = []
        }
        if (!Array.isArray(msg.skills_used)) {
          msg.skills_used = []
        }
        if (!msg._planCollapsed) {
          msg._planCollapsed = false
        }
        if (!msg._skillsCollapsed) {
          msg._skillsCollapsed = false
        }
      }
      
      mergedMessages.push(msg)
    }
    
    // 处理剩余的待处理工具调用（可能最后一条是 tool_result 没有对应的 assistant）
    if (pendingToolCalls.length > 0) {
      // 找到最后一条 assistant 消息
      for (let i = mergedMessages.length - 1; i >= 0; i--) {
        if (mergedMessages[i].role === 'assistant') {
          mergedMessages[i].tool_calls = [...(mergedMessages[i].tool_calls || []), ...pendingToolCalls]
          mergedMessages[i]._toolsCollapsed = false
          pendingToolCalls = []
          break
        }
      }
      // 如果没有找到 assistant 消息，创建一条
      if (pendingToolCalls.length > 0) {
        mergedMessages.push({
          role: 'assistant',
          content: '',
          tool_calls: pendingToolCalls,
          _toolsCollapsed: false,
          _toolLoading: false,
          _temp_id: 'merged_' + Date.now(),
          created_at: new Date().toISOString(),
        })
      }
    }
    
    messages.value = mergedMessages
    await nextTick()
    scrollToBottom()
  } catch (e) {
    message.error(humanizeError(e?.message || e || '加载历史消息失败'))
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (msgListRef.value) {
      msgListRef.value.scrollTop = msgListRef.value.scrollHeight
    }
  })
}

// ============ 智能体配置 ============
async function openAgentConfig() {
  const agentId = currentConv.value?.agent_id
  if (!agentId) {
    message.warning('当前会话未关联智能体')
    return
  }
  agentConfigVisible.value = true
  agentConfigLoading.value = true
  // 重置表单
  Object.assign(agentConfigForm, {
    id: undefined,
    name: '',
    description: '',
    status: '',
    llm_config_id: undefined,
    llm_config_name: '',
    system_prompt: '',
    temperature: 0.7,
    top_p: 1.0,
    max_tokens: 2048,
  })
  try {
    const detail = await agentApi.detail(agentId)
    Object.assign(agentConfigForm, {
      id: detail.id,
      name: detail.name || '',
      description: detail.description || '',
      status: detail.status || '',
      llm_config_id: detail.llm_config_id,
      llm_config_name: detail.llm_config_name || '',
      system_prompt: detail.system_prompt || '',
      temperature: detail.temperature ?? 0.7,
      top_p: detail.top_p ?? 1.0,
      max_tokens: detail.max_tokens ?? 2048,
    })
  } catch (e) {
    message.error(humanizeError(e?.message || e || '加载智能体配置失败'))
    agentConfigVisible.value = false
  } finally {
    agentConfigLoading.value = false
  }
}

async function handleSaveAgentConfig() {
  if (!agentConfigForm.id) {
    message.warning('智能体信息未加载完成')
    return
  }
  agentConfigSaving.value = true
  try {
    await agentApi.update(agentConfigForm.id, {
      system_prompt: agentConfigForm.system_prompt,
      temperature: agentConfigForm.temperature,
      top_p: agentConfigForm.top_p,
      max_tokens: agentConfigForm.max_tokens,
    })
    message.success('智能体配置已更新，后续对话将使用新参数')
    agentConfigVisible.value = false
    // 同步更新 currentConv 中的 agent_name（名称可能未变，但保持一致）
    if (currentConv.value && agentConfigForm.name) {
      currentConv.value.agent_name = agentConfigForm.name
    }
  } catch (e) {
    message.error(humanizeError(e?.message || e || '保存智能体配置失败'))
  } finally {
    agentConfigSaving.value = false
  }
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
    message.warning('请先选择一个 Agent，才能新建会话')
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
    message.success('会话已创建，现在可以向 Agent 提问了')
  } catch (e) {
    message.error(humanizeError(e?.message || e || '新建会话失败'))
  } finally {
    newConvSubmitting.value = false
  }
}

async function handleDeleteConv(conv) {
  try {
    await conversationApi.remove(conv.id)
    message.success('会话已删除')
    if (currentConvId.value === conv.id) {
      currentConvId.value = null
      currentConv.value = null
      messages.value = []
    }
    fetchConversations()
  } catch (e) {
    message.error(humanizeError(e?.message || e || '删除会话失败'))
  }
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
    thinking: '',
    thinkingIteration: undefined,
    _temp_id: Date.now() + '_a_' + Math.random(),
    _answerCollapsed: false,
    _thinkingActive: false,
    _thinkingCollapsed: false,
    _thinkingMigrated: false,
    _thinkingStartTime: null,
    _thinkingDuration: null,
    _answerSet: false,
    _toolsCollapsed: false,
    _skillsCollapsed: false,
    _planCollapsed: false,
    _is_error: false,
    tool_calls: [],
    skills_used: [],
    workflow_mode: '',
    workflow_description: '',
    plan_summary: '',
    plan_steps: [],
    plan_duration_ms: 0,
    created_at: new Date().toISOString(),
  })
  messages.value.push(assistantMsg)

  const handlers = {
    onMessage: (data) => {
      // ── 全局异常隔离：单事件出错绝不中断整个 SSE 流式连接 ──
      try {
        if (!data || typeof data !== 'object') return
        // 工作模式事件：显示当前对话使用的工作模式
        if (data.type === 'workflow_mode' || data.event === 'workflow_mode') {
          assistantMsg.workflow_mode = data.mode || data.workflow_mode || 'hybrid'
          assistantMsg.workflow_description = data.description || ''
          scrollToBottom()
          return
        }
        // 计划生成事件：Plan-and-Execute 模式下显示生成的计划
        if (data.type === 'plan_generated' || data.event === 'plan_generated') {
          assistantMsg.plan_summary = data.summary || ''
          // 初始化步骤状态
          const steps = (data.steps || []).map((step, i) => ({
            ...step,
            _status: i === 0 ? 'executing' : 'pending',
          }))
          assistantMsg.plan_steps = steps
          assistantMsg.plan_duration_ms = data.duration_ms || 0
          assistantMsg._planCollapsed = false
          scrollToBottom()
          return
        }
        // 思考开始事件
        if (data.type === 'thinking_start' || data.event === 'thinking_start') {
          assistantMsg._thinkingActive = true
          assistantMsg._thinkingCollapsed = false
          assistantMsg._thinkingStartTime = Date.now()
          assistantMsg._thinkingDuration = null
          if (!assistantMsg.thinking) {
            assistantMsg.thinking = ''
          }
          startThinkingTimer()
          scrollToBottom()
          return
        }
        // 思考过程事件（流式追加）
        if (data.type === 'thinking' || data.event === 'thinking') {
          appendThinkingMessage(data, assistantMsg)
          return
        }
        // 思考结束事件（带时长）→ 停止计时，但保持展开
        if (data.type === 'thinking_done' || data.event === 'thinking_done') {
          const durationMs = data.duration_ms || 0
          assistantMsg._thinkingActive = false
          // 多轮推理时累加思考时长
          assistantMsg._thinkingDuration = (assistantMsg._thinkingDuration || 0) + durationMs
          assistantMsg._thinkingStartTime = null
          stopThinkingTimer()
          scrollToBottom()
          return
        }
        // 思考转最终回答事件（最终轮）→ 分离思考和回答
        if (data.type === 'thinking_to_answer' || data.event === 'thinking_to_answer') {
          const durationMs = data.duration_ms || 0
          assistantMsg._thinkingActive = false
          assistantMsg._thinkingDuration = (assistantMsg._thinkingDuration || 0) + durationMs
          assistantMsg._thinkingStartTime = null
          assistantMsg._thinkingCollapsed = false
          assistantMsg._thinkingMigrated = true
          stopThinkingTimer()

          // 设置中间推理内容（如果有）
          if (data.thinking_content != null && data.thinking_content) {
            // 有中间推理：保留到思考区作为历史推理记录
            assistantMsg.thinking = data.thinking_content
          } else {
            // 无中间推理：清空思考区（最终回答已通过 message 事件在回答区展示）
            assistantMsg.thinking = ''
          }

          // 重置 _answerSet 确保后续 message 事件能正常追加
          assistantMsg._answerSet = false
          scrollToBottom()
          return
        }
        // Skills 可用事件：记录本次对话绑定的技能
        if (data.type === 'skills_available' || data.event === 'skills_available') {
          const skills = data.skills || []
          assistantMsg.skills_used = skills.map(s => ({
            name: s.name,
            description: s.description,
            category: s.category,
          }))
          scrollToBottom()
          return
        }
        // 工具调用事件
        if (data.type === 'tool_call' || data.event === 'tool_call') {
          appendToolCallMessage(data, assistantMsg)
          return
        }
        if (data.type === 'tool_result' || data.event === 'tool_result') {
          // 对 tool_result 的错误进行友好化，但要过滤掉无意义的"伪错误"
          const payload = { ...data }
          const rawError = payload.error ?? payload.error_message ?? ''
          const normalizedErr = String(rawError).trim().toLowerCase()
          const isRealError = rawError
            && !['', 'ok', 'success', 'true', '0', '200', 'none', 'null', 'undefined'].includes(normalizedErr)
            && normalizedErr !== '无'
          if (isRealError) {
            payload._raw_error = rawError
            payload.error = humanizeError(rawError)
          } else {
            payload.error = ''
            delete payload.error_message
          }
          const status = payload.status
          if (!isRealError && status && String(status).toLowerCase() === 'failed') {
            payload.error = '工具调用失败（服务未返回具体错误信息）'
          }
          appendToolResultMessage(payload)
          return
        }
        // 后端主动推送的错误消息（仅当回答区块尚无有效内容时才显示）
        if (data.role === 'error') {
          const hasValidAnswer = assistantMsg.content && assistantMsg.content.trim().length > 20
          if (hasValidAnswer) {
            message.warning(humanizeError(data.content || data.message || data.error || ''))
          } else {
            const rawMsg = data.content || data.message || data.error || ''
            assistantMsg.content = humanizeError(rawMsg)
            assistantMsg._is_error = true
            streamingText.value = assistantMsg.content
          }
          scrollToBottom()
          return
        }
        if (data.content) {
          // 追加回答内容到 content（回答区块）
          assistantMsg.content += data.content
          streamingText.value = assistantMsg.content
          scrollToBottom()
        }
      } catch (handlerErr) {
        // 单事件异常：打印到控制台，绝不向上抛（防止SSE ABORT 最终回答丢失）
        console.warn('[chat onMessage] 事件处理异常但已隔离:', handlerErr, 'event data=', data)
      }
    },
    onDone: (data) => {
      try {
        streaming.value = false
        streamingText.value = ''
        regenerating.value = false
        stopThinkingTimer()
        if (assistantMsg.thinking || assistantMsg._thinkingMigrated) {
          assistantMsg._thinkingActive = false
          assistantMsg._thinkingStartTime = null
        }
        if (data?.message_id) {
          assistantMsg.id = data.message_id
        }
        if (data?.aborted) {
          if (!assistantMsg.content) {
            assistantMsg.content = '⏹️ 生成已被你手动停止，当前内容仅保留已输出的部分。如需完整回答可点击「重试」或「重新生成」。'
            assistantMsg._is_error = true
          }
        } else if (data?.error) {
          const hasValidAnswer = assistantMsg.content && assistantMsg.content.trim().length > 20 && !assistantMsg._is_error
          if (hasValidAnswer) {
            message.warning(humanizeError(data.error))
          } else {
            assistantMsg.content = humanizeError(data.error)
            assistantMsg._is_error = true
          }
        } else if (!assistantMsg.content && !assistantMsg.message_type && !assistantMsg.tool_calls) {
          assistantMsg.content =
            '🤖 Agent 未返回任何文本内容。\n\n' +
            '可能原因：\n' +
            '1. 当前 Agent 未配置可用的 LLM 模型，或模型 API Key 已失效\n' +
            '2. Agent 绑定的工具调用耗时过长，尚未在本次请求内生成最终总结\n' +
            '3. 对话上下文过长超出模型限制\n\n' +
            '建议操作：点击下方「重试」，或前往 Agent 配置页检查 LLM 配置与绑定的 MCP 服务。'
          assistantMsg._is_error = true
        } else if (assistantMsg.content && assistantMsg.content.trim().length <= 8 && !assistantMsg.tool_calls) {
          const original = assistantMsg.content.trim()
          assistantMsg.content =
            `🤖 Agent 仅回复了「${original}」，回答内容过短，可能是模型未正确理解你的问题，或工具调用阶段出错导致最终总结未生成。\n\n` +
            '建议操作：点击「重试」或「重新生成」，或换一种更具体的问法再试一次。'
          assistantMsg._is_error = true
          assistantMsg._too_short = true
        }
        if (data?.fallback) {
          message.warning(data.fallback_message || '当前配置的 LLM 调用失败，已自动降级为系统默认模型参数，请在「模型配置」中检查 API Key')
        }
        abortController = null
        scrollToBottom()
      } catch (doneErr) {
        console.warn('[chat onDone] 异常隔离:', doneErr)
      }
    },
    onError: (err) => {
      try {
        streaming.value = false
        streamingText.value = ''
        regenerating.value = false
        stopThinkingTimer()
        if (assistantMsg.thinking) {
          assistantMsg._thinkingActive = false
          assistantMsg._thinkingStartTime = null
        }
        const friendly = humanizeError(err.message || err || '请求失败')
        if (!assistantMsg.content) {
          assistantMsg.content = `⚠️ 对话过程中出现异常：${friendly}`
          assistantMsg._is_error = true
        } else {
          message.error(`对话异常：${friendly}`)
        }
        abortController = null
        scrollToBottom()
      } catch (errErr) {
        console.warn('[chat onError] 异常隔离:', errErr)
      }
    },
  }

  abortController = isRegenerate
    ? chatApi.regenerate(payload, handlers)
    : chatApi.sendStream(payload, handlers)
}

// ============ 思考时长计时器 ============
const thinkingNow = ref(Date.now())
let thinkingTimerId = null

function startThinkingTimer() {
  stopThinkingTimer()
  thinkingTimerId = setInterval(() => {
    thinkingNow.value = Date.now()
  }, 100)
}

function stopThinkingTimer() {
  if (thinkingTimerId) {
    clearInterval(thinkingTimerId)
    thinkingTimerId = null
  }
}

// 工作模式格式化
function formatWorkflowMode(mode) {
  const map = {
    'react': '边思考边行动（ReAct）',
    'plan_and_execute': '先计划后执行（Plan-and-Execute）',
    'hybrid': '混合模式（自适应）',
  }
  return map[mode] || mode
}

// 格式化时长（毫秒 → 可读文本）
function formatDuration(ms) {
  if (!ms || ms < 0) return ''
  const seconds = ms / 1000
  if (seconds < 60) {
    return `${seconds.toFixed(1)}秒`
  }
  const minutes = Math.floor(seconds / 60)
  const remainSeconds = Math.floor(seconds % 60)
  return `${minutes}分${remainSeconds}秒`
}

// 实时计时（思考中）
function formatLiveDuration(startTime) {
  if (!startTime) return ''
  const elapsed = thinkingNow.value - startTime
  return formatDuration(elapsed)
}

function appendThinkingMessage(data, linkedAssistantMsg) {
  const content = data.content || data.thinking || ''
  if (!content) return
  const iteration = data.iteration ?? 0

  // 直接关联到当前正在流式生成的Agent消息
  if (linkedAssistantMsg) {
    // 如果内容已迁移为最终回答，不再追加到 thinking
    // 这是为了让思考过程和最终回答完全分离
    if (linkedAssistantMsg._thinkingMigrated) {
      return
    }
    // 支持多轮推理：累加思考内容
    if (linkedAssistantMsg.thinking) {
      // 如果迭代轮数变化，添加分隔标记
      if (linkedAssistantMsg.thinkingIteration !== undefined && linkedAssistantMsg.thinkingIteration !== iteration) {
        linkedAssistantMsg.thinking += `\n\n---\n\n**第 ${iteration + 1} 轮推理**\n\n${content}`
        linkedAssistantMsg.thinkingIteration = iteration
      } else {
        // 流式追加：直接拼接 chunk，不加额外换行
        linkedAssistantMsg.thinking += content
      }
    } else {
      // 第一轮不加前缀，直接显示思考内容（DeepSeek 风格）
      linkedAssistantMsg.thinking = content
      linkedAssistantMsg.thinkingIteration = iteration
    }
    linkedAssistantMsg._thinkingActive = true
    linkedAssistantMsg._thinkingCollapsed = false  // 流式过程中默认展开
    scrollToBottom()
    return
  }

  // 兜底：创建独立消息
  const msg = reactive({
    role: 'assistant',
    content: '',
    thinking: content,
    thinkingIteration: iteration,
    _thinkingActive: true,
    _thinkingCollapsed: false,
    _temp_id: Date.now() + '_th_' + Math.random(),
    created_at: new Date().toISOString(),
  })
  messages.value.push(msg)
  scrollToBottom()
}

function appendToolCallMessage(data, linkedAssistantMsg) {
  const toolCalls = data.tool_calls || [{
    name: data.name || data.tool_name,
    tool_name: data.tool_name || data.name,
    arguments: data.arguments || data.args || data.input || {},
  }]
  
  // 直接关联到当前正在流式生成的Agent消息
  if (linkedAssistantMsg) {
    if (!linkedAssistantMsg.tool_calls) {
      linkedAssistantMsg.tool_calls = []
    }
    linkedAssistantMsg.tool_calls.push(...toolCalls)
    linkedAssistantMsg._toolLoading = true
    linkedAssistantMsg._toolsCollapsed = false
    
    // 如果有计划步骤，更新步骤状态：标记当前执行的步骤为 executing，之前的步骤为 done
    if (linkedAssistantMsg.plan_steps?.length) {
      const steps = linkedAssistantMsg.plan_steps
      // 将所有 pending 步骤中第一个标记为 executing
      const pendingIdx = steps.findIndex(s => !s._status || s._status === 'pending')
      if (pendingIdx >= 0) {
        // 将之前的 executing 步骤标记为 done
        steps.forEach((s, i) => {
          if (i < pendingIdx) s._status = 'done'
        })
        steps[pendingIdx]._status = 'executing'
      }
    }
    
    scrollToBottom()
    return
  }
  
  // 兜底：如果没有关联消息，创建新的独立消息（历史消息兼容）
  const msg = reactive({
    role: 'assistant',
    content: '',
    tool_calls: toolCalls,
    _toolLoading: true,
    _toolsCollapsed: false,
    _temp_id: Date.now() + '_tc_' + Math.random(),
    created_at: new Date().toISOString(),
  })
  messages.value.push(msg)
  scrollToBottom()
}

function appendToolResultMessage(data) {
  const toolName = data.tool_name || data.name
  
  // 遍历找到最近一条有tool_calls且正在loading的Agent消息
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const m = messages.value[i]
    if (m.role === 'assistant' && m.tool_calls && m.tool_calls.length > 0) {
      const list = m.tool_calls
      let updated = false
      for (const tc of list) {
        if (!tc.result && !tc.error && (!toolName || (tc.name || tc.tool_name) === toolName)) {
          if (data.error) {
            tc.error = data.error
            tc.status = 'failed'
          } else {
            tc.result = data.result ?? data.content ?? data.output ?? ''
            tc.status = 'success'
          }
          updated = true
          // 检查是否所有工具调用都已完成
          const allDone = list.every(t => t.result || t.error)
          if (allDone) {
            m._toolLoading = false
            // 所有工具完成后，更新计划步骤状态
            if (m.plan_steps?.length) {
              const steps = m.plan_steps
              const execIdx = steps.findIndex(s => s._status === 'executing')
              if (execIdx >= 0) {
                steps[execIdx]._status = data.error ? 'pending' : 'done'
                // 如果有错误，保持该步骤为 pending（待重试）
                // 否则标记为 done，将下一步标记为 executing
                if (!data.error && execIdx + 1 < steps.length) {
                  // 不自动标记下一步为 executing，等待下一个 tool_call 事件
                }
              }
            }
          }
          break
        }
      }
      if (updated) {
        scrollToBottom()
        return
      }
    }
  }
  
  // 兜底：如果找不到对应的工具调用，创建独立消息
  const msg = reactive({
    role: 'assistant',
    content: '',
    tool_calls: [{
      name: data.tool_name || data.name,
      tool_name: data.tool_name || data.name,
      result: data.result ?? data.content ?? data.output ?? '',
      error: data.error,
      status: data.error ? 'failed' : 'success',
      arguments: {},
    }],
    _toolsCollapsed: false,
    _temp_id: Date.now() + '_tr_' + Math.random(),
    created_at: new Date().toISOString(),
  })
  messages.value.push(msg)
  scrollToBottom()
}

async function handleSend() {
  const content = inputText.value.trim()
  if ((!content && attachments.value.length === 0) || streaming.value) return

  const attPayload = attachments.value.map(a => ({
    type: a.type,
    mime: a.mime,
    name: a.name,
    data_url: a.data_url,
  }))

  const userMsg = {
    role: 'user',
    content,
    attachments: attPayload.length ? attPayload : null,
    _temp_id: Date.now() + '_u',
    created_at: new Date().toISOString(),
  }
  messages.value.push(userMsg)
  inputText.value = ''
  attachments.value = []
  await nextTick()
  scrollToBottom()

  startStream({
    payload: {
      conversation_id: currentConvId.value,
      content,
      attachments: attPayload,
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
      attachments: userMsg.attachments || [],
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
  stopThinkingTimer()
  // 关闭所有思考活跃状态和工具加载状态
  for (const m of messages.value) {
    if (m.message_type === 'tool_call') m._toolLoading = false
    if (m._thinkingActive) {
      m._thinkingActive = false
      m._thinkingStartTime = null
    }
  }
  message.info('已停止生成')
}

watch(currentConvId, () => {
  if (streaming.value && abortController) {
    abortController.abort()
    abortController = null
    streaming.value = false
  }
  stopThinkingTimer()
})

onMounted(async () => {
  await fetchConversations()
  fetchAgents()
  // 刷新后自动选中最近的会话，恢复对话上下文
  if (conversations.value.length > 0 && !currentConvId.value) {
    await selectConversation(conversations.value[0])
  }
})

onUnmounted(() => {
  stopThinkingTimer()
})
</script>

<style scoped>
.page-chat {
  display: flex;
  height: 100%;
  background: #f7f7f8;
  overflow: hidden;
}

/* 左侧会话列表 */
.conv-sidebar {
  width: 280px;
  flex-shrink: 0;
  background: #fff;
  border-right: 1px solid #ececec;
  display: flex;
  flex-direction: column;
}

.conv-sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid #f0f0f0;
}

.conv-sidebar-title {
  font-weight: 600;
  font-size: 14px;
  color: #1f1f1f;
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
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: 2px;
}

.conv-item:hover {
  background: #f5f5f5;
}

.conv-item.active {
  background: #f0f5ff;
  color: #1677ff;
}

.conv-item.active .conv-item-text {
  color: #1677ff;
  font-weight: 500;
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
  color: #1f1f1f;
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
  background: #f7f7f8;
  position: relative;
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  border-bottom: 1px solid #ececec;
  background: #fff;
}

.chat-header-title {
  font-weight: 600;
  color: #1f1f1f;
}

.msg-list {
  flex: 1;
  overflow: auto;
  padding: 24px 24px 80px;
  background: transparent;
  scroll-behavior: smooth;
}

.msg-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.msg-row {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
  max-width: 860px;
  margin-left: auto;
  margin-right: auto;
}

.msg-row.user {
  flex-direction: row-reverse;
}

.msg-avatar {
  flex-shrink: 0;
}

/* 头像样式 - 渐变圆形 */
.avatar-circle {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 18px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.avatar-user {
  background: linear-gradient(135deg, #1677ff 0%, #0958d9 100%);
}

.avatar-agent {
  background: linear-gradient(135deg, #722ed1 0%, #531dab 100%);
}

.msg-content-col {
  max-width: 78%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.msg-row.user .msg-content-col { align-items: flex-end; }

/* 发送者名称 */
.msg-sender {
  padding: 0 4px;
  line-height: 1.4;
}
.sender-name {
  font-size: 13px;
  font-weight: 600;
  color: #595959;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.sender-user { color: #1677ff; }
.sender-agent { color: #722ed1; }
.sender-icon { font-size: 12px; }

/* 智能体配置标签可点击 */
.agent-config-tag {
  cursor: pointer;
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
}
.agent-config-tag:hover {
  opacity: 0.85;
  transform: translateY(-1px);
}
.agent-config-icon {
  margin-left: 4px;
  font-size: 11px;
}

/* 智能体配置弹窗 */
.agent-config-desc { margin-bottom: 4px; }
.agent-config-tip {
  margin-top: 8px;
  padding: 8px 12px;
  background: #f6f8fa;
  border-radius: 6px;
  font-size: 12px;
  color: #8c8c8c;
  display: flex;
  align-items: center;
  gap: 6px;
}

/* 用户消息气泡 */
.msg-bubble.user-bubble {
  padding: 12px 16px;
  border-radius: 16px 16px 4px 16px;
  background: #e6f4ff;
  color: #1f1f1f;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  max-width: 100%;
  word-break: break-word;
}

/* Agent内容区域 - 不使用气泡，直接展示内容（DeepSeek风格） */
.assistant-content {
  width: 100%;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.assistant-content.is-error .assistant-text {
  background: #fff1f0;
  border: 1px solid #ffa39e;
  border-radius: 12px;
  padding: 12px 16px;
}

.assistant-content.is-error .assistant-text .is-error-content {
  color: #cf1322;
}

/* 工作模式提示区块 */
.workflow-mode-block {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  background: #f0f5ff;
  border: 1px solid #d6e4ff;
  border-radius: 16px;
  font-size: 12px;
  line-height: 1.5;
  width: fit-content;
}

.workflow-mode-value {
  font-weight: 600;
  color: #1890ff;
}

.workflow-mode-value.mode-react {
  color: #1890ff;
}

.workflow-mode-value.mode-plan_and_execute {
  color: #722ed1;
}

.workflow-mode-value.mode-hybrid {
  color: #13c2c2;
}

/* 计划卡片容器 */
.plan-container {
  border: 1px solid #e6f4ff;
  border-radius: 12px;
  background: linear-gradient(180deg, #f0f9ff 0%, #ffffff 40px);
  overflow: hidden;
  transition: all 0.2s ease;
  margin-top: 8px;
}

.plan-container.collapsed {
  background: #fafafa;
}

.plan-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s ease;
}

.plan-header:hover {
  background: #f5f5f5;
}

.plan-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.plan-icon-wrap {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #722ed1;
  border-radius: 6px;
  color: #fff;
  font-size: 12px;
}

.plan-header-title {
  font-size: 13px;
  font-weight: 500;
  color: #262626;
}

.plan-steps-count {
  font-size: 12px;
  color: #8c8c8c;
  margin-left: 4px;
}

.plan-duration {
  font-size: 12px;
  color: #8c8c8c;
  margin-left: 8px;
}

.plan-toggle {
  font-size: 12px;
  color: #8c8c8c;
  transition: transform 0.3s ease;
}

.plan-toggle.rotated {
  transform: rotate(-90deg);
}

.plan-content {
  padding: 4px 16px 12px;
}

.plan-summary {
  font-size: 12px;
  color: #595959;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: #f9f9f9;
  border-radius: 6px;
  line-height: 1.6;
}

.plan-steps {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.plan-step {
  display: flex;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  transition: background 0.2s ease;
}

.plan-step.is-executing {
  background: #e6f7ff;
}

.plan-step.is-completed {
  opacity: 0.7;
}

.step-indicator {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.step-icon {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 600;
}

.step-icon.step-pending {
  background: #f0f0f0;
  color: #8c8c8c;
  font-size: 11px;
}

.step-icon.step-executing {
  background: #1890ff;
  color: #fff;
  animation: spin 1s linear infinite;
}

.step-icon.step-done {
  color: #52c41a;
  font-size: 18px;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.step-body {
  flex: 1;
  min-width: 0;
}

.step-title {
  font-size: 13px;
  font-weight: 500;
  color: #262626;
  line-height: 1.5;
}

.step-desc {
  font-size: 12px;
  color: #595959;
  margin-top: 2px;
  line-height: 1.5;
}

.step-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}

.step-tool-tag {
  display: inline-block;
  font-size: 11px;
  padding: 1px 8px;
  background: #f5f5f5;
  border: 1px solid #e8e8e8;
  border-radius: 10px;
  color: #595959;
}

.step-tool-more {
  font-size: 11px;
  color: #8c8c8c;
}

/* 思考过程区块 */
.thinking-block {
  border: 1px solid #e8e8e8;
  border-radius: 12px;
  background: #fafafa;
  overflow: hidden;
  transition: all 0.3s ease;
}

.thinking-block.active {
  border-color: #d9b3ff;
  background: linear-gradient(135deg, #faf5ff 0%, #f9f9f9 100%);
}

.thinking-block.collapsed {
  background: #f5f5f5;
}

.thinking-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  cursor: pointer;
  transition: background 0.2s;
  user-select: none;
}

.thinking-header:hover {
  background: rgba(0, 0, 0, 0.02);
}

.thinking-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.thinking-icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #f0f0f0;
  color: #8c8c8c;
  transition: all 0.3s;
}

.thinking-icon-wrap.is-thinking {
  background: linear-gradient(135deg, #722ed1 0%, #531dab 100%);
  color: #fff;
  animation: thinking-pulse 1.5s ease-in-out infinite;
}

@keyframes thinking-pulse {
  0%, 100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(114, 46, 209, 0.4); }
  50% { transform: scale(1.05); box-shadow: 0 0 0 6px rgba(114, 46, 209, 0); }
}

.thinking-icon {
  font-size: 12px;
}

.thinking-label {
  font-size: 13px;
  font-weight: 600;
  color: #595959;
}

.thinking-block.active .thinking-label {
  color: #722ed1;
}

.thinking-spinner {
  margin-left: 4px;
}

.thinking-duration {
  font-size: 12px;
  color: #8c8c8c;
  font-weight: 400;
  margin-left: 2px;
}

.thinking-duration-live {
  color: #722ed1;
  font-variant-numeric: tabular-nums;
}

.thinking-iteration {
  font-size: 11px;
  color: #bfbfbf;
  background: #f0f0f0;
  padding: 1px 6px;
  border-radius: 8px;
}

.thinking-toggle {
  font-size: 12px;
  color: #8c8c8c;
  transition: transform 0.3s ease;
}

.thinking-toggle.rotated {
  transform: rotate(-90deg);
}

.thinking-content {
  padding: 12px 16px 16px;
  font-size: 13px;
  color: #595959;
  line-height: 1.7;
  border-top: 1px solid #f0f0f0;
  background: #fff;
}

/* 思考过程中的流式光标 */
.thinking-cursor {
  background: #722ed1;
  height: 14px;
  width: 7px;
  vertical-align: text-bottom;
  margin-left: 2px;
}

/* 技能使用卡片样式 */
.skills-container {
  border: 1px solid #e8f4e8;
  border-radius: 12px;
  background: linear-gradient(180deg, #f0fff4 0%, #ffffff 40px);
  overflow: hidden;
  transition: all 0.2s ease;
  margin-top: 8px;
}

.skills-container.collapsed {
  background: #fafafa;
}

.skills-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  cursor: pointer;
  transition: background 0.2s;
  user-select: none;
}

.skills-header:hover {
  background: #f5fff5;
}

.skills-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.skills-icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: linear-gradient(135deg, #52c41a 0%, #389e0d 100%);
  color: #fff;
  font-size: 12px;
}

.skills-header-title {
  font-size: 13px;
  font-weight: 600;
  color: #389e0d;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.skills-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: #e8f8e8;
  color: #389e0d;
  font-size: 11px;
  font-weight: 600;
}

.skills-toggle {
  font-size: 12px;
  color: #8c8c8c;
  transition: transform 0.2s ease;
}

.skills-toggle.rotated {
  transform: rotate(-90deg);
}

.skills-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid #f0f0f0;
}

.skill-item {
  border: 1px solid #d9f7d9;
  border-radius: 8px;
  background: #f6ffed;
  padding: 10px 12px;
}

.skill-info {
  font-size: 13px;
  color: #389e0d;
}

.skill-name {
  font-weight: 600;
}

.skill-category {
  color: #8c8c8c;
  font-size: 12px;
}

.skill-desc {
  color: #595959;
  font-size: 12px;
}

/* 最终回答区块样式 */
.answer-block {
  border: 1px solid #d9e8ff;
  border-radius: 12px;
  background: linear-gradient(180deg, #f0f5ff 0%, #ffffff 40px);
  overflow: hidden;
  transition: all 0.2s ease;
  margin-top: 8px;
}

.answer-block.collapsed {
  background: #fff;
}

.answer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s ease;
}

.answer-header:hover {
  background: #f5f5f5;
}

.answer-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.answer-icon-wrap {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #1677ff;
  border-radius: 6px;
  color: #fff;
}

.answer-icon {
  font-size: 13px;
}

.answer-label {
  font-size: 13px;
  font-weight: 500;
  color: #262626;
}

.answer-toggle {
  font-size: 12px;
  color: #8c8c8c;
  transition: transform 0.3s ease;
}

.answer-toggle.rotated {
  transform: rotate(-90deg);
}

.answer-content {
  padding: 8px 16px 16px;
}

/* 工具调用容器 */
.tool-calls-container {
  border: 1px solid #e8e8e8;
  border-radius: 12px;
  background: #fff;
  overflow: hidden;
  transition: all 0.2s ease;
}

.tool-calls-container.collapsed {
  background: #fafafa;
}

.tool-calls-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  cursor: pointer;
  transition: background 0.2s;
  user-select: none;
}

.tool-calls-header:hover {
  background: #f5f5f5;
}

.tool-calls-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tool-calls-icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #f0f0f0;
  color: #8c8c8c;
  transition: all 0.3s;
  font-size: 12px;
}

.tool-calls-icon-wrap.is-loading {
  background: linear-gradient(135deg, #faad14 0%, #d48806 100%);
  color: #fff;
}

.tool-calls-header-title {
  font-size: 13px;
  font-weight: 600;
  color: #595959;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.tool-calls-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: #f0f0f0;
  color: #595959;
  font-size: 11px;
  font-weight: 600;
}

.tool-calls-spinner {
  margin-left: 4px;
}

.tools-toggle {
  font-size: 12px;
  color: #8c8c8c;
  transition: transform 0.2s ease;
}

.tools-toggle.rotated {
  transform: rotate(-90deg);
}

/* 工具调用列表 */
.tool-call-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid #f0f0f0;
}

.tool-call-item {
  border: 1px solid #ececec;
  border-radius: 8px;
  background: #fafafa;
  overflow: hidden;
  transition: all 0.2s ease;
}

.tool-call-item.loading {
  background: #fffbf0;
  border-color: #ffe58f;
}

.tool-call-item.has-result {
  background: #f6ffed;
  border-color: #d9f7be;
}

.tool-call-item.has-error {
  background: #fff2f0;
  border-color: #ffccc7;
}

.tool-call-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.6);
  border-bottom: 1px solid #f0f0f0;
}

.tool-call-name-wrap {
  display: inline-flex;
  align-items: center;
  gap: 6px;
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

.tool-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 500;
}

.tool-status.status-success {
  color: #389e0d;
}

.tool-status.status-error {
  color: #cf1322;
}

.tool-status.status-loading {
  color: #faad14;
}

.tool-call-body {
  padding: 8px 12px;
}

.tool-call-section {
  margin-bottom: 8px;
}

.tool-call-section:last-child {
  margin-bottom: 0;
}

.section-label {
  font-size: 11px;
  color: #8c8c8c;
  margin-bottom: 4px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.section-label.error-label {
  color: #cf1322;
}

/* Agent回复文本 */
.assistant-text {
  font-size: 14px;
  line-height: 1.75;
  color: #1f1f1f;
  word-break: break-word;
  position: relative;
}

/* 流式输出光标 */
.streaming-cursor {
  display: inline-block;
  width: 8px;
  height: 16px;
  background: #722ed1;
  margin-left: 2px;
  vertical-align: text-bottom;
  animation: cursor-blink 1s infinite;
  border-radius: 1px;
}

@keyframes cursor-blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

/* 用户消息容器 */
.user-message-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

/* 用户消息底部操作按钮（右侧对齐，hover显示） */
.user-msg-footer {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
  font-size: 12px;
  color: #bfbfbf;
  opacity: 0;
  transition: opacity 0.2s;
}

.msg-row:hover .user-msg-footer {
  opacity: 1;
}

/* 消息底部操作 */
.msg-footer {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
  font-size: 12px;
  color: #bfbfbf;
  opacity: 0;
  transition: opacity 0.2s;
}

.msg-row:hover .msg-footer {
  opacity: 1;
}

.msg-time {
  font-size: 11px;
  color: #bfbfbf;
  margin-right: 8px;
}

.msg-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border: none;
  background: transparent;
  color: #8c8c8c;
  font-size: 12px;
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.2s;
}

.msg-action-btn:hover {
  background: #f0f0f0;
  color: #595959;
}

/* 打字动画 */
.msg-typing {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #8c8c8c;
  font-size: 13px;
  padding: 4px 0;
}

.typing-dots {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.typing-dots .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #722ed1;
  animation: typing-dot 1.4s infinite ease-in-out;
}

.typing-dots .dot:nth-child(1) { animation-delay: -0.32s; }
.typing-dots .dot:nth-child(2) { animation-delay: -0.16s; }

@keyframes typing-dot {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

.msg-typing-text {
  font-size: 13px;
  color: #8c8c8c;
}

/* 内联加载指示器（在 assistant 消息块内部显示，不产生第二个头像） */
.inline-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 0;
  margin-top: 4px;
}

.inline-loading .typing-dots .dot {
  background: #1890ff;
}

.inline-loading-text {
  font-size: 13px;
  color: #8c8c8c;
}

/* 独立加载指示器（已有消息时不显示） */
.loading-indicator {
  opacity: 0.9;
}

/* 重新生成浮动条 */
.msg-action-bar {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  bottom: 120px;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(8px);
  padding: 6px 12px;
  border-radius: 20px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  z-index: 10;
  border: 1px solid #ececec;
}

/* 旧的工具卡片样式保留（兼容） */
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

.tool-call-title,
.tool-result-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 13px;
  color: #4338ca;
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
  padding: 12px 24px 20px;
  background: #fff;
  border-top: 1px solid #ececec;
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

/* 搜索高亮 - 关键词高亮样式 */
.search-highlight {
  position: relative;
}

.search-highlight-keyword {
  background-color: #fff3cd;
  color: #856404;
  padding: 1px 3px;
  border-radius: 3px;
  font-weight: 600;
  box-shadow: 0 0 0 1px rgba(255, 193, 7, 0.3);
  transition: background-color 0.2s ease;
}

.search-highlight-keyword:hover {
  background-color: #ffe69c;
}

.search-flash {
  animation: search-flash 1.5s ease-out;
}

@keyframes search-flash {
  0% { background: rgba(22, 119, 255, 0.15); }
  100% { background: transparent; }
}

/* 思考空状态 */
.thinking-empty {
  padding: 8px 12px;
  background: rgba(139, 92, 246, 0.08);
  border-radius: 6px;
  border: 1px dashed rgba(139, 92, 246, 0.3);
}

.thinking-empty-text {
  color: #8b5cf6;
  font-size: 13px;
  font-style: italic;
}

/* 自定义滚动条 */
.msg-list::-webkit-scrollbar {
  width: 6px;
}

.msg-list::-webkit-scrollbar-track {
  background: transparent;
}

.msg-list::-webkit-scrollbar-thumb {
  background: #d9d9d9;
  border-radius: 3px;
}

.msg-list::-webkit-scrollbar-thumb:hover {
  background: #bfbfbf;
}

.conv-list::-webkit-scrollbar {
  width: 6px;
}

.conv-list::-webkit-scrollbar-track {
  background: transparent;
}

.conv-list::-webkit-scrollbar-thumb {
  background: #e8e8e8;
  border-radius: 3px;
}

.conv-list::-webkit-scrollbar-thumb:hover {
  background: #d9d9d9;
}

/* 附件工具栏 / 预览条 */
.chat-input-toolbar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 2px;
}
.attachment-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 2px 2px 0;
}
.attachment-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px 6px 6px;
  border: 1px solid #e8e8e8;
  border-radius: 10px;
  background: #fafafa;
  max-width: 280px;
}
.att-thumb {
  width: 40px;
  height: 40px;
  object-fit: cover;
  border-radius: 6px;
  flex-shrink: 0;
}
.att-audio-icon {
  width: 40px;
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #f0f5ff;
  border-radius: 6px;
  font-size: 20px;
  flex-shrink: 0;
}
.att-meta {
  min-width: 0;
  flex: 1;
  overflow: hidden;
}
.att-name {
  font-size: 12px;
  color: #1f1f1f;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.att-size {
  font-size: 11px;
  color: #8c8c8c;
}

/* 用户消息中附件展示 */
.user-attachments {
  display: flex;
  flex-wrap: wrap;
  max-width: 100%;
  margin-top: 6px;
  justify-content: flex-end;
}
.audio-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: #fff7e6;
  border: 1px solid #ffd591;
  border-radius: 8px;
}
.audio-chip audio {
  height: 32px;
}
.audio-name {
  font-size: 12px;
  color: #d46b08;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
