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
      msg = data?.message || data?.detail || data?.error || `请求错误 (${error.response.status})`
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
}

// ============ 会话 ============
export const conversationApi = {
  create: (data) => request.post('/conversations', data),
  list: (params) => request.get('/conversations', { params }),
  detail: (id) => request.get(`/conversations/${id}`),
  remove: (id) => request.delete(`/conversations/${id}`),
  messages: (id) => request.get(`/conversations/${id}/messages`),
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
          throw new Error(`HTTP ${response.status}`)
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder('utf-8')
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          // SSE 以 \n\n 分隔事件，按行处理
          const parts = buffer.split('\n')
          buffer = parts.pop() // 保留最后不完整的行
          for (const line of parts) {
            const trimmed = line.trim()
            if (!trimmed || !trimmed.startsWith('data:')) continue
            const jsonStr = trimmed.replace(/^data:\s*/, '')
            if (jsonStr === '[DONE]') {
              onDone && onDone({})
              return
            }
            try {
              const data = JSON.parse(jsonStr)
              if (data.done) {
                onDone && onDone(data)
                return
              }
              if (data.content) {
                onMessage && onMessage(data)
              }
            } catch (e) {
              // 忽略解析错误的行
            }
          }
        }
        // 处理 buffer 中剩余数据
        if (buffer.startsWith('data:')) {
          try {
            const data = JSON.parse(buffer.replace(/^data:\s*/, ''))
            if (data.done) {
              onDone && onDone(data)
            } else if (data.content) {
              onMessage && onMessage(data)
            }
          } catch (e) {}
        }
        onDone && onDone({})
      } catch (err) {
        if (err.name === 'AbortError') {
          // 主动中断，不计为错误
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

export default request
