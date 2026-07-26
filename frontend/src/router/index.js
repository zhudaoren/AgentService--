import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/chat'
  },
  {
    path: '/chat',
    name: 'chat',
    component: () => import('@/views/chat/index.vue'),
    meta: { title: '对话' }
  },
  {
    path: '/agents',
    name: 'agents',
    component: () => import('@/views/agent/index.vue'),
    meta: { title: 'Agent管理' }
  },
  {
    path: '/mcp',
    name: 'mcp',
    component: () => import('@/views/mcp/index.vue'),
    meta: { title: 'MCP服务' }
  },
  {
    path: '/skills',
    name: 'skills',
    component: () => import('@/views/skill/index.vue'),
    meta: { title: '技能库' }
  },
  {
    path: '/memory',
    name: 'memory',
    component: () => import('@/views/memory/index.vue'),
    meta: { title: '记忆管理' }
  },
  {
    path: '/rag',
    name: 'rag',
    component: () => import('@/views/rag/index.vue'),
    meta: { title: '知识库' }
  },
  {
    path: '/chatbi',
    name: 'chatbi',
    component: () => import('@/views/chatbi/index.vue'),
    meta: { title: 'ChatBI' }
  },
  {
    path: '/collaboration',
    name: 'collaboration',
    component: () => import('@/views/collaboration/index.vue'),
    meta: { title: '多Agent协作' }
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

export default router
