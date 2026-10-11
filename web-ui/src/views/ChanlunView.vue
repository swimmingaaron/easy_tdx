<script setup lang="ts">
// 缠论理论多周期立体共振分析系统页面（ChanlunView.vue）
// 功能：
// 1. 以最小周期K线为基准，同图立体呈现三周期笔、中枢、买卖点与三周期共振信号；
// 2. 实时行情与定时自动刷新（支持 3s/5s/10s 轮询，支持手动一键穿透刷新）；
// 3. 支持多周期（预设波段/长线/日内/游资组合 + 自由自定义三周期）；
// 4. 可以回溯（时间轴滑块、单步步进、自动播放推演历史当下缠论走势结构，无未来函数）；
// 5. 支持同图立体、三屏联动分屏、单周期模式切换。

import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { fetchChanlunResonance, fetchStockSuggestions } from '../api'
import echarts from '../echarts-setup'
import type {
  ChanlunResonanceResponse,
  StockSuggestItem,
} from '../types'

const route = useRoute()

// ── 标的与参数状态 ───────────────────────────────────────────────────────────
const code = ref('000001')
const searchKeyword = ref('')
const suggestList = ref<StockSuggestItem[]>([])
const isSearching = ref(false)

// 常用热门标的快捷标签
const popularStocks = [
  { code: '000001', name: '平安银行' },
  { code: '600519', name: '贵州茅台' },
  { code: '300750', name: '宁德时代' },
  { code: '002594', name: '比亚迪' },
  { code: '300308', name: '中际旭创' },
  { code: '601127', name: '赛力斯' },
]

// ── 多周期设置 ───────────────────────────────────────────────────────────────
const periodPresets = [
  { label: '标准 (日·30F·5F)', value: 'DAY,30F,5F' },
  { label: '波段 (周·日·30F)', value: 'WEEK,DAY,30F' },
  { label: '长线 (月·周·日)', value: 'MONTH,WEEK,DAY' },
  { label: '日内 (日·60F·15F)', value: 'DAY,60F,15F' },
  { label: '超短 (60F·30F·5F)', value: '60F,30F,5F' },
]
const activePreset = ref('DAY,30F,5F')
const periodHigh = ref('DAY')
const periodMid = ref('30F')
const periodLow = ref('5F')

const allPeriodOptions = [
  { key: 'MONTH', label: '月线 (MONTH)' },
  { key: 'WEEK', label: '周线 (WEEK)' },
  { key: 'DAY', label: '日线 (DAY)' },
  { key: '120F', label: '120分钟 (120F)' },
  { key: '60F', label: '60分钟 (60F)' },
  { key: '30F', label: '30分钟 (30F)' },
  { key: '15F', label: '15分钟 (15F)' },
  { key: '5F', label: '5分钟 (5F)' },
  { key: '1F', label: '1分钟 (1F)' },
]

// ── 图层控制 ───────────────────────────────────────────────────────────
const showHighBi = ref(true)
const showHighZs = ref(true)
const showMidBi = ref(true)
const showMidZs = ref(true)
const showLowBi = ref(true)
const showLowZs = ref(true)
const showMmdMarks = ref(true)
const showResonanceMarks = ref(false)
const subIndicator = ref<'amount' | 'macd' | 'none'>('amount')

// ── 实时刷新 ─────────────────────────────────────────────────────────────────
const autoRefresh = ref(false)
const refreshIntervalSec = ref(5)
let refreshTimer: ReturnType<typeof setInterval> | null = null
const lastRefreshTime = ref('')

// ── 回溯时光机状态 ───────────────────────────────────────────────────────────
const isBacktrackingMode = ref(false)
const backtrackDate = ref<string | null>(null)
const backtrackIndex = ref(0)
const isPlayingReplay = ref(false)
const replaySpeed = ref(1) // 1x, 2x, 4x
let replayTimer: ReturnType<typeof setInterval> | null = null

// ── 数据与图表 ───────────────────────────────────────────────────────────────
const loading = ref(false)
const errorMsg = ref('')
const chanData = ref<ChanlunResonanceResponse | null>(null)

const chartContainer = ref<HTMLDivElement | null>(null)
let chartInstance: echarts.ECharts | null = null

// ── 计算属性 ─────────────────────────────────────────────────────────────────
const currentPeriodsStr = computed(() => {
  return `${periodHigh.value},${periodMid.value},${periodLow.value}`
})

const availableDates = computed(() => {
  return chanData.value?.backtrack_timeline?.available_dates || []
})

const maxBacktrackIndex = computed(() => {
  return Math.max(0, availableDates.value.length - 1)
})

// ── 周期切换处理 ─────────────────────────────────────────────────────────────
function applyPreset(pStr: string) {
  activePreset.value = pStr
  const parts = pStr.split(',')
  if (parts.length === 3) {
    periodHigh.value = parts[0]
    periodMid.value = parts[1]
    periodLow.value = parts[2]
  }
  loadData()
}

const PERIOD_ORDER = ['MONTH', 'WEEK', 'DAY', '120F', '60F', '30F', '15F', '5F', '1F']

function onCustomPeriodChange(changed: 'high' | 'mid' | 'low' = 'low') {
  activePreset.value = ''
  let hIdx = PERIOD_ORDER.indexOf(periodHigh.value)
  let mIdx = PERIOD_ORDER.indexOf(periodMid.value)
  let lIdx = PERIOD_ORDER.indexOf(periodLow.value)
  if (hIdx < 0) hIdx = 2
  if (mIdx < 0) mIdx = 5
  if (lIdx < 0) lIdx = 7

  if (changed === 'low') {
    if (mIdx >= lIdx) mIdx = Math.max(lIdx - 1, 1)
    if (hIdx >= mIdx) hIdx = Math.max(mIdx - 1, 0)
  } else if (changed === 'mid') {
    if (hIdx >= mIdx) hIdx = Math.max(mIdx - 1, 0)
    if (lIdx <= mIdx) lIdx = Math.min(mIdx + 1, PERIOD_ORDER.length - 1)
  } else {
    if (mIdx <= hIdx) mIdx = Math.min(hIdx + 1, PERIOD_ORDER.length - 2)
    if (lIdx <= mIdx) lIdx = Math.min(mIdx + 1, PERIOD_ORDER.length - 1)
  }

  periodHigh.value = PERIOD_ORDER[hIdx]
  periodMid.value = PERIOD_ORDER[mIdx]
  periodLow.value = PERIOD_ORDER[lIdx]
  loadData()
}

