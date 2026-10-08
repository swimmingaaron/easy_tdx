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
  }>(),
  {
    groupId: 'backtest-charts-sync',
  },
)

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

function calcMA(dayCount: number, bars: Bar[]): (number | '-')[] {
  const result: (number | '-')[] = []
  for (let i = 0; i < bars.length; i++) {
    if (i < dayCount - 1) {
      result.push('-')
      continue
    }
    let sum = 0
    for (let j = 0; j < dayCount; j++) {
      sum += bars[i - j].close
    }
    result.push(Number((sum / dayCount).toFixed(2)))
  }
  return result
}

function calcTD(bars: Bar[]): { tdHigh: number[]; tdLow: number[] } {
  const n = bars.length
  const tdHigh = new Array(n).fill(0)
  const tdLow = new Array(n).fill(0)
  if (n < 5) return { tdHigh, tdLow }

  const a2 = new Array(n).fill(0)
  for (let i = 4; i < n; i++) {
    if (bars[i].close > bars[i - 4].close) {
      a2[i] = a2[i - 1] + 1
    } else {
      a2[i] = 0
    }
  }
  for (let i = 0; i < n; i++) {
    if (i > 0 && a2[i - 1] === 8 && a2[i] > a2[i - 1]) {
      const start = Math.max(0, i - 8)
      for (let j = start; j <= i; j++) {
        tdHigh[j] = a2[j]
      }
    }
  }
  const lastA2 = a2[n - 1]
  if (lastA2 >= 3 && lastA2 <= 8) {
    const start = Math.max(0, n - lastA2)
    for (let j = start; j < n; j++) {
      tdHigh[j] = a2[j]
    }
  }

  const b2 = new Array(n).fill(0)
  for (let i = 4; i < n; i++) {
    if (bars[i].close < bars[i - 4].close) {
      b2[i] = b2[i - 1] + 1
    } else {
      b2[i] = 0
    }
  }
  for (let i = 0; i < n; i++) {
    if (i > 0 && b2[i - 1] === 8 && b2[i] > b2[i - 1]) {
      const start = Math.max(0, i - 8)
      for (let j = start; j <= i; j++) {
        tdLow[j] = b2[j]
      }
    }
  }
  const lastB2 = b2[n - 1]
  if (lastB2 >= 3 && lastB2 <= 8) {
    const start = Math.max(0, n - lastB2)
    for (let j = start; j < n; j++) {
      tdLow[j] = b2[j]
    }
  }

  return { tdHigh, tdLow }
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

  // 计算 MA5, MA10, MA20, MA30, MA60
  const ma5 = calcMA(5, props.bars)
  const ma10 = calcMA(10, props.bars)
  const ma20 = calcMA(20, props.bars)
  const ma30 = calcMA(30, props.bars)
  const ma60 = calcMA(60, props.bars)

  // 计算九转序列 (TD Sequential)
  const { tdHigh, tdLow } = calcTD(props.bars)
  props.bars.forEach((b, i) => {
    const h = tdHigh[i]
    const l = tdLow[i]
    if (h === 9) {
      markPoints.push({
        name: '高9',
        coord: [i, b.high],
        value: '9',
        itemStyle: { color: '#14532d' },
        symbol: 'circle',
        symbolSize: 18,
        label: {
          show: true,
          formatter: '9',
          position: 'inside',
          color: '#ffffff',
          fontSize: 10,
          fontWeight: 'bold',
          offset: [0, 0],
        },
      })
    } else if (h >= 1) {
      markPoints.push({
        name: `高${h}`,
        coord: [i, b.high],
        value: String(h),
        itemStyle: { color: 'transparent' },
        symbol: 'none',
        symbolSize: 0,
        label: {
          show: true,
          formatter: String(h),
          position: 'top',
          color: '#ff00ff',
          fontSize: 10,
          fontWeight: 'bold',
          offset: [0, -2],
        },
      })
    }

    if (l === 9) {
      markPoints.push({
        name: '低9',
        coord: [i, b.low],
        value: '9',
        itemStyle: { color: '#881337' },
        symbol: 'circle',
        symbolSize: 18,
        label: {
          show: true,
          formatter: '9',
          position: 'inside',
          color: '#ffffff',
          fontSize: 10,
          fontWeight: 'bold',
          offset: [0, 0],
        },
      })
    } else if (l >= 1) {
      markPoints.push({
        name: `低${l}`,
        coord: [i, b.low],
        value: String(l),
        itemStyle: { color: 'transparent' },
        symbol: 'none',
        symbolSize: 0,
        label: {
          show: true,
          formatter: String(l),
          position: 'bottom',
          color: '#00ff00',
          fontSize: 10,
          fontWeight: 'bold',
          offset: [0, 2],
        },
      })
    }
  })

  // 组装 K 线名称：只显示股票代码，节省布局
  const cleanCode = props.code || (props.symbol ? props.symbol.split(':').pop() : '')
  const klineName = cleanCode ? `${cleanCode} K线` : 'K线'

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      alwaysShowContent: true,
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

        const m5 = ma5[dataIndex] !== '-' ? Number(ma5[dataIndex]).toFixed(2) : '-'
        const m10 = ma10[dataIndex] !== '-' ? Number(ma10[dataIndex]).toFixed(2) : '-'
        const m20 = ma20[dataIndex] !== '-' ? Number(ma20[dataIndex]).toFixed(2) : '-'
        const m30 = ma30[dataIndex] !== '-' ? Number(ma30[dataIndex]).toFixed(2) : '-'
        const m60 = ma60[dataIndex] !== '-' ? Number(ma60[dataIndex]).toFixed(2) : '-'

        let tdInfo = ''
        if (tdHigh[dataIndex] > 0) {
          tdInfo = `<span style="color:#ff00ff; font-weight:bold;">高${tdHigh[dataIndex]}</span>`
        } else if (tdLow[dataIndex] > 0) {
          tdInfo = `<span style="color:#00ff00; font-weight:bold;">低${tdLow[dataIndex]}</span>`
        }

        let html = `<div style="font-size:12px; line-height:1.6; min-width:180px;">`
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
        html += `<div style="margin-top:4px; padding-top:4px; border-top:1px dashed #383f4d; font-family:monospace; font-size:11px;">`
        html += `<span style="color:#ffd800;">MA5:${m5}</span> <span style="color:#d15cee;">MA10:${m10}</span> <span style="color:#4cd964;">MA20:${m20}</span> <span style="color:#f97316;">MA30:${m30}</span> <span style="color:#38bdf8;">MA60:${m60}</span>`
        if (tdInfo) {
          html += `<div>九转: ${tdInfo}</div>`
        }
        html += `</div>`
        html += `</div>`
        return html
      },
    },
    legend: {
      data: [klineName, 'MA5', 'MA10', 'MA20', 'MA30', 'MA60', '成交额'],
      top: 0,
      textStyle: { color: '#e6e8eb' },
    },
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
    },
    grid: [
      // 上图：K线
      { left: 70, right: 65, top: 32, height: '62%' },
      // 下图：成交额柱状图
      { left: 70, right: 65, top: '76%', height: '16%' },
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
      {
        name: 'MA5',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: ma5,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.2, color: '#ffd800' },
      },
      {
        name: 'MA10',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: ma10,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.2, color: '#d15cee' },
      },
      {
        name: 'MA20',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: ma20,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.2, color: '#4cd964' },
      },
      {
        name: 'MA30',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: ma30,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.2, color: '#f97316' },
      },
      {
        name: 'MA60',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: ma60,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.2, color: '#38bdf8' },
      },
      // 5: 成交额柱状图
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
  <div ref="container" class="kline-chart"></div>
</template>

<style scoped>
.kline-chart {
  width: 100%;
  height: 650px;
}
</style>
