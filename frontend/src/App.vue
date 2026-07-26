<template>
  <a-config-provider :locale="zhCN">
    <a-layout class="app-layout">
      <a-layout-sider v-model:collapsed="collapsed" theme="dark" :trigger="null" collapsible>
        <div class="logo">
          <span class="logo-text">{{ collapsed ? 'AS' : 'AgentService' }}</span>
        </div>
        <a-menu
          v-model:selectedKeys="selectedKeys"
          theme="dark"
          mode="inline"
          :items="menuItems"
          @click="handleMenuClick"
        />
      </a-layout-sider>

      <a-layout>
        <a-layout-header class="app-header">
          <span class="header-title">{{ currentPageTitle }}</span>
        </a-layout-header>

        <a-layout-content class="app-content">
          <router-view v-slot="{ Component }">
            <component :is="Component" />
          </router-view>
        </a-layout-content>

        <a-layout-footer class="app-footer">
          AgentService Platform © 2026 - v1.0.0
        </a-layout-footer>
      </a-layout>
    </a-layout>
  </a-config-provider>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  MessageOutlined,
  RobotOutlined,
  ToolOutlined,
  DatabaseOutlined,
  BarChartOutlined,
  TeamOutlined,
  BulbOutlined,
  FileSearchOutlined
} from '@ant-design/icons-vue'
import zhCN from 'ant-design-vue/es/locale/zh_CN'

const router = useRouter()
const route = useRoute()
const collapsed = ref(false)
const selectedKeys = ref([route.name || 'chat'])

const menuItems = [
  { key: 'chat', icon: 'MessageOutlined', label: '对话' },
  { key: 'agents', icon: 'RobotOutlined', label: 'Agent管理' },
  { key: 'mcp', icon: 'ToolOutlined', label: 'MCP服务' },
  { key: 'skills', icon: 'BulbOutlined', label: '技能库' },
  { key: 'memory', icon: 'FileSearchOutlined', label: '记忆管理' },
  { key: 'rag', icon: 'DatabaseOutlined', label: '知识库' },
  { key: 'chatbi', icon: 'BarChartOutlined', label: 'ChatBI' },
  { key: 'collaboration', icon: 'TeamOutlined', label: '多Agent协作' },
]

const currentPageTitle = computed(() => {
  const item = menuItems.find(m => m.key === selectedKeys.value[0])
  return item ? item.label : 'AgentService'
})

function handleMenuClick({ key }) {
  router.push({ name: key })
}
</script>

<style scoped>
.app-layout {
  min-height: 100vh;
}

.logo {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.1);
  margin: 0;
}

.logo-text {
  color: #fff;
  font-size: 18px;
  font-weight: bold;
}

.app-header {
  background: #fff;
  padding: 0 24px;
  border-bottom: 1px solid #f0f0f0;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
}

.app-content {
  margin: 16px;
  padding: 24px;
  background: #fff;
  border-radius: 8px;
  min-height: calc(100vh - 64px - 69px - 32px);
}

.app-footer {
  text-align: center;
  background: #fafafa;
}
</style>