let isDataLoading = false
let pendingBacktrackDate: string | null = null
let sliderDebounceTimer: ReturnType<typeof setTimeout> | null = null

async function triggerBacktrackLoad() {
  if (isDataLoading) {
    pendingBacktrackDate = backtrackDate.value
    return
  }
  await loadData()
  if (pendingBacktrackDate && pendingBacktrackDate !== backtrackDate.value) {
    backtrackDate.value = pendingBacktrackDate
    pendingBacktrackDate = null
    await loadData()
  }
}

// ── 数据加载 ─────────────────────────────────────────────────────────────────
async function loadData(forceRefresh = false) {
  if (!code.value) return
  isDataLoading = true
  if (!isBacktrackingMode.value) {
    loading.value = true
  }
  errorMsg.value = ''

  try {
    const reqCount = (currentPeriodsStr.value.includes('5F') || currentPeriodsStr.value.includes('1F')) ? 1500 : 300
    const res = await fetchChanlunResonance({
      code: code.value,
      periods: currentPeriodsStr.value,
      count: reqCount,
      cutoff_date: isBacktrackingMode.value ? (backtrackDate.value || undefined) : undefined,
      force_refresh: isBacktrackingMode.value ? false : forceRefresh,
    })
    chanData.value = res
    lastRefreshTime.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })

    // 初始化回溯滑块索引
    if (!isBacktrackingMode.value) {
      backtrackIndex.value = res.backtrack_timeline.total_bars - 1
      backtrackDate.value = res.summary.latest_date
    } else {
      const idx = res.backtrack_timeline.available_dates.indexOf(res.summary.latest_date)
      if (idx >= 0) backtrackIndex.value = idx
    }

    nextTick(() => {
      renderChart()
    })
  } catch (err: unknown) {
    errorMsg.value = `数据获取失败: ${err instanceof Error ? err.message : String(err)}`
  } finally {
    isDataLoading = false
    loading.value = false
  }
}

// ── 标的切换 ─────────────────────────────────────────────────────────────────
function selectStock(c: string) {
  code.value = c
  searchKeyword.value = ''
  suggestList.value = []
  exitBacktracking()
  loadData(true)
}

// 联想搜索
async function onSearchInput() {
  const kw = searchKeyword.value.trim()
  if (!kw) {
    suggestList.value = []
    return
  }
  isSearching.value = true
  try {
    const items = await fetchStockSuggestions(kw)
    suggestList.value = items.slice(0, 8)
  } catch {
    suggestList.value = []
  } finally {
    isSearching.value = false
  }
}

