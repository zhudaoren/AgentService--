<template>
  <div class="mermaid-block" :class="{ error: hasError }">
    <div class="mermaid-block__toolbar">
      <a-tag v-if="title" size="small" color="default" class="mermaid-title-tag">{{ title }}</a-tag>
      <a-space size="small">
        <a-button size="small" type="link" @click="viewMode = viewMode === 'svg' ? 'code' : 'svg'">
          {{ viewMode === 'svg' ? '查看源码' : '查看图形' }}
        </a-button>
      </a-space>
    </div>
    <div class="mermaid-block__body">
      <pre v-if="viewMode === 'code'" class="language-mermaid"><code>{{ code }}</code></pre>
      <div v-else ref="svgContainerRef" class="mermaid-render"></div>
    </div>
    <div v-if="hasError && viewMode === 'svg'" class="mermaid-block__error">
      Mermaid 渲染失败：{{ errorMessage }}（已自动切为"查看源码"模式）
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch, nextTick } from 'vue'
import mermaid from 'mermaid'

const props = defineProps({
  code: { type: String, required: true },
  title: { type: String, default: '' },
})

const viewMode = ref('svg')
const hasError = ref(false)
const errorMessage = ref('')
const svgContainerRef = ref(null)

// 全局初始化一次（securityLevel: strict 禁止脚本/外链点击，防止XSS）
let _initialized = false
function ensureInit() {
  if (_initialized) return
  try {
    mermaid.initialize({
      startOnLoad: false,
      theme: 'default',
      securityLevel: 'strict',
      maxTextSize: 200000,
      fontFamily: 'inherit',
    })
    _initialized = true
  } catch (e) {
    console.warn('[Mermaid] init failed:', e)
  }
}

async function render() {
  ensureInit()
  hasError.value = false
  errorMessage.value = ''
  if (viewMode.value !== 'svg') return
  if (!svgContainerRef.value) return
  try {
    // 清空旧 SVG
    svgContainerRef.value.innerHTML = ''
    const { svg } = await mermaid.render(
      'mmd-' + Math.random().toString(36).slice(2, 9),
      props.code.trim()
    )
    svgContainerRef.value.innerHTML = svg
  } catch (err) {
    hasError.value = true
    errorMessage.value = (err && err.message) ? err.message : String(err)
    console.warn('[Mermaid] render failed:', err)
    viewMode.value = 'code' // 失败回退到源码
  }
}

onMounted(render)
watch(() => [props.code, viewMode.value], () => nextTick(render))
</script>

<style scoped>
.mermaid-block {
  margin: 12px 0;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}
.mermaid-block__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: #fafafa;
  border-bottom: 1px solid #f0f0f0;
  font-size: 12px;
}
.mermaid-title-tag {
  margin-inline-end: 0;
}
.mermaid-block__body {
  padding: 12px;
  overflow-x: auto;
}
.mermaid-render {
  display: flex;
  justify-content: center;
}
.mermaid-render :deep(svg) {
  max-width: 100%;
  height: auto;
}
.mermaid-block.error {
  border-color: #ffe58f;
}
.mermaid-block__error {
  padding: 6px 12px;
  background: #fffbe6;
  color: #d48806;
  font-size: 12px;
  border-top: 1px dashed #f0f0f0;
}
pre.language-mermaid {
  margin: 0;
  background: #282c34;
  color: #abb2bf;
  border-radius: 6px;
  padding: 12px;
  font-family: Consolas, Monaco, monospace;
  font-size: 13px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
pre.language-mermaid code {
  background: transparent;
  padding: 0;
}
</style>
