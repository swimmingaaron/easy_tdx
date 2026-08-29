<script setup lang="ts">
// 净值曲线 + 回撤双轴图（ECharts line）。
// 左轴：净值总额(total)；右轴：回撤百分比(drawdown_pct，取负值向下显示）。

import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import echarts from '../echarts-setup'
import { fmt2 } from '../format'
import type { EquityPoint } from '../types'

const props = withDefaults(
  defineProps<{
    equity: EquityPoint[]
    groupId?: string
  }>(),
  {
    groupId: 'backtest-charts-sync',
  },
)

const container = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function render() {
  if (!container.value || props.equity.length === 0) return
  chart ??= echarts.init(container.value, 'dark')
  chart.group = props.groupId
  chart.setOption(buildOption(), true)
  echarts.connect(props.groupId)
}

function buildOption(): echarts.EChartsCoreOption {
  const keys = props.equity.map((e) => e.datetime)
  const isIntraday = keys.some((k) => {
    const time = k.slice(11, 19)
    return time && time !== '00:00:00'
  })
  const dates = keys.map((k) => (isIntraday ? k.replace('T', ' ').slice(5, 16) : k.slice(0, 10)))

  const totals = props.equity.map((e) => e.total)
  // 回撤百分比：后端 drawdown_pct 为正值（如 0.05），显示为 -5% 更直观
  const drawdowns = props.equity.map((e) => -e.drawdown_pct * 100)

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
      valueFormatter: (v: number | string) => fmt2(Number(v)),
    },
    legend: { data: ['净值', '回撤%'], top: 0 },
    grid: { left: 80, right: 65, top: 30, bottom: 40 },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: true,
      axisLine: { onZero: false },
      splitLine: { show: false },
      axisLabel: { formatter: (v: string) => v },
      axisPointer: {
        label: { show: true },
      },
    },
    yAxis: [
      {
        type: 'value',
        name: '净值',
        scale: true,
        position: 'left',
        splitLine: { lineStyle: { color: '#2a2e3a' } },
        axisLabel: { formatter: (v: number) => fmt2(v) },
      },
      {
        type: 'value',
        name: '回撤%',
        position: 'right',
        splitLine: { show: false },
        axisLabel: { formatter: (v: number) => fmt2(v) },
      },
    ],
    dataZoom: [{ type: 'inside', start: 0, end: 100 }],
    series: [
      {
        name: '净值',
        type: 'line',
        data: totals,
        smooth: false,
        symbol: 'none',
        lineStyle: { width: 1.5, color: '#4a9eff' },
        areaStyle: { opacity: 0.1 },
      },
      {
        name: '回撤%',
        type: 'line',
        data: drawdowns,
        yAxisIndex: 1,
        symbol: 'none',
        lineStyle: { width: 1, color: '#ef4146' },
        areaStyle: { opacity: 0.15, color: '#ef4146' },
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
watch(() => props.equity, render)
</script>

<template>
  <div ref="container" class="equity-chart"></div>
</template>

<style scoped>
.equity-chart {
  width: 100%;
  height: 300px;
}
</style>