// ── 实时刷新控制 ─────────────────────────────────────────────────────────────
function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) {
    // 开启实时刷新自动退出回溯态
    if (isBacktrackingMode.value) {
      exitBacktracking()
    }
    startAutoRefresh()
  } else {
    stopAutoRefresh()
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  refreshTimer = setInterval(() => {
    if (!isBacktrackingMode.value && !loading.value) {
      loadData(true)
    }
  }, refreshIntervalSec.value * 1000)
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

// ── 回溯时光机控制 ───────────────────────────────────────────────────────────
function enterBacktracking() {
  isBacktrackingMode.value = true
  if (autoRefresh.value) {
    autoRefresh.value = false
    stopAutoRefresh()
  }
  if (!backtrackDate.value && availableDates.value.length > 0) {
    backtrackIndex.value = Math.max(0, availableDates.value.length - 10)
    backtrackDate.value = availableDates.value[backtrackIndex.value]
  }
  loadData()
}

function exitBacktracking() {
  isBacktrackingMode.value = false
  stopReplay()
  backtrackDate.value = null
  loadData()
}

function onSliderChange(e: Event) {
  const val = Number((e.target as HTMLInputElement).value)
  backtrackIndex.value = val
  if (availableDates.value[val]) {
    backtrackDate.value = availableDates.value[val]
    if (sliderDebounceTimer) clearTimeout(sliderDebounceTimer)
    sliderDebounceTimer = setTimeout(() => {
      triggerBacktrackLoad()
    }, 45)
  }
}

function stepBacktrack(step: number) {
  const nextIdx = backtrackIndex.value + step
  if (nextIdx >= 0 && nextIdx < availableDates.value.length) {
    backtrackIndex.value = nextIdx
    backtrackDate.value = availableDates.value[nextIdx]
    if (sliderDebounceTimer) clearTimeout(sliderDebounceTimer)
    sliderDebounceTimer = setTimeout(() => {
      triggerBacktrackLoad()
    }, 30)
  }
}

function toggleReplay() {
  if (isPlayingReplay.value) {
    stopReplay()
  } else {
    startReplay()
  }
}

function startReplay() {
  if (!isBacktrackingMode.value) {
    isBacktrackingMode.value = true
  }
  isPlayingReplay.value = true
  const interval = Math.max(400, Math.floor(1500 / replaySpeed.value))
  replayTimer = setInterval(() => {
    if (backtrackIndex.value >= availableDates.value.length - 1) {
      stopReplay()
      return
    }
    stepBacktrack(1)
  }, interval)
}

function stopReplay() {
  isPlayingReplay.value = false
  if (replayTimer) {
    clearInterval(replayTimer)
    replayTimer = null
  }
}

// ── ECharts 绘制逻辑 ─────────────────────────────────────────────────────────
function renderChart() {
  if (!chartContainer.value || !chanData.value) return

  if (!chartInstance) {
    chartInstance = echarts.init(chartContainer.value, 'dark')
    window.addEventListener('resize', handleResize)
  }

  const d = chanData.value
  const uc = d.unified_chart

  if (!uc || !uc.dates || uc.dates.length === 0) {
    chartInstance.clear()
    return
  }

  // 大级别笔 MarkLines (花姐标准：紫色粗线)
  const highBiLines = showHighBi.value
    ? uc.high_bis.map((b) => [
        { coord: b.start, lineStyle: { color: '#c084fc', width: 3.2, type: 'solid' } },
        { coord: b.end },
      ])
    : []

  // 中级别笔 MarkLines (花姐标准：金黄色中粗线)
  const midBiLines = showMidBi.value
    ? uc.mid_bis.map((b) => [
        { coord: b.start, lineStyle: { color: '#facc15', width: 2.2, type: 'solid' } },
        { coord: b.end },
      ])
    : []

  // 小级别笔 MarkLines (花姐标准：青蓝色细线)
  const lowBiLines = showLowBi.value
    ? uc.low_bis.map((b) => [
        { coord: b.start, lineStyle: { color: '#00e5ff', width: 1.5, type: 'solid' } },
        { coord: b.end },
      ])
    : []

  // 大级别中枢 MarkAreas (紫色半透明箱体)
  const highZsAreas = showHighZs.value
    ? uc.high_zss.map((zs) => [
        {
          name: `[${d.periods.high.name}中枢]`,
          coord: [zs.start_date, zs.zg],
          itemStyle: { color: 'rgba(147, 51, 234, 0.20)', borderColor: '#c084fc', borderWidth: 1.2, borderType: 'dashed' },
          label: { show: true, position: 'top', color: '#c084fc', fontSize: 10, formatter: `[${d.periods.high.name}紫色中枢]` },
        },
        { coord: [zs.end_date, zs.zd] },
      ])
    : []

  // 中级别中枢 MarkAreas (黄色半透明箱体)
  const midZsAreas = showMidZs.value
    ? uc.mid_zss.map((zs) => [
        {
          name: `[${d.periods.mid.name}中枢]`,
          coord: [zs.start_date, zs.zg],
          itemStyle: { color: 'rgba(202, 138, 4, 0.20)', borderColor: '#facc15', borderWidth: 1.0, borderType: 'dashed' },
          label: { show: true, position: 'top', color: '#facc15', fontSize: 10, formatter: `[${d.periods.mid.name}黄色中枢]` },
        },
        { coord: [zs.end_date, zs.zd] },
      ])
    : []

  // 小级别中枢 MarkAreas (微观青蓝箱体)
  const lowZsAreas = showLowZs.value
    ? uc.low_zss.map((zs) => [
        {
          name: `[${d.periods.low.name}中枢]`,
          coord: [zs.start_date, zs.zg],
          itemStyle: { color: 'rgba(2, 132, 199, 0.18)', borderColor: '#00e5ff', borderWidth: 0.8, borderType: 'dotted' },
          label: { show: true, position: 'insideTopLeft', color: '#00e5ff', fontSize: 9, formatter: `[${d.periods.low.name}微观中枢]` },
        },
        { coord: [zs.end_date, zs.zd] },
      ])
    : []

  const isDark = document.documentElement.classList.contains('dark')

  // 多级别买卖点同图呈现 markPoints
  const mmdMarkPoints = showMmdMarks.value
    ? uc.mmd_marks.map((m) => {
        const isBig = m.label.includes('大级别') || m.label.includes('大1') || m.label.includes('大2')
        const isMid = m.label.includes('次')
        let color = m.is_buy ? '#ef4444' : '#10b981'
        if (isBig) {
          color = '#9333ea'
        } else if (isMid) {
          color = m.is_buy ? '#f59e0b' : '#d97706'
        }

        let textColor, textBorderColor
        if (isDark) {
          textColor = isMid && m.is_buy ? '#fef08a' : (m.is_buy ? '#ffffff' : '#ecfdf5')
          textBorderColor = 'rgba(0, 0, 0, 0.9)'
        } else {
          textColor = isMid ? (m.is_buy ? '#78350f' : '#9a3412') : (m.is_buy ? '#991b1b' : '#064e3b')
          textBorderColor = '#ffffff'
        }

        return {
          name: m.type,
          coord: m.coord,
          value: m.label,
          symbol: m.is_buy ? 'pin' : 'arrow',
          symbolRotate: m.is_buy ? 0 : 180,
          symbolSize: isBig ? 32 : (isMid ? 28 : 26),
          itemStyle: { 
            color,
            borderColor: isDark ? 'rgba(255, 255, 255, 0.35)' : 'rgba(0, 0, 0, 0.2)',
            borderWidth: 1,
          },
          label: {
            show: true,
            color: textColor,
            textBorderColor: textBorderColor,
            textBorderWidth: 2.5,
            fontWeight: 'bold',
            fontSize: 9.5,
          },
        }
      })
    : []

  // 三周期立体共振买卖点 markPoints & 垂直穿透引导线
  const resonanceMarkPoints = showResonanceMarks.value
    ? uc.res_marks.map((r) => {
        const isBuy = r.direction === 'BUY'
        const labelColor = isDark ? '#ffffff' : (isBuy ? '#92400e' : '#0e7490')
        const labelBorderColor = isDark ? '#000000' : '#ffffff'

        return {
          name: r.pattern_name,
          coord: r.coord,
          value: r.label,
          symbol: 'diamond',
          symbolSize: 32,
          itemStyle: {
            color: isBuy ? '#ffd600' : '#00e5ff',
            borderColor: isDark ? '#ffffff' : '#0f172a',
            borderWidth: 1.5,
            shadowBlur: 8,
            shadowColor: isBuy ? '#ffd600' : '#00e5ff',
          },
          label: {
            show: true,
            position: isBuy ? 'bottom' : 'top',
            color: labelColor,
            textBorderColor: labelBorderColor,
            textBorderWidth: 2.5,
            fontWeight: 'bold',
            fontSize: 10.5,
            formatter: r.label,
          },
        }
      })
    : []

  const resonanceVerticalLines = showResonanceMarks.value
    ? uc.res_marks.map((r) => {
        const isBuy = r.direction === 'BUY'
        const tagColor = isDark
          ? (isBuy ? '#ffd600' : '#00e5ff')
          : (isBuy ? '#b45309' : '#0284c7')
        return {
          xAxis: r.date,
          lineStyle: {
            color: isBuy ? 'rgba(255, 214, 0, 0.85)' : 'rgba(0, 229, 255, 0.85)',
            width: 1.5,
            type: 'dashed',
          },
          label: {
            show: true,
            position: 'end',
            formatter: `★ ${r.grade}共振`,
            color: tagColor,
            textBorderColor: isDark ? '#000000' : '#ffffff',
            textBorderWidth: 2.5,
            fontSize: 10,
            fontWeight: 'bold',
          },
        }
      })
    : []

  // 副图指标配置 (默认成交额，不要 MACD)
  const hasSub = subIndicator.value !== 'none'
  const isSubAmount = subIndicator.value === 'amount'
  const isSubMacd = subIndicator.value === 'macd'
  const macdData = uc.macd || { hist: [], dif: [], dea: [] }

  const subSeries: any[] = []
  if (isSubAmount) {
    const amountsData = (uc.amounts && uc.amounts.length > 0)
      ? uc.amounts
      : (uc.volumes || []).map((v) => [v[0], v[1] * (uc.candles[v[0]] ? uc.candles[v[0]][1] : 0), v[2]] as [number, number, number])
    subSeries.push({
      name: '成交额',
      type: 'bar',
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: amountsData.map((v) => ({
        value: v[1],
        itemStyle: { color: v[2] >= 0 ? '#ef4146' : '#089981' },
      })),
      barWidth: '55%',
      barMaxWidth: 14,
    })
  } else if (isSubMacd) {
    subSeries.push(
      {
        name: 'MACD',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: macdData.hist.map((v) => ({
          value: v,
          itemStyle: { color: v >= 0 ? '#ef4146' : '#089981' },
        })),
        barWidth: '55%',
        barMaxWidth: 14,
      },
      {
        name: 'DIF',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: macdData.dif,
        lineStyle: { color: '#ffffff', width: 1.2 },
        symbol: 'none',
        markPoint: {
          symbolSize: 22,
          data: (uc.macd_marks || []).map((m: any) => ({
            name: m.label,
            coord: [m.date, m.dif],
            value: m.label,
            symbol: 'triangle',
            symbolRotate: m.type === 'bottom' ? 0 : 180,
            itemStyle: {
              color: m.type === 'bottom' ? '#ef4444' : '#10b981',
              borderColor: '#ffffff',
              borderWidth: 1.2,
            },
            label: {
              show: true,
              position: m.type === 'bottom' ? 'bottom' : 'top',
              color: m.type === 'bottom' ? '#f87171' : '#34d399',
              fontWeight: 'bold',
              fontSize: 9.5,
              formatter: m.label,
            },
          })),
        },
      },
      {
        name: 'DEA',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: macdData.dea,
        lineStyle: { color: '#ffd600', width: 1.2 },
        symbol: 'none',
      }
    )
  }

  const option: echarts.EChartsCoreOption = {
    backgroundColor: '#131722',
    animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', lineStyle: { color: '#888888', width: 1, type: 'dashed' } },
      backgroundColor: 'rgba(24, 27, 39, 0.95)',
      borderColor: '#363c4e',
      borderWidth: 1,
      textStyle: { color: '#d1d4dc', fontSize: 12 },
      formatter: (params: any) => {
        if (!Array.isArray(params) || params.length === 0) return ''
        const dateStr = params[0].name
        const idx = params[0].dataIndex
        const kParam = params.find((p: any) => p.seriesType === 'candlestick')
        let html = `<div style="font-weight:bold; margin-bottom:4px; color:#ffffff;">📅 ${dateStr}</div>`
        if (kParam && kParam.value) {
          const [, open, close, low, high] = kParam.value
          const isUp = close >= open
          const color = isUp ? '#ef4146' : '#089981'
          const curAmt = (uc.amounts && uc.amounts[idx]) ? uc.amounts[idx][1] : ((uc.volumes && uc.volumes[idx]) ? uc.volumes[idx][1] * close : 0)
          let amtStr = '--'
          if (curAmt >= 1e8) amtStr = `¥${(curAmt / 1e8).toFixed(2)}亿`
          else if (curAmt >= 1e4) amtStr = `¥${(curAmt / 1e4).toFixed(1)}万`
          else if (curAmt > 0) amtStr = `¥${curAmt.toFixed(0)}元`

          html += `<div style="color:${color}; margin-bottom:4px;">
            开: <b>${open.toFixed(2)}</b> 高: <b>${high.toFixed(2)}</b> 低: <b>${low.toFixed(2)}</b> 收: <b>${close.toFixed(2)}</b>
            <span style="margin-left:8px; color:#cbd5e1;">额: <b>${amtStr}</b></span>
          </div>`
        }
        // 匹配共振点
        const matchedRes = uc.res_marks.find((r) => r.date === dateStr)
        if (matchedRes) {
          const isBuy = matchedRes.direction === 'BUY'
          const resBg = isDark ? (isBuy ? 'rgba(239, 68, 68, 0.22)' : 'rgba(16, 185, 129, 0.22)') : (isBuy ? 'rgba(254, 226, 226, 0.95)' : 'rgba(209, 250, 229, 0.95)')
          const resBorder = isBuy ? '#ef4444' : '#10b981'
          const resColor = isDark ? (isBuy ? '#fca5a5' : '#86efac') : (isBuy ? '#991b1b' : '#064e3b')
          html += `<div style="padding:4px 6px; background:${resBg}; border:1px solid ${resBorder}; border-radius:4px; margin-top:4px; font-weight:bold; color:${resColor}; font-size:11px;">
            ${matchedRes.pattern_name} [${matchedRes.grade}级] ¥${matchedRes.price.toFixed(2)}
          </div>`
        }
        // 匹配 MACD 背离点
        const matchedMacd = (uc.macd_marks || []).find((m: any) => m.date === dateStr)
        if (matchedMacd) {
          const isBottom = matchedMacd.type === 'bottom'
          const macdBg = isDark ? (isBottom ? 'rgba(239, 68, 68, 0.25)' : 'rgba(16, 185, 129, 0.25)') : (isBottom ? 'rgba(254, 226, 226, 0.95)' : 'rgba(209, 250, 229, 0.95)')
          const macdBorder = isBottom ? '#ef4444' : '#10b981'
          const macdColor = isDark ? (isBottom ? '#fca5a5' : '#86efac') : (isBottom ? '#991b1b' : '#064e3b')
          html += `<div style="padding:4px 6px; background:${macdBg}; border: 1px solid ${macdBorder}; border-radius:4px; margin-top:4px; font-weight:bold; color:${macdColor}; font-size:11px;">
            ${matchedMacd.label}: ${matchedMacd.msg}
          </div>`
        }
        return html
      },
    },
    legend: {
      data: [
        '基准K线',
        `大级别笔(${d.periods.high.name})`,
        `中级别笔(${d.periods.mid.name})`,
        `小级别笔(${d.periods.low.name})`,
        ...(isSubAmount ? ['成交额'] : (isSubMacd ? ['MACD'] : [])),
      ],
      selected: {
        基准K线: true,
        [`大级别笔(${d.periods.high.name})`]: showHighBi.value,
        [`中级别笔(${d.periods.mid.name})`]: showMidBi.value,
        [`小级别笔(${d.periods.low.name})`]: showLowBi.value,
        成交额: true,
        MACD: true,
      },
      top: 10,
      textStyle: { color: '#a0a6b5', fontSize: 12 },
    },
    grid: [
      { left: '3.5%', right: '3.5%', top: '7%', height: hasSub ? '63%' : '82%' },
      { left: '3.5%', right: '3.5%', top: '74%', height: hasSub ? '18%' : '0%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: uc.dates,
        gridIndex: 0,
        axisLine: { lineStyle: { color: '#2a2e39' } },
        axisLabel: { show: !hasSub, color: '#888888', fontSize: 11 },
        splitLine: { show: true, lineStyle: { color: '#1e222d', type: 'dashed' } },
      },
      {
        type: 'category',
        data: uc.dates,
        gridIndex: 1,
        show: hasSub,
        axisLine: { lineStyle: { color: '#2a2e39' } },
        axisLabel: { color: '#888888', fontSize: 11 },
        splitLine: { show: true, lineStyle: { color: '#1e222d', type: 'dashed' } },
      },
    ],
    yAxis: [
      {
        type: 'value',
        scale: true,
        gridIndex: 0,
        position: 'right',
        splitLine: { lineStyle: { color: '#1e222d' } },
        axisLine: { lineStyle: { color: '#2a2e39' } },
        axisLabel: { color: '#888888', fontSize: 11 },
      },
      {
        type: 'value',
        scale: true,
        gridIndex: 1,
        show: hasSub,
        position: 'right',
        splitLine: { lineStyle: { color: '#1e222d' } },
        axisLine: { lineStyle: { color: '#2a2e39' } },
        axisLabel: {
          color: '#888888',
          fontSize: 10,
          formatter: isSubAmount
            ? (val: any) => {
                const n = Number(val)
                if (n >= 1e8) return `${(n / 1e8).toFixed(1)}亿`
                if (n >= 1e4) return `${(n / 1e4).toFixed(0)}万`
                return String(n)
              }
            : undefined,
        },
      },
    ],
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: [0, 1],
        minValueSpan: 20,
        start: Math.max(0, 100 - (110 / uc.dates.length) * 100),
        end: 100,
      },
      {
        type: 'slider',
        xAxisIndex: [0, 1],
        top: '94%',
        height: 18,
        minValueSpan: 20,
        borderColor: '#2a2e39',
        backgroundColor: '#181b27',
        fillerColor: 'rgba(41, 98, 255, 0.25)',
        textStyle: { color: '#888888', fontSize: 10 },
        start: Math.max(0, 100 - (110 / uc.dates.length) * 100),
        end: 100,
      },
    ],
    series: [
      {
        name: '基准K线',
        type: 'candlestick',
        barWidth: '55%',
        barMaxWidth: 14,
        data: uc.candles,
        itemStyle: {
          color: '#ef4146',
          color0: '#089981',
          borderColor: '#ef4146',
          borderColor0: '#089981',
        },
        markPoint: {
          data: [...mmdMarkPoints, ...resonanceMarkPoints],
        },
        markLine: {
          data: [...resonanceVerticalLines, ...highBiLines, ...midBiLines, ...lowBiLines] as any,
          symbol: ['circle', 'circle'],
          symbolSize: 4,
        },
        markArea: {
          data: [...highZsAreas, ...midZsAreas, ...lowZsAreas] as any,
        },
      },
      {
        name: `大级别笔(${d.periods.high.name})`,
        type: 'line',
        data: [],
        lineStyle: { color: '#c084fc', width: 3.2 },
      },
      {
        name: `中级别笔(${d.periods.mid.name})`,
        type: 'line',
        data: [],
        lineStyle: { color: '#facc15', width: 2.2 },
      },
      {
        name: `小级别笔(${d.periods.low.name})`,
        type: 'line',
        data: [],
        lineStyle: { color: '#00e5ff', width: 1.5 },
      },
      ...subSeries,
    ],
  }

  chartInstance.setOption(option, true)
}

