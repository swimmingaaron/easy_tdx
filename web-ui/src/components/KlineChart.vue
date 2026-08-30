<script setup lang="ts">
// K线主图 + 买卖点标注 + 成交额柱状图（ECharts dual-grid candlestick + volume bar）。
// 核心难点：把 trades 的 datetime 对齐到 K线时间轴，上下子图联动缩放。

import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { fetchStockSuggestions } from '../api'
import echarts, { DOWN_COLOR, UP_COLOR } from '../echarts-setup'
import { fmt2 } from '../format'
import type { Bar, Trade } from '../types'

const props = withDefaults(
  defineProps<{
    bars: Bar[]
    trades: Trade[]
    code?: string
    stockName?: string
    symbol?: string
    groupId?: string
    showDateControls?: boolean
  }>(),
  {
    groupId: 'backtest-charts-sync',
    showDateControls: true,
  },
)

const emit = defineEmits<{
  'shiftStart': [delta: number]
  'shiftEnd': [delta: number]
}>()

const container = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

// 自动解析股票名称（若外部未传入则按代码搜索补齐）
const resolvedName = ref(props.stockName || '')

watch(
  () => [props.code, props.stockName, props.symbol],
  async () => {
    if (props.stockName) {
      resolvedName.value = props.stockName
      render()
      return
    }
    const c = props.code || (props.symbol ? props.symbol.split(':').pop() : '')
    if (c && /^\d{6}$/.test(c)) {
      try {
        const items = await fetchStockSuggestions(c)
        const exact = items.find((it) => it.code === c)
        if (exact) {
          resolvedName.value = exact.name
          render()
        }
      } catch {
        // 忽略联想异常
      }
    }
  },
  { immediate: true },
)

function fmtAmount(val: number): string {
  if (!Number.isFinite(val) || val === 0) return '0'
  const abs = Math.abs(val)
  if (abs >= 1e8) {
    return `${(val / 1e8).toFixed(2)}亿`
  }
  if (abs >= 1e4) {
    return `${(val / 1e4).toFixed(0)}万`
  }
  return val.toFixed(0)
}

function render() {
  if (!container.value || props.bars.length === 0) return
  chart ??= echarts.init(container.value, 'dark')
  chart.group = props.groupId
  chart.setOption(buildOption(), true)
  echarts.connect(props.groupId)
}

