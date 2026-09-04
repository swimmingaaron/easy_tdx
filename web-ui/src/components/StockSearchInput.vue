<script setup lang="ts">
// 股票智能搜索输入框：支持 6 位代码 / 拼音声母（如 jzgf）/ 中文名称（如 君正）实时联想。
// 支持键盘导航（↑/↓/Enter/Esc）与鼠标交互，选中后自动回填 6 位代码并显示市场标签。

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { fetchStockSuggestions } from '../api'
import { detectMarket, marketLabel } from '../market'
import type { StockSuggestItem } from '../types'

const props = withDefaults(
  defineProps<{
    modelValue: string
    placeholder?: string
    autoAddOnSelect?: boolean
  }>(),
  {
    placeholder: '搜索股票代码...',
    autoAddOnSelect: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'select': [item: StockSuggestItem]
  'confirm': [code: string]
}>()

const inputRef = ref<HTMLInputElement | null>(null)
const containerRef = ref<HTMLElement | null>(null)

// 当前输入框文本
const query = ref(props.modelValue || '')
// 当前选中的股票名称（用于展示提示）
const selectedName = ref('')
// 联想建议列表
const suggestions = ref<StockSuggestItem[]>([])
// 下拉框展开状态
const open = ref(false)
// 键盘选中的索引（-1 表示无）
const activeIndex = ref(-1)
// 防抖计时器
let debounceTimer: ReturnType<typeof setTimeout> | null = null

// 智能识别当前代码的市场（用于右侧 badge）
const detectedMarket = computed(() => {
  if (query.value && /^\d{6}$/.test(query.value)) {
    return marketLabel(detectMarket(query.value))
  }
  return ''
})

// 外部 v-model 变化时同步到 query
watch(
  () => props.modelValue,
  (newVal) => {
    if (newVal !== query.value) {
      query.value = newVal || ''
    }
  },
)

// 当用户输入时触发联想搜索
function onInput(e: Event) {
  const val = (e.target as HTMLInputElement).value
  query.value = val
  activeIndex.value = -1

  // 如果用户直接输入了 6 位数字，直接 emit
  if (/^\d{6}$/.test(val)) {
    emit('update:modelValue', val)
  }

  if (debounceTimer) clearTimeout(debounceTimer)
  const trimmed = val.trim()
  if (!trimmed) {
    suggestions.value = []
    open.value = false
    return
  }

  debounceTimer = setTimeout(async () => {
    const list = await fetchStockSuggestions(trimmed)
    suggestions.value = list
    open.value = list.length > 0
    activeIndex.value = list.length > 0 ? 0 : -1

    // 如果正好匹配到单只股票且是 6 位纯数字，记录名称
    const exact = list.find((it) => it.code === trimmed)
    if (exact) {
      selectedName.value = exact.name
    }
  }, 120)
}

function onFocus() {
  if (suggestions.value.length > 0 && query.value.trim()) {
    open.value = true
  }
}

// 选中某个建议项：只在搜索框回填 6 位股票代码，节省布局
function selectItem(item: StockSuggestItem) {
  query.value = item.code
  selectedName.value = item.name
  open.value = false
  suggestions.value = []
  emit('update:modelValue', item.code)
  emit('select', item)
  nextTick(() => {
    inputRef.value?.focus()
  })
}

// 清空按钮
function clearQuery() {
  query.value = ''
  selectedName.value = ''
  open.value = false
  suggestions.value = []
  emit('update:modelValue', '')
  inputRef.value?.focus()
}

// 键盘事件处理
function onKeyDown(e: KeyboardEvent) {
  if (!open.value || suggestions.value.length === 0) {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (/^\d{6}$/.test(query.value)) {
        emit('update:modelValue', query.value)
      }
      emit('confirm', query.value)
    }
    return
  }

  switch (e.key) {
    case 'ArrowDown':
      e.preventDefault()
      activeIndex.value = (activeIndex.value + 1) % suggestions.value.length
      break
    case 'ArrowUp':
      e.preventDefault()
      activeIndex.value =
        activeIndex.value <= 0 ? suggestions.value.length - 1 : activeIndex.value - 1
      break
    case 'Enter':
      e.preventDefault()
      if (activeIndex.value >= 0 && activeIndex.value < suggestions.value.length) {
        selectItem(suggestions.value[activeIndex.value])
      } else {
        if (/^\d{6}$/.test(query.value)) {
          emit('update:modelValue', query.value)
        }
        emit('confirm', query.value)
        open.value = false
      }
      break
    case 'Escape':
      e.preventDefault()
      open.value = false
      break
  }
}