function handleResize() {
  chartInstance?.resize()
}

function zoomChart(factor: number) {
  if (!chartInstance) return
  const opt = chartInstance.getOption() as any
  if (!opt || !opt.dataZoom || !opt.dataZoom[0]) return
  let start = opt.dataZoom[0].start ?? 40
  let end = opt.dataZoom[0].end ?? 100
  const span = end - start
  const totalBars = chanData.value?.unified_chart?.dates?.length || 100
  const minSpan = Math.min(100, (20 / totalBars) * 100)
  const newSpan = Math.max(minSpan, Math.min(100, span * factor))
  const delta = (newSpan - span) / 2
  let newStart = Math.max(0, start - delta)
  let newEnd = Math.min(100, end + delta)
  if (newStart === 0) newEnd = Math.min(100, newStart + newSpan)
  if (newEnd === 100) newStart = Math.max(0, newEnd - newSpan)
  chartInstance.dispatchAction({
    type: 'dataZoom',
    start: newStart,
    end: newEnd,
  })
}

function handleKeyDown(e: KeyboardEvent) {
  if (document.activeElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    zoomChart(0.8)
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    zoomChart(1.25)
  }
}

// ── 生命周期 ─────────────────────────────────────────────────────────────────
onMounted(() => {
  const qCode = (route.query.code || route.query.symbol) as string | undefined
  if (qCode) {
    code.value = qCode
  }
  loadData(true)
  window.addEventListener('keydown', handleKeyDown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeyDown)
  stopAutoRefresh()
  stopReplay()
  if (chartInstance) {
    window.removeEventListener('resize', handleResize)
    chartInstance.dispose()
    chartInstance = null
  }
})
</script>