/** 构建 ECharts 配置。trades 的 datetime 对齐到 K线 index。 */
function buildOption(): echarts.EChartsCoreOption {
  const keys = props.bars.map((b) => b.datetime)
  const keyIndex = new Map<string, number>()
  keys.forEach((k, i) => keyIndex.set(k, i))

  const isIntraday = keys.some((k) => {
    const time = k.slice(11, 19)
    return time && time !== '00:00:00'
  })
  const dates = keys.map((k) => (isIntraday ? k.replace('T', ' ').slice(5, 16) : k.slice(0, 10)))

  const ohlc = props.bars.map((b) => [b.open, b.close, b.low, b.high])

  // 成交额柱状图数据（阳红阴绿）
  const amounts = props.bars.map((b) => ({
    value: b.amount,
    itemStyle: {
      color: b.close >= b.open ? UP_COLOR : DOWN_COLOR,
      borderColor: b.close >= b.open ? UP_COLOR : DOWN_COLOR,
    },
  }))

  // 买卖点 markPoint
  const markPoints: Array<{
    name: string
    coord: [number, number]
    value: string
    itemStyle: { color: string }
    symbol: string
    symbolSize: number
    label: {
      show: boolean
      formatter: string
      position: string
      color: string
      fontSize: number
      fontWeight: string
      offset?: [number, number]
    }
  }> = []
  for (const t of props.trades) {
    if (t.rejected) continue
    const tKey = t.datetime.slice(0, 19).replace(' ', 'T')
    let idx = keyIndex.get(tKey)
    if (idx === undefined) {
      const dayPrefix = tKey.slice(0, 10)
      idx = keys.findIndex((k) => k.startsWith(dayPrefix))
      if (idx === -1) continue
    }
    const isBuy = t.direction === 'BUY'
    markPoints.push({
      name: isBuy ? '买入 (B)' : '卖出 (S)',
      coord: [idx, t.price],
      value: isBuy ? 'B' : 'S',
      itemStyle: { color: isBuy ? UP_COLOR : DOWN_COLOR },
      symbol: isBuy ? 'triangle' : 'pin',
      symbolSize: 14,
      label: {
        show: true,
        formatter: isBuy ? 'B' : 'S',
        position: 'top',
        color: isBuy ? UP_COLOR : DOWN_COLOR,
        fontSize: 13,
        fontWeight: 'bold',
        offset: [0, -2],
      },
    })
  }

  // 组装 K 线名称（如：君正股份 (601216) K线）
  const cleanCode = props.code || (props.symbol ? props.symbol.split(':').pop() : '')
  let klineName = 'K线'
  if (resolvedName.value && cleanCode) {
    klineName = `${resolvedName.value} (${cleanCode}) K线`
  } else if (resolvedName.value) {
    klineName = `${resolvedName.value} K线`
  } else if (cleanCode) {
    klineName = `${cleanCode} K线`
  }

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'cross',
        label: {
          show: true,
          backgroundColor: '#383f4d',
        },
      },
      formatter: (params: any) => {
        if (!Array.isArray(params) || params.length === 0) return ''
        const dataIndex = params[0].dataIndex
        const bar = props.bars[dataIndex]
        if (!bar) return ''
        const dateStr = dates[dataIndex]
        const chg = bar.open > 0 ? ((bar.close - bar.open) / bar.open) * 100 : 0
        const chgSign = chg > 0 ? '+' : ''
        const chgColor = chg >= 0 ? UP_COLOR : DOWN_COLOR

        let html = `<div style="font-size:12px; line-height:1.6; min-width:140px;">`
        html += `<div style="font-weight:600; margin-bottom:4px; color:#e6e8eb; border-bottom:1px solid #383f4d; padding-bottom:2px;">`
        html += `${resolvedName.value ? resolvedName.value + ' ' : ''}${cleanCode ? '(' + cleanCode + ') ' : ''}${dateStr}</div>`
        html += `<div>开盘: <span style="color:#e6e8eb; font-family:monospace;">${fmt2(bar.open)}</span></div>`
        html += `<div>收盘: <span style="color:${chgColor}; font-family:monospace; font-weight:600;">${fmt2(bar.close)} (${chgSign}${chg.toFixed(2)}%)</span></div>`
        html += `<div>最高: <span style="color:#e6e8eb; font-family:monospace;">${fmt2(bar.high)}</span></div>`
        html += `<div>最低: <span style="color:#e6e8eb; font-family:monospace;">${fmt2(bar.low)}</span></div>`
        html += `<div>成交额: <span style="color:#e6e8eb; font-family:monospace; font-weight:600;">${fmtAmount(bar.amount)}</span></div>`
        if (bar.vol) {
          html += `<div>成交量: <span style="color:#e6e8eb; font-family:monospace;">${(bar.vol / 100).toFixed(0)}手</span></div>`
        }
        html += `</div>`
        return html
      },
    },
    legend: {
      data: [klineName, '成交额'],
      top: 0,
      textStyle: { color: '#e6e8eb' },
    },
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
    },
    grid: [
      // 上图：K线
      { left: 70, right: 65, top: 32, height: '58%' },
      // 下图：成交额柱状图
      { left: 70, right: 65, top: '74%', height: '16%' },
    ],
    xAxis: [
      // 上图 X 轴
      {
        type: 'category',
        gridIndex: 0,
        data: dates,
        boundaryGap: true,
        axisLine: { onZero: false, lineStyle: { color: '#2a2e3a' } },
        splitLine: { show: false },
        axisLabel: { show: false },
        axisPointer: { label: { show: false } },
      },
      // 下图 X 轴
      {
        type: 'category',
        gridIndex: 1,
        data: dates,
        boundaryGap: true,
        axisLine: { onZero: false, lineStyle: { color: '#2a2e3a' } },
        splitLine: { show: false },
        axisLabel: {
          formatter: (v: string) => v,
          color: '#8b919e',
          fontSize: 11,
        },
        axisPointer: { label: { show: true } },
      },
    ],
    yAxis: [
      // 上图 Y 轴（价格）
      {
        type: 'value',
        gridIndex: 0,
        scale: true,
        splitLine: { lineStyle: { color: '#2a2e3a' } },
        axisLabel: { formatter: (v: number) => fmt2(v), color: '#8b919e' },
      },
      // 下图 Y 轴（成交额）
      {
        type: 'value',
        gridIndex: 1,
        scale: true,
        splitNumber: 2,
        splitLine: { lineStyle: { color: '#2a2e3a' } },
        axisLabel: {
          formatter: (v: number) => fmtAmount(v),
          color: '#8b919e',
          fontSize: 10,
        },
      },
    ],
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: [0, 1],
        start: 0,
        end: 100,
      },
      {
        type: 'slider',
        xAxisIndex: [0, 1],
        bottom: 4,
        start: 0,
        end: 100,
        height: 16,
        borderColor: '#2a2e3a',
        fillerColor: 'rgba(74, 158, 255, 0.15)',
        textStyle: { color: '#8b919e', fontSize: 10 },
      },
    ],
    series: [
      // 0: K线
      {
        name: klineName,
        type: 'candlestick',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: ohlc,
        itemStyle: {
          color: UP_COLOR,
          color0: DOWN_COLOR,
          borderColor: UP_COLOR,
          borderColor0: DOWN_COLOR,
        },
        markPoint: {
          data: markPoints,
        },
      },
      // 1: 成交额柱状图
      {
        name: '成交额',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: amounts,
      },
    ],
  }
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  render()
  window.addEventListener('resize', resize)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})
