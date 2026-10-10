<script setup lang="ts">
// 选标的 + 配置日期范围（取行情由父组件在「开始回测/开始寻优」时触发）。
// 市场按 6 位代码智能识别，不再手动选择。
// 后端 /bars 仅支持 count（上限 800，约 3.2 年），固定拉满后前端按日期过滤。
// 默认：结束日=今天（最近交易日），开始日=2020-01-06。

import { onMounted, ref } from 'vue'

import { fetchBars, fetchHotSectors, formatError, type HotSectorItem } from '../api'
import { detectMarket } from '../market'
import StockSearchInput from './StockSearchInput.vue'
import { useBacktestStore } from '../stores/backtest'
import type { Category } from '../types'

const store = useBacktestStore()

const hotSectors = ref<HotSectorItem[]>([
  { code: '881376', name: '数字媒体', change_pct: 0, chg: '--' },
  { code: '881422', name: '房产服务', change_pct: 0, chg: '--' },
  { code: '881373', name: '影视院线', change_pct: 0, chg: '--' },
  { code: '881319', name: '半导体', change_pct: 0, chg: '--' },
  { code: '881394', name: '证券', change_pct: 0, chg: '--' },
  { code: '881386', name: '全国银行', change_pct: 0, chg: '--' },
])

async function loadHotSectors(_force = false) {
  const list = await fetchHotSectors(8)
  if (list && list.length > 0) {
    hotSectors.value = list
  }
}

function selectHotSector(sectorCode: string) {
  code.value = sectorCode
}

onMounted(() => {
  loadHotSectors()
})

// 代码 / 周期 / 日期通过 defineModel 与父组件双向同步：
// 既允许父组件读取（如寻优页「查看」按钮拼 URL 带上这些值），
// 也允许父组件写入（如回测页从 URL query 回填表单）。
// 未绑定时取默认值，向后兼容。
//
// 注意：defineModel 的 default 不能引用本 <script setup> 内声明的局部函数
// （编译期会被 hoist 到 setup() 外，此时函数还未定义），
// 默认：结束日=今天（最近交易日），开始日=一年前。
const code = defineModel<string>('code', { default: '000001' })
const category = defineModel<Category>('category', { default: 'DAY' })
const startDate = defineModel<string>('startDate', {
  default: new Date(new Date().setFullYear(new Date().getFullYear() - 1)).toISOString().slice(0, 10),
})
const endDate = defineModel<string>('endDate', {
  default: new Date().toISOString().slice(0, 10),
})

const error = ref('')
// loading 由父组件控制（回测/寻优时驱动），组件自身只暴露 loadBars
const loading = ref(false)

const CATEGORIES: Category[] = ['DAY', 'WEEK', 'MONTH', 'MIN_5', 'MIN_15', 'MIN_30', 'MIN_60']

/** 取行情（由父组件在点击「开始回测/开始寻优」时调用）。
 * 成功返回 true，失败返回 false（并把错误写入 store.error 供父组件感知）。 */
async function loadBars(): Promise<boolean> {
  // 基本校验
  if (!/^\d{6}$/.test(code.value)) {
    error.value = '股票代码必须是 6 位数字'
    store.error = error.value
    return false
  }
  if (startDate.value >= endDate.value) {
    error.value = '开始日期必须早于结束日期'
    store.error = error.value
    return false
  }

  loading.value = true
  error.value = ''
  try {
    const market = detectMarket(code.value)
    const bars = await fetchBars(
      market,
      code.value,
      category.value,
      startDate.value,
      endDate.value,
    )
    if (bars.length < 2) {
      error.value = `该日期范围内仅取到 ${bars.length} 根 K 线，不足以回测`
      store.error = error.value
      return false
    }
    const range = `${startDate.value} ~ ${endDate.value}`
    store.setOhlcv(bars, `${market}:${code.value} ${category.value} ${range}`)
    store.clearResult()
    return true
  } catch (e) {
    error.value = formatError(e)
    store.error = error.value
    return false
  } finally {
    loading.value = false
  }
}

// 暴露给父组件（BacktestView / OptimizeView）在「开始回测/寻优」时串联调用
defineExpose({ loadBars, loading })
</script>

<template>
  <div class="symbol-picker">
    <div class="field">
      <label>股票代码</label>
      <StockSearchInput
        v-model="code"
        placeholder="搜索股票代码..."
      />
    </div>

    <!-- 热门行业板块一键回测 (实时) -->
    <div class="hot-sectors-section">
      <div class="hot-sectors-header">
        <label>热门行业板块一键回测：</label>
        <span class="live-badge" title="基于全市场实时行情排序，点击立即刷新" @click="loadHotSectors(true)">
          <span class="dot"></span>实时
        </span>
      </div>
      <div class="hot-sectors-list">
        <button
          v-for="s in hotSectors"
          :key="s.code"
          type="button"
          class="hot-sector-btn"
          :title="`${s.name} (${s.code}) 实时涨跌: ${s.chg}，点击快速切换`"
          @click="selectHotSector(s.code)"
        >
          <span class="name">{{ s.name }}</span>
          <span v-if="s.chg !== '--'" :class="['chg', s.change_pct >= 0 ? 'chg-up' : 'chg-down']">{{ s.chg }}</span>
        </button>
      </div>
    </div>

    <div class="field">
      <label>周期</label>
      <select v-model="category">
        <option v-for="c in CATEGORIES" :key="c" :value="c">{{ c }}</option>
      </select>
    </div>

    <div class="row">
      <div class="field">
        <label>开始日期</label>
        <input v-model="startDate" type="date" />
      </div>
      <div class="field">
        <label>结束日期</label>
        <input v-model="endDate" type="date" />
      </div>
    </div>

    <p v-if="error" class="err">{{ error }}</p>
    <p v-if="store.barsSource" class="ok">
      已加载：{{ store.barsSource }}（{{ store.ohlcv.length }} 根）
    </p>
  </div>
</template>

<style scoped>
.hot-sectors-section {
  margin-top: -4px;
  margin-bottom: 8px;
}
.hot-sectors-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.hot-sectors-header label {
  font-size: 11px;
  color: var(--muted, #94a3b8);
}
.live-badge {
  display: inline-flex;
  align-items: center;
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(6, 78, 59, 0.4);
  color: #34d399;
  border: 1px solid rgba(5, 150, 105, 0.4);
  cursor: pointer;
  user-select: none;
}
.live-badge .dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #34d399;
  margin-right: 4px;
  animation: pulse 1.5s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
.hot-sectors-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.hot-sector-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 10px;
  background: rgba(30, 27, 75, 0.6);
  color: #c7d2fe;
  border: 1px solid rgba(67, 56, 202, 0.6);
  cursor: pointer;
  transition: all 0.15s ease;
}
.hot-sector-btn:hover {
  background: rgba(49, 46, 129, 0.8);
  border-color: #6366f1;
  color: #fff;
}
.chg {
  font-family: monospace;
  font-size: 9px;
}
.chg-up {
  color: #fb7185;
  font-weight: 600;
}
.chg-down {
  color: #34d399;
  font-weight: 600;
}
.err {
  color: var(--up);
  font-size: 12px;
  margin-top: 8px;
}
.ok {
  color: var(--down);
  font-size: 12px;
  margin-top: 8px;
}
</style>
