<template>
  <a-config-provider :locale="zhCN">
    <a-layout class="app-layout">
      <a-layout-sider
        v-model:collapsed="collapsed"
        theme="dark"
        :trigger="null"
        collapsible
        width="220"
        class="app-sider"
      >
        <div class="logo">
          <robot-outlined class="logo-icon" />
          <span v-if="!collapsed" class="logo-text">AgentService</span>
        </div>
        <a-menu
          v-model:selectedKeys="selectedKeys"
          v-model:openKeys="openKeys"
          theme="dark"
          mode="inline"
          :items="menuItems"
          @click="handleMenuClick"
        />
      </a-layout-sider>

      <a-layout class="app-main">
        <a-layout-header class="app-header">
          <div class="header-left">
            <a-button type="text" class="collapse-btn" @click="collapsed = !collapsed">
              <menu-unfold-outlined v-if="collapsed" />
              <menu-fold-outlined v-else />
            </a-button>
            <span class="header-title">{{ currentPageTitle }}</span>
          </div>
          <div class="header-right">
            <a-tag color="blue">P1 阶段</a-tag>
            <a-tooltip title="网关地址: http://localhost:8000">
              <a-badge status="success" text="网关在线" />
            </a-tooltip>
          </div>
        </a-layout-header>

        <a-layout-content class="app-content">
          <router-view v-slot="{ Component }">
            <component :is="Component" />
          </router-view>
        </a-layout-content>
      </a-layout>
    </a-layout>
  </a-config-provider>
</template>

<script setup>
import { ref, computed, h, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  MessageOutlined,
  RobotOutlined,
  ToolOutlined,
  DatabaseOutlined,
  BarChartOutlined,
  TeamOutlined,
  BulbOutlined,
  FileSearchOutlined,
  ApiOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons-vue'
import zhCN from 'ant-design-vue/es/locale/zh_CN'

const router = useRouter()
const route = useRoute()
const collapsed = ref(false)
const openKeys = ref([])
const selectedKeys = ref([route.name || 'chat'])

const menuItems = [
  { key: 'chat', icon: () => h(MessageOutlined), label: '对话' },
  { key: 'agents', icon: () => h(RobotOutlined), label: 'Agent管理' },
  { key: 'llm-config', icon: () => h(ApiOutlined), label: 'LLM配置' },
  { key: 'memory', icon: () => h(FileSearchOutlined), label: '记忆管理' },
  { key: 'mcp', icon: () => h(ToolOutlined), label: 'MCP服务' },
  { key: 'skills', icon: () => h(BulbOutlined), label: '技能库' },
  { key: 'rag', icon: () => h(DatabaseOutlined), label: '知识库' },
  { key: 'chatbi', icon: () => h(BarChartOutlined), label: 'ChatBI' },
  { key: 'collaboration', icon: () => h(TeamOutlined), label: '多Agent协作' },
]

const currentPageTitle = computed(() => {
  const item = menuItems.find((m) => m.key === selectedKeys.value[0])
  return item ? item.label : 'AgentService'
})

watch(
  () => route.name,
  (name) => {
    if (name) selectedKeys.value = [name]
  }
)

function handleMenuClick({ key }) {
  router.push({ name: key })
}
</script>

<style scoped>
.app-layout {
  height: 100vh;
}

.app-sider {
  overflow: auto;
  height: 100vh;
  position: sticky;
  top: 0;
  left: 0;
}

.logo {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}

.logo-icon {
  font-size: 24px;
  color: #1677ff;
}

.logo-text {
  font-size: 18px;
  font-weight: 600;
  color: #fff;
  letter-spacing: 0.5px;
}

.app-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.app-header {
  background: #fff;
  padding: 0 16px 0 0;
  border-bottom: 1px solid #f0f0f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 100%;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.collapse-btn {
  font-size: 18px;
  width: 48px;
  height: 64px;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
  color: #1f1f1f;
}

.app-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  background: #f0f2f5;
}
</style>