watch(() => [props.bars, props.trades, props.code, props.stockName, props.symbol], render)
</script>

<template>
  <div class="kline-chart-wrapper">
    <div v-if="showDateControls" class="kline-date-controls">
      <div class="date-controls-left">
        <button
          type="button"
          class="date-step-btn"
          title="开始日期往前一日并重新回测"
          @click="emit('shiftStart', -1)"
        >
          ◀ 上一日
        </button>
        <button
          type="button"
          class="date-step-btn"
          title="开始日期往后一日并重新回测"
          @click="emit('shiftStart', 1)"
        >
          下一日 ▶
        </button>
      </div>
      <div class="date-controls-right">
        <button
          type="button"
          class="date-step-btn"
          title="结束日期往前一日并重新回测"
          @click="emit('shiftEnd', -1)"
        >
          ◀ 上一日
        </button>
        <button
          type="button"
          class="date-step-btn"
          title="结束日期往后一日并重新回测"
          @click="emit('shiftEnd', 1)"
        >
          下一日 ▶
        </button>
      </div>
    </div>
    <div ref="container" class="kline-chart"></div>
  </div>
</template>

<style scoped>
.kline-chart-wrapper {
  position: relative;
  width: 100%;
}
.kline-date-controls {
  position: absolute;
  top: 2px;
  left: 0;
  right: 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  pointer-events: none;
  z-index: 10;
}
.date-controls-left,
.date-controls-right {
  pointer-events: auto;
  display: flex;
  gap: 6px;
  padding: 0 4px;
}
.date-step-btn {
  background: rgba(74, 158, 255, 0.12);
  color: #4a9eff;
  border: 1px solid rgba(74, 158, 255, 0.35);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  user-select: none;
  display: inline-flex;
  align-items: center;
}
.date-step-btn:hover {
  background: rgba(74, 158, 255, 0.25);
  border-color: #4a9eff;
  color: #70b4ff;
}
.date-step-btn:active {
  transform: scale(0.96);
}
.kline-chart {
  width: 100%;
  height: 500px;
}
</style>