// 点击外部关闭下拉建议
function onClickOutside(e: MouseEvent) {
  if (containerRef.value && !containerRef.value.contains(e.target as Node)) {
    open.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', onClickOutside)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onClickOutside)
  if (debounceTimer) clearTimeout(debounceTimer)
})
</script>

<template>
  <div ref="containerRef" class="stock-search-input">
    <div class="input-wrapper">
      <input
        ref="inputRef"
        :value="query"
        type="text"
        :placeholder="placeholder"
        autocomplete="off"
        spellcheck="false"
        @input="onInput"
        @focus="onFocus"
        @keydown="onKeyDown"
      />
      <button
        v-if="query"
        type="button"
        class="clear-btn"
        title="清空"
        @click="clearQuery"
      >
        ✕
      </button>
      <span v-if="detectedMarket" class="market-tag">{{ detectedMarket }}</span>
    </div>

    <!-- 联想建议浮层 -->
    <div v-if="open && suggestions.length" class="suggest-dropdown">
      <div
        v-for="(item, idx) in suggestions"
        :key="item.symbol"
        :class="['suggest-item', { active: idx === activeIndex }]"
        @mousedown.prevent="selectItem(item)"
        @mouseenter="activeIndex = idx"
      >
        <div class="suggest-left">
          <span class="stock-name">{{ item.name }}</span>
          <span v-if="item.pinyin" class="stock-pinyin">{{ item.pinyin.toUpperCase() }}</span>
        </div>
        <div class="suggest-right">
          <span class="stock-code">{{ item.code }}</span>
          <span class="market-badge" :class="item.market.toLowerCase()">
            {{ item.market === 'SH' ? '沪' : item.market === 'SZ' ? '深' : '北' }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stock-search-input {
  position: relative;
  width: 100%;
}
.input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}
.input-wrapper input {
  width: 100%;
  padding-right: 68px;
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text);
  padding-top: 6px;
  padding-bottom: 6px;
  padding-left: 10px;
  border-radius: var(--radius);
  font-size: 13px;
  transition: border-color 0.15s;
}
.input-wrapper input:focus {
  outline: none;
  border-color: var(--accent);
}
.clear-btn {
  position: absolute;
  right: 48px;
  background: transparent;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 11px;
  padding: 0 4px;
  line-height: 1;
}
.clear-btn:hover {
  color: var(--text);
}
.market-tag {
  position: absolute;
  right: 6px;
  font-size: 11px;
  color: var(--text-dim);
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  padding: 1px 6px;
  border-radius: 3px;
  pointer-events: none;
}
.suggest-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: var(--radius);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.6);
  max-height: 260px;
  overflow-y: auto;
  z-index: 200;
}
.suggest-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 10px;
  cursor: pointer;
  border-bottom: 1px solid rgba(51, 65, 85, 0.5);
  transition: background 0.1s;
}
.suggest-item:last-child {
  border-bottom: none;
}
.suggest-item:hover,
.suggest-item.active {
  background: #1e293b;
}
.suggest-left {
  display: flex;
  align-items: center;
  gap: 6px;
}
.stock-name {
  font-size: 13px;
  font-weight: 700;
  color: #ffffff;
}
.stock-pinyin {
  font-size: 10px;
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.15);
  padding: 1px 4px;
  border-radius: 2px;
  font-family: var(--font-mono);
  font-weight: 600;
}
.suggest-right {
  display: flex;
  align-items: center;
  gap: 6px;
}
.stock-code {
  font-family: var(--font-mono);
  font-size: 12px;
  color: #38bdf8;
  font-weight: 700;
}
.market-badge {
  font-size: 10px;
  padding: 1px 4px;
  border-radius: 2px;
  font-weight: 600;
}
.market-badge.sh {
  background: rgba(239, 65, 70, 0.25);
  color: #f87171;
}
.market-badge.sz {
  background: rgba(56, 189, 248, 0.25);
  color: #38bdf8;
}
.market-badge.bj {
  background: rgba(245, 158, 11, 0.25);
  color: #fbbf24;
}
</style>