<template>
  <div class="chanlun-container">
    <!-- 顶部状态与工具栏 -->
    <header class="chanlun-toolbar">
      <div class="toolbar-left">
        <div class="title-badge">
          <span class="main-title">缠论多周期立体共振</span>
          <span class="sub-tag">chanlun_resonance_kline</span>
        </div>

        <!-- 标的输入与联想 -->
        <div class="stock-search-wrap">
          <input
            v-model="searchKeyword"
            type="text"
            placeholder="输入代码/名称/拼音"
            class="stock-input"
            @input="onSearchInput"
            @keyup.enter="selectStock(searchKeyword)"
          />
          <button class="search-btn" @click="selectStock(searchKeyword)">切换标的</button>

          <!-- 搜索下拉 -->
          <ul v-if="suggestList.length > 0" class="suggest-dropdown">
            <li
              v-for="item in suggestList"
              :key="item.symbol"
              @click="selectStock(item.code)"
            >
              <span class="s-code">{{ item.code }}</span>
              <span class="s-name">{{ item.name }}</span>
              <span class="s-mkt">{{ item.market }}</span>
            </li>
          </ul>
        </div>

        <!-- 热门快速切换 -->
        <div class="popular-tags">
          <span
            v-for="stk in popularStocks"
            :key="stk.code"
            class="tag"
            :class="{ active: stk.code === code }"
            @click="selectStock(stk.code)"
          >
            {{ stk.name }}
          </span>
        </div>
      </div>

      <!-- 右侧：实时与回溯切换控制器 -->
      <div class="toolbar-right">
        <!-- 实时刷新开关 -->
        <div class="refresh-box">
          <button
            class="tool-btn"
            :class="{ active: autoRefresh, pulsing: autoRefresh }"
            @click="toggleAutoRefresh"
            :title="autoRefresh ? '点击暂停实时轮询' : '点击开启实时自动刷新'"
          >
            <span class="dot" :class="{ live: autoRefresh }"></span>
            {{ autoRefresh ? '实时更新中' : '实时刷新已暂停' }}
          </button>
          <select
            v-if="autoRefresh"
            v-model="refreshIntervalSec"
            class="interval-select"
            @change="startAutoRefresh"
          >
            <option :value="3">3秒</option>
            <option :value="5">5秒</option>
            <option :value="10">10秒</option>
          </select>
          <button class="icon-btn" @click="loadData(true)" title="立即刷新最新K线数据">
            🔄
          </button>
        </div>

        <!-- 回溯模式切换按钮 -->
        <div class="mode-switch-box">
          <button
            class="mode-btn"
            :class="{ active: !isBacktrackingMode }"
            @click="exitBacktracking"
          >
            ⚡ 实时最新
          </button>
          <button
            class="mode-btn"
            :class="{ active: isBacktrackingMode }"
            @click="enterBacktracking"
          >
            🕰️ 历史回溯
          </button>
        </div>
      </div>
    </header>

    <!-- 标的行情信息条 & 多周期立体定调 -->
    <section v-if="chanData" class="market-overview-card">
      <div class="stock-info">
        <h2 class="name">{{ chanData.name }}</h2>
        <span class="code">{{ chanData.code }}</span>
        <span
          class="price"
          :class="{ up: chanData.summary.change_pct >= 0, down: chanData.summary.change_pct < 0 }"
        >
          ¥{{ chanData.summary.latest_price.toFixed(2) }}
        </span>
        <span
          class="pct"
          :class="{ up: chanData.summary.change_pct >= 0, down: chanData.summary.change_pct < 0 }"
        >
          {{ chanData.summary.change_pct >= 0 ? '+' : '' }}{{ chanData.summary.change_pct }}%
        </span>
        <span class="time">时刻: {{ chanData.summary.latest_date }}</span>
      </div>

      <!-- 三级多空定态 -->
      <div class="states-summary">
        <div class="state-chip high">
          <span class="chip-title">【大级别·{{ chanData.periods.high.name }}】</span>
          <span class="chip-val">{{ chanData.summary.high_state.detail }}</span>
        </div>
        <div class="state-chip mid">
          <span class="chip-title">【中级别·{{ chanData.periods.mid.name }}】</span>
          <span class="chip-val">{{ chanData.summary.mid_state.detail }}</span>
        </div>
        <div class="state-chip low">
          <span class="chip-title">【基准小·{{ chanData.periods.low.name }}】</span>
          <span class="chip-val">{{ chanData.summary.low_state.detail }}</span>
        </div>
        <div class="state-chip resonance-stat">
          <span class="chip-title">共振买卖点</span>
          <span class="chip-badge">{{ chanData.resonances.length }} 处</span>
        </div>
      </div>
    </section>

    <!-- 周期配置与图层过滤器 -->
    <div class="controls-bar">
      <!-- 快捷预设周期 -->
      <div class="presets-row">
        <span class="label">周期组合:</span>
        <button
          v-for="p in periodPresets"
          :key="p.value"
          class="preset-btn"
          :class="{ active: activePreset === p.value }"
          @click="applyPreset(p.value)"
        >
          {{ p.label }}
        </button>

        <!-- 自定义选择器 -->
        <div class="custom-periods">
          <span>大:</span>
          <select v-model="periodHigh" @change="onCustomPeriodChange('high')">
            <option v-for="opt in allPeriodOptions" :key="opt.key" :value="opt.key">{{ opt.key }}</option>
          </select>
          <span>中:</span>
          <select v-model="periodMid" @change="onCustomPeriodChange('mid')">
            <option v-for="opt in allPeriodOptions" :key="opt.key" :value="opt.key">{{ opt.key }}</option>
          </select>
          <span>基准小:</span>
          <select v-model="periodLow" @change="onCustomPeriodChange('low')">
            <option v-for="opt in allPeriodOptions" :key="opt.key" :value="opt.key">{{ opt.key }}</option>
          </select>
        </div>
      </div>

      <!-- 图层开关 -->
      <div class="toggles-row">
        <span class="label">图层控制:</span>
        <label class="toggle-item high-layer">
          <input type="checkbox" v-model="showHighBi" @change="renderChart" />
          <span class="color-dot high-dot"></span> 大笔
        </label>
        <label class="toggle-item high-layer">
          <input type="checkbox" v-model="showHighZs" @change="renderChart" />
          大中枢
        </label>
        <label class="toggle-item mid-layer">
          <input type="checkbox" v-model="showMidBi" @change="renderChart" />
          <span class="color-dot mid-dot"></span> 中笔
        </label>
        <label class="toggle-item mid-layer">
          <input type="checkbox" v-model="showMidZs" @change="renderChart" />
          空中枢
        </label>
        <label class="toggle-item low-layer">
          <input type="checkbox" v-model="showLowBi" @change="renderChart" />
          <span class="color-dot low-dot"></span> 基准笔
        </label>
        <label class="toggle-item low-layer">
          <input type="checkbox" v-model="showLowZs" @change="renderChart" />
          基准中枢
        </label>
        <label class="toggle-item mmd-layer">
          <input type="checkbox" v-model="showMmdMarks" @change="renderChart" />
          买卖点
        </label>
        <label class="toggle-item res-layer">
          <input type="checkbox" v-model="showResonanceMarks" @change="renderChart" />
          ★共振信号
        </label>
        <span class="sub-sep">|</span>
        <span class="label">副图:</span>
        <label class="toggle-item sub-layer" :class="{ active: subIndicator === 'amount' }">
          <input type="radio" value="amount" v-model="subIndicator" @change="renderChart" />
          成交额
        </label>
        <label class="toggle-item sub-layer" :class="{ active: subIndicator === 'macd' }">
          <input type="radio" value="macd" v-model="subIndicator" @change="renderChart" />
          MACD
        </label>
        <label class="toggle-item sub-layer" :class="{ active: subIndicator === 'none' }">
          <input type="radio" value="none" v-model="subIndicator" @change="renderChart" />
          关闭
        </label>
      </div>
    </div>

    <!-- 历史回溯时光机操作条（激活时显示） -->
    <div v-if="isBacktrackingMode" class="backtrack-panel">
      <div class="backtrack-header">
        <div class="backtrack-title">
          <span>🕰️ 历史回溯推演态 (无未来函数)</span>
          <span class="current-cutoff">截断时间: <b>{{ backtrackDate || '最新' }}</b> (第 {{ backtrackIndex + 1 }} / {{ availableDates.length }} 根K线)</span>
        </div>
        <div class="backtrack-tools">
          <button class="step-btn" @click="stepBacktrack(-1)" :disabled="backtrackIndex <= 0">◀ 后退1根</button>
          <button class="step-btn" @click="stepBacktrack(1)" :disabled="backtrackIndex >= maxBacktrackIndex">▶ 前进1根</button>
          <button class="play-btn" :class="{ playing: isPlayingReplay }" @click="toggleReplay">
            {{ isPlayingReplay ? '⏸ 暂停推演' : '▶ 自动推演播放' }}
          </button>
          <select v-model="replaySpeed" class="speed-select" :disabled="isPlayingReplay">
            <option :value="1">1x 速度</option>
            <option :value="2">2x 速度</option>
            <option :value="4">4x 速度</option>
          </select>
          <button class="restore-btn" @click="exitBacktracking">⟲ 恢复实时最新</button>
        </div>
      </div>

      <!-- 时间轴滑块 -->
      <div class="slider-wrap">
        <span class="slider-bound">{{ chanData?.backtrack_timeline?.min_date }}</span>
        <input
          type="range"
          min="0"
          :max="maxBacktrackIndex"
          :value="backtrackIndex"
          class="time-slider"
          @input="onSliderChange"
        />
        <span class="slider-bound">{{ chanData?.backtrack_timeline?.max_date }}</span>
      </div>
    </div>

    <!-- 主图表区 -->
    <div class="chart-wrapper">
      <div v-if="loading" class="chart-loading-overlay">
        <div class="spinner"></div>
        <span>正在运行三周期缠论立体共振计算管道...</span>
      </div>
      <div v-if="errorMsg" class="chart-error-banner">
        ⚠️ {{ errorMsg }}
      </div>

      <div ref="chartContainer" class="main-echart"></div>
    </div>
  </div>
