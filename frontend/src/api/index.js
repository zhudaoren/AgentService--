import axios from 'axios'
import { message } from 'ant-design-vue'

// 通过 Vite 代理：/api -> http://localhost:8000/api/v1
const request = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
request.interceptors.request.use(
  (config) => {
    // 可在此处注入 token
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器：统一处理返回结构 { code, message, data } 或裸数据
request.interceptors.response.use(
  (response) => {
    const res = response.data
    // 如果是分页或裸数据结构，直接返回
    if (res && typeof res === 'object' && 'code' in res) {
      if (res.code !== 0 && res.code !== 200) {
        const msg = res.message || res.msg || '请求失败'
        message.error(msg)
        return Promise.reject(new Error(msg))
      }
      return res.data !== undefined ? res.data : res
    }
    return res
  },
  (error) => {
    let msg = '请求失败'
    if (error.response) {
      const data = error.response.data
      if (typeof data?.message === 'string') {
        msg = data.message
      } else if (typeof data?.detail === 'string') {
        msg = data.detail
      } else if (Array.isArray(data?.detail)) {
        msg = data.detail.map(d => (typeof d === 'string' ? d : d?.msg || d?.message || JSON.stringify(d))).join('; ')
      } else if (typeof data?.detail === 'object' && data?.detail !== null) {
        msg = data.detail.msg || data.detail.message || JSON.stringify(data.detail)
      } else if (typeof data?.error === 'string') {
        msg = data.error
      } else {
        msg = `请求错误 (${error.response.status})`
      }
    } else if (error.request) {
      msg = '服务器无响应，请检查网络或后端服务'
    } else {
      msg = error.message
    }
    message.error(msg)
    return Promise.reject(error)
  }
)

// ============ LLM 配置 ============
export const llmConfigApi = {
  list: (params) => request.get('/llm-configs', { params }),
  detail: (id) => request.get(`/llm-configs/${id}`),
  create: (data) => request.post('/llm-configs', data),
  update: (id, data) => request.put(`/llm-configs/${id}`, data),
  remove: (id) => request.delete(`/llm-configs/${id}`),
  test: (id) => request.post(`/llm-configs/${id}/test`),
  getProviderParams: () => request.get('/llm-configs/providers/params'),
}

// ============ Agent ============
export const agentApi = {
  list: (params) => request.get('/agents', { params }),
  detail: (id) => request.get(`/agents/${id}`),
  create: (data) => request.post('/agents', data),
  update: (id, data) => request.put(`/agents/${id}`, data),
  remove: (id) => request.delete(`/agents/${id}`),
  status: (id, action) => request.post(`/agents/${id}/status`, { action }),
  clone: (id) => request.post(`/agents/${id}/clone`),
  official: (params) => request.get('/agents/official/list', { params }),
  polishPrompt: (raw_prompt) => request.post('/agents/polish-prompt', { raw_prompt }),
  polishMcpDescription: (raw_description, mode = '') =>
    request.post('/agents/polish-mcp-description', { raw_description, mode }),
}

// ============ 会话 ============
export const conversationApi = {
  create: (data) => request.post('/conversations', data),
  list: (params) => request.get('/conversations', { params }),
  detail: (id) => request.get(`/conversations/${id}`),
  remove: (id) => request.delete(`/conversations/${id}`),
  messages: (id, params) => request.get(`/conversations/${id}/messages`, { params }),
}

// ============ 对话（SSE 流式） ============
// 使用 fetch + ReadableStream 处理 POST 流式响应
export const chatApi = {
  /**
   * 发送消息（流式）
   * @param {Object} payload { conversation_id, content, stream }
   * @param {Object} handlers { onMessage(data), onDone(data), onError(err) }
   * @returns {AbortController} 用于中断请求
   */
  sendStream(payload, handlers = {}) {
    const controller = new AbortController()
    const { onMessage, onDone, onError } = handlers

    ;(async () => {
      try {
        const response = await fetch('/api/chat', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ ...payload, stream: true }),
          signal: controller.signal,
        })

        if (!response.ok) {
          let errMsg = `HTTP ${response.status}`
          try {
            const body = await response.text()
            const parsed = JSON.parse(body)
            errMsg = parsed.detail || parsed.message || parsed.error || body
          } catch (_) {
            // use default message
          }
          throw new Error(errMsg)
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder('utf-8')
        let buffer = ''
        let streamError = null
        let currentEvent = ''
        let eventDataLines = []

        const flushEvent = () => {
          if (eventDataLines.length === 0) return
          const jsonStr = eventDataLines.join('\n')
          eventDataLines = []
          try {
            if (jsonStr === '[DONE]') {
              onDone && onDone({ error: streamError })
              return
            }
            const data = JSON.parse(jsonStr)
            // 将 SSE event 类型注入 data，供上层 handler 识别
            if (typeof data === 'object' && data !== null) {
              data._event = currentEvent
              // 兼容：同时设置 type 字段，便于上层判断
              if (!data.type) data.type = currentEvent
            }
            if (currentEvent === 'done') {
              onDone && onDone({ ...data, error: streamError })
              return
            }
            if (data.error) {
              streamError = data.error
              onMessage && onMessage(data)
              return
            }
            if (data.done) {
              onDone && onDone({ ...data, error: streamError })
              return
            }
            onMessage && onMessage(data)
          } catch (e) {
            // ignore parse errors
          }
          currentEvent = ''
        }

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop()
          for (const line of lines) {
            const trimmed = line.trim()
            if (!trimmed) {
              flushEvent()
              continue
            }
            if (trimmed.startsWith('event:')) {
              currentEvent = trimmed.replace(/^event:\s*/, '')
              continue
            }
            if (trimmed.startsWith('data:')) {
              eventDataLines.push(trimmed.replace(/^data:\s*/, ''))
            }
          }
        }
        // Process remaining buffer content
        if (buffer.trim()) {
          const trimmed = buffer.trim()
          if (trimmed.startsWith('event:')) {
            currentEvent = trimmed.replace(/^event:\s*/, '')
          } else if (trimmed.startsWith('data:')) {
            eventDataLines.push(trimmed.replace(/^data:\s*/, ''))
          }
        }
        flushEvent()
        if (eventDataLines.length > 0) {
          const jsonStr = eventDataLines.join('\n')
          try {
            const data = JSON.parse(jsonStr)
            if (currentEvent === 'done' || data.done) {
              onDone && onDone({ ...data, error: streamError })
            } else {
              onMessage && onMessage(data)
            }
          } catch (e) {
            onDone && onDone({ error: streamError })
          }
        } else {
          onDone && onDone({ error: streamError })
        }
      } catch (err) {
        if (err.name === 'AbortError') {
          onDone && onDone({ aborted: true })
          return
        }
        onError && onError(err)
      }
    })()

    return controller
  },

  stop: (conversationId) => request.post('/chat/stop', { conversation_id: conversationId }),
}

