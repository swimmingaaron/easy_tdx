<script setup lang="ts">
import { ref } from 'vue'

import { detectMarket } from '../market'
import StockSearchInput from './StockSearchInput.vue'
import type { StockSuggestItem } from '../types'

const props = defineProps<{
  modelValue: string[]
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()

const code = ref('')

function add() {
  if (!/^\d{6}$/.test(code.value)) return
  const sym = `${detectMarket(code.value)}:${code.value}`
  if (!props.modelValue.includes(sym)) {
    emit('update:modelValue', [...props.modelValue, sym])
  }
  code.value = ''
}

/** 选中下拉建议项时，直接添加并清空输入框（组合页选中即添加） */
function onSelectEntry(entry: StockSuggestItem) {
  const sym = `${entry.market}:${entry.code}`
  if (!props.modelValue.includes(sym)) {
    emit('update:modelValue', [...props.modelValue, sym])
  }
  code.value = ''
}

function remove(sym: string) {
  emit('update:modelValue', props.modelValue.filter((s) => s !== sym))
}
</script>

<template>
  <div class="stocks-picker">
    <div class="row add-row">
      <StockSearchInput
        v-model="code"
        placeholder="6位代码 / 拼音(如jzgf) / 名称"
        @select="onSelectEntry"
        @confirm="add"
      />
      <button class="add-btn" @click="add">添加</button>
    </div>

    <div v-if="modelValue.length" class="stock-list">
      <span v-for="s in modelValue" :key="s" class="stock-tag">
        {{ s }}
        <button class="remove" @click="remove(s)">×</button>
      </span>
    </div>
    <p v-else class="hint">至少添加 1 只标的</p>
  </div>
</template>

<style scoped>
.add-row {
  display: flex;
  gap: 6px;
  align-items: flex-start;
}
.add-row :deep(.stock-search-input) {
  flex: 1;
}
.add-btn {
  height: 32px;
  white-space: nowrap;
  flex-shrink: 0;
}
.stock-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.stock-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-family: var(--font-mono);
}
.remove {
  border: none;
  background: none;
  color: var(--text-dim);
  padding: 0 2px;
  font-size: 14px;
  line-height: 1;
}
.remove:hover {
  color: var(--up);
}
.hint {
  color: var(--text-dim);
  font-size: 11px;
  margin-top: 8px;
}
</style>