</template>

<style scoped>
.chanlun-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #131722;
  color: #d1d4dc;
  overflow-y: auto;
  padding: 12px 16px;
  gap: 10px;
}

/* 顶部工具栏 */
.chanlun-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #1e222d;
  border: 1px solid #2a2e39;
  border-radius: 8px;
  padding: 8px 14px;
  flex-shrink: 0;
}
.toolbar-left, .toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.title-badge {
  display: flex;
  flex-direction: column;
}
.main-title {
  font-size: 15px;
  font-weight: 700;
  color: #ffffff;
  letter-spacing: 0.5px;
}
.sub-tag {
  font-size: 10px;
  color: #787b86;
}

.stock-search-wrap {
  position: relative;
  display: flex;
  align-items: center;
}
.stock-input {
  background: #131722;
  border: 1px solid #363c4e;
  color: #ffffff;
  padding: 5px 10px;
  border-radius: 4px 0 0 4px;
  font-size: 13px;
  width: 140px;
  outline: none;
}
.stock-input:focus {
  border-color: #2962ff;
}
.search-btn {
  background: #2962ff;
  border: none;
  color: #ffffff;
  padding: 5px 10px;
  border-radius: 0 4px 4px 0;
  font-size: 12px;
  cursor: pointer;
}
.suggest-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  width: 220px;
  background: #1e222d;
  border: 1px solid #363c4e;
  border-radius: 4px;
  list-style: none;
  padding: 4px 0;
  margin: 4px 0 0 0;
  z-index: 100;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
}
.suggest-dropdown li {
  display: flex;
  justify-content: space-between;
  padding: 6px 10px;
  font-size: 12px;
  cursor: pointer;
}
.suggest-dropdown li:hover {
  background: #2a2e39;
}
.s-code {
  color: #ffd600;
  font-weight: bold;
}
.s-name {
  color: #ffffff;
}
.s-mkt {
  color: #787b86;
  font-size: 10px;
}