// ============ 记忆 ============
export const memoryApi = {
  longTerm: (agentId) => request.get(`/memory/agents/${agentId}/long-term`),
  updateLongTerm: (agentId, data) => request.put(`/memory/agents/${agentId}/long-term`, data),
  summary: (agentId) => request.get(`/memory/agents/${agentId}/long-term/summary`),
  shortTerm: (agentId, conversationId) =>
    request.get(`/memory/agents/${agentId}/short-term/${conversationId}`),
}

// ============ MCP 服务 ============
export const mcpApi = {
  list: (params) => request.get('/mcp-services', { params }),
  create: (data) => request.post('/mcp-services', data),
  detail: (id) => request.get(`/mcp-services/${encodeURIComponent(id)}`),
  update: (id, data) => request.put(`/mcp-services/${encodeURIComponent(id)}`, data),
  remove: (id) => request.delete(`/mcp-services/${encodeURIComponent(id)}`),
  connect: (id) => request.post(`/mcp-services/${encodeURIComponent(id)}/connect`),
  disconnect: (id) => request.post(`/mcp-services/${encodeURIComponent(id)}/disconnect`),
  discover: (id) => request.post(`/mcp-services/${encodeURIComponent(id)}/discover`),
  listTools: (id, params) => request.get(`/mcp-services/${encodeURIComponent(id)}/tools`, { params }),
  toggleTool: (id, toolName, enabled) =>
    request.post(
      `/mcp-services/${encodeURIComponent(id)}/tools/${encodeURIComponent(toolName)}/toggle`,
      { enabled }
    ),
  // OAuth 2.1 接口
  oauthDiscover: (id) => request.post(`/mcp-services/${encodeURIComponent(id)}/oauth/discover`),
  oauthConfig: (id, data) => request.post(`/mcp-services/${encodeURIComponent(id)}/oauth/config`, data),
  oauthAuthorize: (id, data) => request.post(`/mcp-services/${encodeURIComponent(id)}/oauth/authorize`, data),
  oauthRefresh: (id) => request.post(`/mcp-services/${encodeURIComponent(id)}/oauth/refresh`),
  oauthRevoke: (id) => request.post(`/mcp-services/${encodeURIComponent(id)}/oauth/revoke`),
  oauthStatus: (id) => request.get(`/mcp-services/${encodeURIComponent(id)}/oauth/status`),
}

// ============ 工具调用 ============
export const toolApi = {
  call: (data) => request.post('/tools/call', data),
  callLogs: (params) => request.get('/tool-call-logs', { params }),
}