.popular-tags {
  display: flex;
  gap: 6px;
}
.popular-tags .tag {
  background: #181b27;
  border: 1px solid #2a2e39;
  color: #a0a6b5;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}
.popular-tags .tag:hover, .popular-tags .tag.active {
  color: #ffd600;
  border-color: #ffd600;
  background: rgba(255, 214, 0, 0.08);
}

.refresh-box {
  display: flex;
  align-items: center;
  gap: 6px;
}
.tool-btn {
  background: #181b27;
  border: 1px solid #363c4e;
  color: #a0a6b5;
  padding: 5px 10px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}
.tool-btn.active {
  color: #089981;
  border-color: #089981;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #787b86;
}
.dot.live {
  background: #089981;
  box-shadow: 0 0 6px #089981;
}
.interval-select {
  background: #131722;
  border: 1px solid #363c4e;
  color: #d1d4dc;
  font-size: 11px;
  padding: 3px 6px;
  border-radius: 4px;
}
.icon-btn {
  background: #181b27;
  border: 1px solid #363c4e;
  color: #ffffff;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
}

.mode-switch-box {
  display: flex;
  background: #131722;
  border: 1px solid #363c4e;
  border-radius: 4px;
  padding: 2px;
}
.mode-btn {
  background: transparent;
  border: none;
  color: #787b86;
  padding: 4px 10px;
  font-size: 12px;
  border-radius: 3px;
  cursor: pointer;
  transition: all 0.2s;
}
.mode-btn.active {
  background: #2962ff;
  color: #ffffff;
  font-weight: 600;
}

/* 标的行情信息条 */
.market-overview-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: linear-gradient(90deg, #181b27 0%, #1e222d 100%);
  border: 1px solid #2a2e39;
  border-radius: 8px;
  padding: 8px 16px;
  flex-shrink: 0;
}
.stock-info {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.stock-info .name {
  font-size: 18px;
  font-weight: 700;
  color: #ffffff;
}
.stock-info .code {
  font-size: 13px;
  color: #ffd600;
  font-weight: 600;
}
.stock-info .price {
  font-size: 20px;
  font-weight: 700;
}
.stock-info .pct {
  font-size: 14px;
  font-weight: 600;
}
.stock-info .time {
  font-size: 11px;
  color: #787b86;
}
.up { color: #ef4146; }
.down { color: #089981; }

.states-summary {
  display: flex;
  gap: 10px;
}
.state-chip {
  background: #131722;
  border: 1px solid #2a2e39;
  border-radius: 6px;
  padding: 4px 8px;
  display: flex;
  flex-direction: column;
  font-size: 11px;
}
.state-chip.high { border-left: 3px solid #e040fb; }
.state-chip.mid { border-left: 3px solid #00e5ff; }
.state-chip.low { border-left: 3px solid #ffd600; }
.chip-title {
  color: #787b86;
  font-size: 10px;
}
.chip-val {
  color: #ffffff;
  font-weight: 600;
}
.resonance-stat {
  border-left: 3px solid #ff4081;
  align-items: center;
  justify-content: center;
}
.chip-badge {
  color: #ffd600;
  font-weight: bold;
}

/* 控制栏 */
.controls-bar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: #181b27;
  border: 1px solid #242838;
  border-radius: 6px;
  padding: 8px 12px;
  flex-shrink: 0;
}
.presets-row, .toggles-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.label {
  color: #787b86;
  font-weight: 600;
}
.preset-btn {
  background: #1e222d;
  border: 1px solid #363c4e;
  color: #d1d4dc;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
}
.preset-btn.active {
  background: rgba(41, 98, 255, 0.2);
  border-color: #2962ff;
  color: #2962ff;
  font-weight: bold;
}
.custom-periods {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: 8px;
}
.custom-periods select {
  background: #131722;
  border: 1px solid #363c4e;
  color: #d1d4dc;
  font-size: 11px;
  padding: 2px 4px;
  border-radius: 3px;
}

.toggle-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  cursor: pointer;
  color: #a0a6b5;
}
.color-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.high-dot { background: #c084fc; }
.mid-dot { background: #facc15; }
.low-dot { background: #00e5ff; }
.sub-sep {
  color: #4b5563;
  margin: 0 4px;
}
.sub-layer input[type="radio"] {
  accent-color: #06b6d4;
  cursor: pointer;
}
.sub-layer.active {
  color: #38bdf8;
  font-weight: 600;
}

/* 回溯控制面板 */
.backtrack-panel {
  background: #1e222d;
  border: 1px solid #ff9800;
  border-radius: 6px;
  padding: 8px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  box-shadow: 0 2px 8px rgba(255, 152, 0, 0.15);
  flex-shrink: 0;
}
.backtrack-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.backtrack-title {
  color: #ff9800;
  font-weight: bold;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.current-cutoff {
  color: #ffffff;
  font-size: 12px;
}
.backtrack-tools {
  display: flex;
  align-items: center;
  gap: 6px;
}
.step-btn, .play-btn, .restore-btn, .speed-select {
  background: #181b27;
  border: 1px solid #363c4e;
  color: #d1d4dc;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
}
.play-btn.playing {
  background: #ff9800;
  color: #131722;
  font-weight: bold;
}
.restore-btn {
  background: #2962ff;
  color: #ffffff;
  border-color: #2962ff;
}
.slider-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
}
.slider-bound {
  font-size: 10px;
  color: #787b86;
}
.time-slider {
  flex: 1;
  accent-color: #ff9800;
  cursor: pointer;
}

/* 主图表 */
.chart-wrapper {
  position: relative;
  background: #181b27;
  border: 1px solid #2a2e39;
  border-radius: 8px;
  height: 754px;
  min-height: 624px;
  flex-shrink: 0;
}
.main-echart {
  width: 100%;
  height: 100%;
}
.chart-loading-overlay {
  position: absolute;
  inset: 0;
  background: rgba(19, 23, 34, 0.7);
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: 12px;
  color: #ffd600;
  font-size: 13px;
  z-index: 10;
}
.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid rgba(255, 214, 0, 0.2);
  border-top-color: #ffd600;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.chart-error-banner {
  position: absolute;
  top: 10px;
  left: 50%;
  transform: translateX(-50%);
  background: #d32f2f;
  color: #ffffff;
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 12px;
  z-index: 10;
}

/* 共振信号明细表 */
.resonance-table-section {
  background: #181b27;
  border: 1px solid #2a2e39;
  border-radius: 8px;
  padding: 10px 14px;
  flex-shrink: 0;
}
.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.t-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.star-icon {
  color: #ffd600;
  font-size: 16px;
}
.t-left h3 {
  font-size: 14px;
  font-weight: 700;
  color: #ffffff;
  margin: 0;
}
.table-count {
  font-size: 11px;
  color: #ffd600;
  background: rgba(255, 214, 0, 0.12);
  padding: 2px 6px;
  border-radius: 4px;
}
.t-tip {
  font-size: 11px;
  color: #787b86;
}
.signals-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.signals-table th {
  background: #1e222d;
  color: #888888;
  padding: 8px 10px;
  text-align: left;
  border-bottom: 1px solid #2a2e39;
  font-weight: 600;
}
.signals-table td {
  padding: 8px 10px;
  border-bottom: 1px solid #202433;
}
.clickable-row:hover {
  background: rgba(41, 98, 255, 0.12);
  cursor: pointer;
}
.dt-cell {
  color: #a0a6b5;
  font-family: monospace;
}
.dir-badge {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 3px;
  font-weight: bold;
  font-size: 11px;
}
.dir-badge.buy {
  background: rgba(239, 65, 70, 0.2);
  color: #ef4146;
}
.dir-badge.sell {
  background: rgba(8, 153, 129, 0.2);
  color: #089981;
}
.grade-badge {
  display: inline-block;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: bold;
}
.grade-badge.AAA {
  background: #d32f2f;
  color: #ffffff;
}
.grade-badge.AA {
  background: #f57c00;
  color: #ffffff;
}
.grade-badge.A {
  background: #1976d2;
  color: #ffffff;
}
.pattern-name {
  color: #ffffff;
  font-weight: 600;
}
.price-cell {
  font-family: monospace;
  font-weight: bold;
  color: #ffd600;
}
.detail-cell {
  color: #a0a6b5;
  font-size: 11px;
}
.empty-signals {
  padding: 20px;
  text-align: center;
  color: #787b86;
  font-size: 12px;
}
</style>