// ============ Skill 管理 ============
export const skillApi = {
  list: (params) => request.get('/skills', { params }),
  create: (data) => request.post('/skills', data),
  detail: (id) => request.get(`/skills/${encodeURIComponent(id)}`),
  update: (id, data) => request.put(`/skills/${encodeURIComponent(id)}`, data),
  remove: (id) => request.delete(`/skills/${encodeURIComponent(id)}`),
  toggle: (id, enabled) =>
    request.post(`/skills/${encodeURIComponent(id)}/toggle`, { enabled }),
  levels: (id) => request.get(`/skills/${encodeURIComponent(id)}/levels`),
  importLocal: (formData) =>
    request.post('/skills/import/local', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  importOnline: (opts = {}) =>
    request.post('/skills/import/online', {
      source_url: opts.source_url,
      import_format: opts.import_format || 'markdown',
      category: opts.category || 'general',
    }),
  progressive: (id, level) =>
    request.get(`/skills/${encodeURIComponent(id)}/progressive`, { params: { level } }),
}

// ============ Agent 绑定 ============
export const agentBindingApi = {
  getMCPBindings: (agentId) =>
    request.get(`/agents/${encodeURIComponent(agentId)}/mcp-bindings`),
  bindMCP: (agentId, data) =>
    request.post(`/agents/${encodeURIComponent(agentId)}/mcp-bindings`, data),
  unbindMCP: (agentId, mcpServiceId) =>
    request.delete(
      `/agents/${encodeURIComponent(agentId)}/mcp-bindings/${encodeURIComponent(mcpServiceId)}`
    ),
  getSkillBindings: (agentId) =>
    request.get(`/agents/${encodeURIComponent(agentId)}/skill-bindings`),
  bindSkill: (agentId, data) =>
    request.post(`/agents/${encodeURIComponent(agentId)}/skill-bindings`, data),
  unbindSkill: (agentId, skillId) =>
    request.delete(
      `/agents/${encodeURIComponent(agentId)}/skill-bindings/${encodeURIComponent(skillId)}`
    ),
  getToolsSummary: (agentId) =>
    request.get(`/agents/${encodeURIComponent(agentId)}/tools-summary`),
}

// chatApi 补充 regenerate 方法
chatApi.regenerate = (payload, handlers = {}) => {
  const controller = new AbortController()
  const { onMessage, onDone, onError } = handlers

  ;(async () => {
    try {
      const response = await fetch('/api/chat/regenerate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ ...payload, stream: true }),
        signal: controller.signal,
      })

      if (!response.ok) {
        let errMsg = `HTTP ${response.status}`
        try {
          const body = await response.text()
          const parsed = JSON.parse(body)
          errMsg = parsed.detail || parsed.message || parsed.error || body
        } catch (_) {}
        throw new Error(errMsg)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''
      let streamError = null
      let currentEvent = ''
      let eventDataLines = []

      const flushEvent = () => {
        if (eventDataLines.length === 0) return
        const jsonStr = eventDataLines.join('\n')
        eventDataLines = []
        try {
          if (jsonStr === '[DONE]') {
            onDone && onDone({ error: streamError })
            return
          }
          const data = JSON.parse(jsonStr)
          // 将 SSE event 类型注入 data，供上层 handler 识别（与 sendStream 保持一致）
          if (typeof data === 'object' && data !== null) {
            data._event = currentEvent
            // 兼容：同时设置 type 字段，便于上层判断
            if (!data.type) data.type = currentEvent
          }
          if (currentEvent === 'done') {
            onDone && onDone({ ...data, error: streamError })
            return
          }
          if (data.error) {
            streamError = data.error
            onMessage && onMessage(data)
            return
          }
          if (data.done) {
            onDone && onDone({ ...data, error: streamError })
            return
          }
          onMessage && onMessage(data)
        } catch (e) {
          // ignore parse errors
        }
        currentEvent = ''
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()
        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) {
            flushEvent()
            continue
          }
          if (trimmed.startsWith('event:')) {
            currentEvent = trimmed.replace(/^event:\s*/, '')
            continue
          }
          if (trimmed.startsWith('data:')) {
            eventDataLines.push(trimmed.replace(/^data:\s*/, ''))
          }
        }
      }
      // Process remaining buffer content
      if (buffer.trim()) {
        const trimmed = buffer.trim()
        if (trimmed.startsWith('event:')) {
          currentEvent = trimmed.replace(/^event:\s*/, '')
        } else if (trimmed.startsWith('data:')) {
          eventDataLines.push(trimmed.replace(/^data:\s*/, ''))
        }
      }
      flushEvent()
      if (eventDataLines.length > 0) {
        const jsonStr = eventDataLines.join('\n')
        try {
          const data = JSON.parse(jsonStr)
          if (currentEvent === 'done' || data.done) {
            onDone && onDone({ ...data, error: streamError })
          } else {
            onMessage && onMessage(data)
          }
        } catch (e) {
          onDone && onDone({ error: streamError })
        }
      } else {
        onDone && onDone({ error: streamError })
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        onDone && onDone({ aborted: true })
        return
      }
      onError && onError(err)
    }
  })()

  return controller
}

export default request
