<script setup lang="ts">
// 缠论理论多周期立体共振分析系统页面（ChanlunView.vue）
// 功能：
// 1. 以最小周期K线为基准，同图立体呈现三周期笔、中枢、买卖点与三周期共振信号；
// 2. 实时行情与定时自动刷新（30秒定时轮询刷新，支持手动一键穿透刷新）；
// 3. 支持多周期（预设波段/长线/日内/游资组合 + 自由自定义三周期）；
// 4. 可以回溯（时间轴滑块、单步步进、自动播放推演历史当下缠论走势结构，无未来函数）；
// 5. 支持同图立体、三屏联动分屏、单周期模式切换。

import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { fetchChanlunHotStocks, fetchChanlunResonance, fetchStockSuggestions, type ChanlunHotStockItem } from '../api'
import echarts from '../echarts-setup'
import type {
  ChanlunResonanceResponse,
  StockSuggestItem,
} from '../types'

const route = useRoute()

// ── 标的与参数状态 ───────────────────────────────────────────────────────────
function getInitialChanlunCode(): string {
  if (typeof window !== 'undefined') {
    const raw = (window.location.hash || '') + '&' + (window.location.search || '')
    const m = raw.match(/[?&#](?:code|symbol)=([0-9a-zA-Z]+)/i)
    if (m && m[1]) return m[1].trim().replace(/[^0-9a-zA-Z]/g, '')
  }
  return '000001'
}
const code = ref(getInitialChanlunCode())
const searchKeyword = ref('')
const suggestList = ref<StockSuggestItem[]>([])
const isSearching = ref(false)

// 常用热门标的快捷标签（支持实时随最小周期自动更新）
const popularStocks = ref<ChanlunHotStockItem[]>([
  { code: '000001', name: '平安银行' },
  { code: '600519', name: '贵州茅台' },
  { code: '300750', name: '宁德时代' },
  { code: '002594', name: '比亚迪' },
  { code: '300308', name: '中际旭创' },
  { code: '601127', name: '赛力斯' },
])

// ── 多周期设置 ───────────────────────────────────────────────────────────────
const periodPresets = [
  { label: '标准 (日·30F·5F)', value: 'DAY,30F,5F' },
  { label: '超短 (30F·5F·1F)', value: '30F,5F,1F' },
  { label: '波段 (周·日·30F)', value: 'WEEK,DAY,30F' },
  { label: '长线 (月·周·日)', value: 'MONTH,WEEK,DAY' },
  { label: '日内 (日·60F·15F)', value: 'DAY,60F,15F' },
  { label: '短线 (60F·30F·5F)', value: '60F,30F,5F' },
  { label: '1F (单周期)', value: '1F' },
  { label: '5F (单周期)', value: '5F' },
  { label: '15F (单周期)', value: '15F' },
  { label: '30F (单周期)', value: '30F' },
  { label: '60F (单周期)', value: '60F' },
  { label: '120F (单周期)', value: '120F' },
  { label: '日 (单周期)', value: 'DAY' },
  { label: '周 (单周期)', value: 'WEEK' },
  { label: '月 (单周期)', value: 'MONTH' },
]
// 窗口分屏模式：'quad' (默认四窗口: 2x2网格) | 'dual' (双窗口: 上下分屏对比) | 'single' (单窗口全屏)
const splitMode = ref<'quad' | 'dual' | 'single'>('quad')

// 窗口 1 周期 (默认: 周·日·30F)
const leftPeriods = ref('WEEK,DAY,30F')
const leftActivePreset = ref('WEEK,DAY,30F')
const leftPeriodHigh = ref('WEEK')
const leftPeriodMid = ref('DAY')
const leftPeriodLow = ref('30F')

// 窗口 2 周期 (默认: 月·周·日)
const w2Periods = ref('MONTH,WEEK,DAY')
const w2ActivePreset = ref('MONTH,WEEK,DAY')
const w2PeriodHigh = ref('MONTH')
const w2PeriodMid = ref('WEEK')
const w2PeriodLow = ref('DAY')

// 窗口 3 周期 (默认: 日·30F·5F)
const rightPeriods = ref('DAY,30F,5F')
const rightActivePreset = ref('DAY,30F,5F')
const rightPeriodHigh = ref('DAY')
const rightPeriodMid = ref('30F')
const rightPeriodLow = ref('5F')

// 窗口 4 周期 (默认: 30F·5F·1F)
const w4Periods = ref('30F,5F,1F')
const w4ActivePreset = ref('30F,5F,1F')
const w4PeriodHigh = ref('30F')
const w4PeriodMid = ref('5F')
const w4PeriodLow = ref('1F')

// 兼容单窗口时的主周期双向绑定 (代理到左窗)
const periodLow = computed({
  get: () => leftPeriodLow.value,
  set: (v) => { leftPeriodLow.value = v }
})

// 当前选中的回溯主控基准窗口：'left' (窗1) | 'w2' (窗2) | 'right' (窗3) | 'w4' (窗4)
const activeWindow = ref<'left' | 'w2' | 'right' | 'w4'>('left')
const activeWindowNum = computed(() => {
  if (activeWindow.value === 'w2') return 2
  if (activeWindow.value === 'right') return 3
  if (activeWindow.value === 'w4') return 4
  return 1
})

function getActiveWindowData(): ChanlunResonanceResponse | null {
  if (activeWindow.value === 'w2') return chanDataW2.value || chanDataLeft.value
  if (activeWindow.value === 'right') return chanDataRight.value || chanDataLeft.value
  if (activeWindow.value === 'w4') return chanDataW4.value || chanDataLeft.value
  return chanDataLeft.value || chanDataW2.value || chanDataRight.value || chanDataW4.value
}

function setActiveWindow(target: 'left' | 'w2' | 'right' | 'w4') {
  activeWindow.value = target
  const d = getActiveWindowData()
  if (d && d.backtrack_timeline) {
    const dates = d.backtrack_timeline.available_dates || []
    if (backtrackDate.value) {
      let idx = dates.indexOf(backtrackDate.value)
      if (idx < 0) {
        for (let i = dates.length - 1; i >= 0; i--) {
          if (dates[i] <= backtrackDate.value) {
            idx = i
            break
          }
        }
      }
      if (idx >= 0) backtrackIndex.value = idx
    } else {
      backtrackIndex.value = dates.length - 1
    }
  }
}

// ── 图层控制 ───────────────────────────────────────────────────────────
const showHighBi = ref(true)
const showHighZs = ref(true)
const showMidBi = ref(true)
const showMidZs = ref(true)
const showLowBi = ref(true)
const showLowZs = ref(true)
const showMmdMarks = ref(false)
const showResonanceMarks = ref(false)
const subIndicator = ref<'amount' | 'inflow' | 'macd' | 'rsi' | 'kdj' | 'expma' | 'none'>('amount')
const isKlineMerged = ref(false) // K线合并开关：严格按照缠论标准显示包含合并后的K线图，默认关闭
const activeLayersCount = computed(() => {
  let c = 0
  if (showHighBi.value) c++
  if (showHighZs.value) c++
  if (showMidBi.value) c++
  if (showMidZs.value) c++
  if (showLowBi.value) c++
  if (showLowZs.value) c++
  if (showMmdMarks.value) c++
  if (showResonanceMarks.value) c++
  return c
})

function setAllLayers(enabled: boolean) {
  showHighBi.value = enabled
  showHighZs.value = enabled
  showMidBi.value = enabled
  showMidZs.value = enabled
  showLowBi.value = enabled
  showLowZs.value = enabled
  showMmdMarks.value = enabled
  showResonanceMarks.value = enabled
  renderChart()
}

function setBiOnly() {
  showHighBi.value = true
  showHighZs.value = false
  showMidBi.value = true
  showMidZs.value = false
  showLowBi.value = true
  showLowZs.value = false
  showMmdMarks.value = false
  showResonanceMarks.value = false
  renderChart()
}

function onMainLayersSelect(e: Event) {
  const target = e.target as HTMLSelectElement
  const val = target.value
  if (!val) return
  if (val === '__ALL_ON__') {
    setAllLayers(true)
  } else if (val === '__ALL_OFF__') {
    setAllLayers(false)
  } else if (val === '__BI_ONLY__') {
    setBiOnly()
  } else if (val === 'highBi') {
    showHighBi.value = !showHighBi.value
  } else if (val === 'highZs') {
    showHighZs.value = !showHighZs.value
  } else if (val === 'midBi') {
    showMidBi.value = !showMidBi.value
  } else if (val === 'midZs') {
    showMidZs.value = !showMidZs.value
  } else if (val === 'lowBi') {
    showLowBi.value = !showLowBi.value
  } else if (val === 'lowZs') {
    showLowZs.value = !showLowZs.value
  } else if (val === 'mmd') {
    showMmdMarks.value = !showMmdMarks.value
  } else if (val === 'res') {
    showResonanceMarks.value = !showResonanceMarks.value
  }
  renderChart()
  target.value = ''
}

// 统一实时刷新周期：30秒
const REFRESH_INTERVAL_SECONDS = 30

function isTradeSession(): boolean {
  const now = new Date()
  const day = now.getDay()
  if (day === 0 || day === 6) return false
  const totalSec = now.getHours() * 3600 + now.getMinutes() * 60 + now.getSeconds()
  const morning = totalSec >= 33300 && totalSec <= 41430
  const afternoon = totalSec >= 46800 && totalSec <= 54330
  return morning || afternoon
}

// ── 实时刷新与休市判断 ─────────────────────────────────────────────────────────
const autoRefresh = ref(true)
const inTradeSession = ref(isTradeSession())
let refreshTimer: ReturnType<typeof setInterval> | null = null
let clockTimer: ReturnType<typeof setInterval> | null = null
const lastRefreshTime = ref('')

// ── 自选股状态管理 (watchlist.json) ───────────────────────────────────────────
const watchlistSymbols = ref<string[]>([])
const isInWatchlist = computed(() => {
  const c = code.value.replace(/[^0-9a-zA-Z]/g, '')
  return watchlistSymbols.value.includes(c)
})

async function fetchWatchlist() {
  try {
    const res = await fetch('/api/quotes/watchlist')
    if (res.ok) {
      const json = await res.json()
      if (Array.isArray(json.data)) {
        watchlistSymbols.value = json.data
      }
    }
  } catch (e) {
    console.debug('Failed to fetch watchlist:', e)
  }
}

async function toggleWatchlist() {
  const c = code.value.replace(/[^0-9a-zA-Z]/g, '')
  if (!c) return
  if (isInWatchlist.value) {
    watchlistSymbols.value = watchlistSymbols.value.filter(s => s !== c)
  } else {
    watchlistSymbols.value.unshift(c)
  }
  try {
    await fetch('/api/quotes/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbols: watchlistSymbols.value }),
    })
  } catch (e) {
    console.debug('Failed to save watchlist:', e)
  }
}

const periodLowLabel = computed(() => {
  const map: Record<string, string> = {
    MONTH: '月线',
    WEEK: '周线',
    DAY: '日线',
  }
  return map[periodLow.value] || periodLow.value
})

const periodLowSeconds = computed(() => {
  return REFRESH_INTERVAL_SECONDS
})

async function loadHotStocks() {
  try {
    const list = await fetchChanlunHotStocks(8)
    if (list && list.length > 0) {
      popularStocks.value = list
      return list
    }
  } catch {
    // keep default
  }
  return popularStocks.value
}

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
const chanDataLeft = ref<ChanlunResonanceResponse | null>(null)
const chanDataW2 = ref<ChanlunResonanceResponse | null>(null)
const chanDataRight = ref<ChanlunResonanceResponse | null>(null)
const chanDataW4 = ref<ChanlunResonanceResponse | null>(null)
const chanData = computed(() => chanDataLeft.value)

interface WinCandleInfo {
  priceStr: string
  chgStr: string
  colorClass: string
}

function getLatestCandleInfo(data: ChanlunResonanceResponse | null): WinCandleInfo | null {
  if (!data?.unified_chart?.candles || data.unified_chart.candles.length === 0) return null
  const candles = data.unified_chart.candles
  const lastIdx = candles.length - 1
  const close = Number(candles[lastIdx][1] || 0)
  const prevC = (lastIdx > 0 && candles[lastIdx - 1]) ? Number(candles[lastIdx - 1][1] || 0) : Number(candles[lastIdx][0] || 0)
  const chg = close - prevC
  const chgPct = prevC > 0 ? (chg / prevC * 100) : 0
  const isUp = chgPct > 0.0001
  const isDown = chgPct < -0.0001
  const colorClass = isUp ? 'color-up' : (isDown ? 'color-down' : 'color-flat')
  const chgSign = isUp ? '+' : ''
  let priceStr = close.toFixed(2)
  if (Math.abs(Math.round(close * 100) - close * 100) > 0.001) {
    priceStr = close.toFixed(3)
  }
  return {
    priceStr,
    chgStr: `${chgSign}${chgPct.toFixed(2)}%`,
    colorClass,
  }
}

const hoverCandleLeft = ref<WinCandleInfo | null>(null)
const hoverCandleW2 = ref<WinCandleInfo | null>(null)
const hoverCandleRight = ref<WinCandleInfo | null>(null)
const hoverCandleW4 = ref<WinCandleInfo | null>(null)

const hoverCandleDateLeft = ref<string | null>(null)
const hoverCandleDateW2 = ref<string | null>(null)
const hoverCandleDateRight = ref<string | null>(null)
const hoverCandleDateW4 = ref<string | null>(null)

const candleInfoLeft = computed(() => hoverCandleLeft.value || getLatestCandleInfo(chanDataLeft.value))
const candleInfoW2 = computed(() => hoverCandleW2.value || getLatestCandleInfo(chanDataW2.value))
const candleInfoRight = computed(() => hoverCandleRight.value || getLatestCandleInfo(chanDataRight.value))
const candleInfoW4 = computed(() => hoverCandleW4.value || getLatestCandleInfo(chanDataW4.value))

const chartContainerLeft = ref<HTMLDivElement | null>(null)
const chartContainerW2 = ref<HTMLDivElement | null>(null)
const chartContainerRight = ref<HTMLDivElement | null>(null)
const chartContainerW4 = ref<HTMLDivElement | null>(null)
let chartInstanceLeft: echarts.ECharts | null = null
let chartInstanceW2: echarts.ECharts | null = null
let chartInstanceRight: echarts.ECharts | null = null
let chartInstanceW4: echarts.ECharts | null = null

function setSplitMode(mode: 'quad' | 'dual' | 'single') {
  splitMode.value = mode
  nextTick(() => {
    handleResize()
    if (mode === 'quad' && (!chanDataW2.value || !chanDataRight.value || !chanDataW4.value)) {
      loadData()
    } else if (mode === 'dual' && !chanDataRight.value) {
      loadData()
    } else {
      renderChart()
    }
  })
}

// ── 计算属性 ─────────────────────────────────────────────────────────────────
const availableDates = computed(() => {
  const activeD = getActiveWindowData()
  return activeD?.backtrack_timeline?.available_dates || chanDataLeft.value?.backtrack_timeline?.available_dates || []
})

const maxBacktrackIndex = computed(() => {
  return Math.max(0, availableDates.value.length - 1)
})

// ── 周期切换处理 ─────────────────────────────────────────────────────────────
function applyWindowPreset(target: 'left' | 'w2' | 'right' | 'w4', pStr: string) {
  const parts = pStr.split(',')
  const pHigh = parts.length === 3 ? parts[0] : parts[0]
  const pMid = parts.length === 3 ? parts[1] : parts[0]
  const pLow = parts.length === 3 ? parts[2] : parts[0]
  if (target === 'left') {
    leftActivePreset.value = pStr
    leftPeriods.value = pStr
    leftPeriodHigh.value = pHigh
    leftPeriodMid.value = pMid
    leftPeriodLow.value = pLow
  } else if (target === 'w2') {
    w2ActivePreset.value = pStr
    w2Periods.value = pStr
    w2PeriodHigh.value = pHigh
    w2PeriodMid.value = pMid
    w2PeriodLow.value = pLow
  } else if (target === 'right') {
    rightActivePreset.value = pStr
    rightPeriods.value = pStr
    rightPeriodHigh.value = pHigh
    rightPeriodMid.value = pMid
    rightPeriodLow.value = pLow
  } else if (target === 'w4') {
    w4ActivePreset.value = pStr
    w4Periods.value = pStr
    w4PeriodHigh.value = pHigh
    w4PeriodMid.value = pMid
    w4PeriodLow.value = pLow
  }
  clearClientBacktrackCache()
  if (autoRefresh.value) {
    startAutoRefresh()
  }
  loadData()
}


// ── 客户端本地回溯分析结果内存缓存（同股票相同截断点 100% 内存瞬时渲染，免除向后端请求）──
const backtrackCache = new Map<string, ChanlunResonanceResponse>()

function getBacktrackCacheKey(c: string, p: string, cutoff?: string | null): string {
  return `${c}_${p}_${cutoff || 'LATEST'}`
}

function clearClientBacktrackCache() {
  backtrackCache.clear()
}

let isDataLoading = false
let backtrackRequestSeq = 0
let sliderDebounceTimer: ReturnType<typeof setTimeout> | null = null
let backtrackAbortController: AbortController | null = null

async function triggerBacktrackLoad() {
  const seq = ++backtrackRequestSeq
  if (isDataLoading && backtrackAbortController) {
    try { backtrackAbortController.abort() } catch {}
  }
  while (isDataLoading) {
    await new Promise(r => setTimeout(r, 20))
    if (seq !== backtrackRequestSeq) return
  }
  if (seq !== backtrackRequestSeq) return
  await loadData()
}

// ── 数据加载 ─────────────────────────────────────────────────────────────────
async function loadData(forceRefresh = false) {
  if (!code.value) return

  const cacheKey = getBacktrackCacheKey(code.value, leftPeriods.value, backtrackDate.value)

  // 1. 回溯模式下且非强制刷新，优先检查客户端内存缓存（0毫秒瞬时切换且绝无网络请求）
  if (isBacktrackingMode.value && backtrackDate.value && !forceRefresh && backtrackCache.has(cacheKey)) {
    const cached = backtrackCache.get(cacheKey)!
    chanDataLeft.value = cached
    const idx = cached.backtrack_timeline.available_dates.indexOf(cached.summary.latest_date)
    if (idx >= 0) backtrackIndex.value = idx
    nextTick(() => {
      renderChart()
    })
    isDataLoading = false
    return
  }

  if (backtrackAbortController) {
    try { backtrackAbortController.abort() } catch {}
  }
  backtrackAbortController = new AbortController()
  const signal = backtrackAbortController.signal
  const reqCode = code.value
  const reqDate = backtrackDate.value

  isDataLoading = true
  if (!isBacktrackingMode.value) {
    loading.value = true
  }
  errorMsg.value = ''

  try {
    // 借鉴 chanlun-pro：实时模式下使用 800 根 (单网络包最优上限，~17个交易日，微秒级加载)；回溯时光机模式使用 2500 根全量母数据
    const reqCount = isBacktrackingMode.value ? 2500 : ((leftPeriods.value.includes('5F') || leftPeriods.value.includes('1F')) ? 800 : 300)
    const cutoff = isBacktrackingMode.value ? (backtrackDate.value || undefined) : undefined
    const force = isBacktrackingMode.value ? false : forceRefresh

    const pLeft = fetchChanlunResonance({
      code: code.value,
      periods: leftPeriods.value,
      count: reqCount,
      cutoff_date: cutoff,
      force_refresh: force,
      signal,
    })
    const promises: Promise<ChanlunResonanceResponse>[] = [pLeft]

    if (splitMode.value === 'quad') {
      const pW2 = fetchChanlunResonance({
        code: code.value,
        periods: w2Periods.value,
        count: reqCount,
        cutoff_date: cutoff,
        force_refresh: force,
        signal,
      })
      const pRight = fetchChanlunResonance({
        code: code.value,
        periods: rightPeriods.value,
        count: reqCount,
        cutoff_date: cutoff,
        force_refresh: force,
        signal,
      })
      const pW4 = fetchChanlunResonance({
        code: code.value,
        periods: w4Periods.value,
        count: reqCount,
        cutoff_date: cutoff,
        force_refresh: force,
        signal,
      })
      promises.push(pW2, pRight, pW4)
    } else if (splitMode.value === 'dual') {
      const pRight = fetchChanlunResonance({
        code: code.value,
        periods: rightPeriods.value,
        count: reqCount,
        cutoff_date: cutoff,
        force_refresh: force,
        signal,
      })
      promises.push(pRight)
    }

    const results = await Promise.all(promises)

    // 过滤过期请求响应，防止由于网络乱序造成旧数据覆盖新截断点
    if (reqCode !== code.value) return
    if (isBacktrackingMode.value && reqDate !== backtrackDate.value) return

    chanDataLeft.value = results[0]
    if (splitMode.value === 'quad') {
      chanDataW2.value = results[1] || null
      chanDataRight.value = results[2] || null
      chanDataW4.value = results[3] || null
    } else if (splitMode.value === 'dual') {
      if (results[1]) {
        chanDataRight.value = results[1]
      }
    }
    lastRefreshTime.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })

    // 存入客户端回溯缓存池
    backtrackCache.set(cacheKey, results[0])
    if (!isBacktrackingMode.value && results[0].summary.latest_date) {
      backtrackCache.set(getBacktrackCacheKey(code.value, leftPeriods.value, results[0].summary.latest_date), results[0])
    }

    // 初始化回溯滑块索引 (基于当前主控窗口)
    const activeD = getActiveWindowData() || results[0]
    if (activeD && activeD.backtrack_timeline) {
      if (!isBacktrackingMode.value) {
        backtrackIndex.value = activeD.backtrack_timeline.total_bars - 1
        backtrackDate.value = activeD.summary.latest_date
      } else {
        const curDate = backtrackDate.value || activeD.summary.latest_date
        const idx = activeD.backtrack_timeline.available_dates.indexOf(curDate)
        if (idx >= 0) backtrackIndex.value = idx
      }
    }

    nextTick(() => {
      renderChart()
    })
  } catch (err: unknown) {
    if (err instanceof Error && err.name === 'AbortError') {
      return
    }
    errorMsg.value = `数据获取失败: ${err instanceof Error ? err.message : String(err)}`
  } finally {
    isDataLoading = false
    loading.value = false
  }
}

// ── 标的切换 ─────────────────────────────────────────────────────────────────
async function selectStock(c: string) {
  const clean = (c || '').trim()
  if (!clean) return

  let targetCode = clean
  // 如果输入的不是 6 位数字代码（如拼音 rssh 或中文名称），自动解析为真实 6 位代码
  if (!/^\d{6}$/.test(clean)) {
    if (suggestList.value.length > 0) {
      targetCode = suggestList.value[0].code
    } else {
      try {
        const items = await fetchStockSuggestions(clean)
        if (items && items.length > 0) {
          targetCode = items[0].code
        }
      } catch {
        // fallback
      }
    }
  }

  code.value = targetCode
  searchKeyword.value = ''
  suggestList.value = []
  clearClientBacktrackCache()
  exitBacktracking()
  loadData(false)
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
  if (!inTradeSession.value) {
    loadData(true)
    loadHotStocks()
    return
  }
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
    inTradeSession.value = isTradeSession()
    if (!isBacktrackingMode.value && !loading.value && inTradeSession.value && autoRefresh.value) {
      loadData(false) // 允许命中后端智能增量缓存，避免击穿
      loadHotStocks() // 热门股票也随之实时更新
    }
  }, REFRESH_INTERVAL_SECONDS * 1000)
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

// 鼠标双击K线时调用：将缠论K线回溯的最新日期设为此处，方便回溯
function setBacktrackDateToBar(targetDate: string, side?: 'left' | 'w2' | 'right' | 'w4') {
  if (!targetDate) return
  const cleanDate = targetDate.trim()
  if (!/^\d{4}[-/]\d{2}/.test(cleanDate)) return
  if (side) {
    setActiveWindow(side)
  }
  isBacktrackingMode.value = true
  if (autoRefresh.value) {
    autoRefresh.value = false
    stopAutoRefresh()
  }

  backtrackDate.value = cleanDate

  // 匹配时间轴与滑块位置（基于当前主控窗口）
  const activeD = getActiveWindowData()
  const dates = activeD?.backtrack_timeline?.available_dates || availableDates.value || []
  let matchedIdx = -1
  if (dates.length > 0) {
    matchedIdx = dates.indexOf(cleanDate)
    if (matchedIdx < 0) {
      for (let i = dates.length - 1; i >= 0; i--) {
        if (dates[i].startsWith(cleanDate) || cleanDate.startsWith(dates[i])) {
          matchedIdx = i
          break
        }
      }
    }
    if (matchedIdx < 0) {
      for (let i = dates.length - 1; i >= 0; i--) {
        if (dates[i] <= cleanDate) {
          matchedIdx = i
          break
        }
      }
    }
    if (matchedIdx >= 0) {
      backtrackIndex.value = matchedIdx
    }
  }

  // 检查客户端内存缓存
  const cacheKeyLeft = getBacktrackCacheKey(code.value, leftPeriods.value, backtrackDate.value)
  const cacheKeyW2 = getBacktrackCacheKey(code.value, w2Periods.value, backtrackDate.value)
  const cacheKeyRight = getBacktrackCacheKey(code.value, rightPeriods.value, backtrackDate.value)
  const cacheKeyW4 = getBacktrackCacheKey(code.value, w4Periods.value, backtrackDate.value)

  if (backtrackCache.has(cacheKeyLeft)) {
    chanDataLeft.value = backtrackCache.get(cacheKeyLeft)!
    if (backtrackCache.has(cacheKeyW2)) chanDataW2.value = backtrackCache.get(cacheKeyW2)!
    if (backtrackCache.has(cacheKeyRight)) chanDataRight.value = backtrackCache.get(cacheKeyRight)!
    if (backtrackCache.has(cacheKeyW4)) chanDataW4.value = backtrackCache.get(cacheKeyW4)!
    nextTick(() => {
      renderChart()
    })
    return
  }

  loadData()
}

function onSliderInput(e: Event) {
  const val = Number((e.target as HTMLInputElement).value)
  backtrackIndex.value = val
  const activeD = getActiveWindowData()
  const dates = activeD?.backtrack_timeline?.available_dates || availableDates.value || []
  if (dates[val]) {
    backtrackDate.value = dates[val]
  }

  // 1. 若拖动途中的该时间点已在客户端缓存，直接 0ms 顺畅刷新图表，完全不向服务器发请求
  const cacheKeyLeft = getBacktrackCacheKey(code.value, leftPeriods.value, backtrackDate.value)
  const cacheKeyW2 = getBacktrackCacheKey(code.value, w2Periods.value, backtrackDate.value)
  const cacheKeyRight = getBacktrackCacheKey(code.value, rightPeriods.value, backtrackDate.value)
  const cacheKeyW4 = getBacktrackCacheKey(code.value, w4Periods.value, backtrackDate.value)

  if (backtrackCache.has(cacheKeyLeft)) {
    chanDataLeft.value = backtrackCache.get(cacheKeyLeft)!
    if (backtrackCache.has(cacheKeyW2)) chanDataW2.value = backtrackCache.get(cacheKeyW2)!
    if (backtrackCache.has(cacheKeyRight)) chanDataRight.value = backtrackCache.get(cacheKeyRight)!
    if (backtrackCache.has(cacheKeyW4)) chanDataW4.value = backtrackCache.get(cacheKeyW4)!
    renderChart()
    return
  }

  // 2. 未命中缓存时，拖拽过程中不做连续请求，仅在停顿 120ms 后才防抖请求一次
  if (sliderDebounceTimer) clearTimeout(sliderDebounceTimer)
  sliderDebounceTimer = setTimeout(() => {
    triggerBacktrackLoad()
  }, 120)
}

function onSliderChange(e: Event) {
  const val = Number((e.target as HTMLInputElement).value)
  backtrackIndex.value = val
  const activeD = getActiveWindowData()
  const dates = activeD?.backtrack_timeline?.available_dates || availableDates.value || []
  if (dates[val]) {
    backtrackDate.value = dates[val]
  }
  if (sliderDebounceTimer) {
    clearTimeout(sliderDebounceTimer)
    sliderDebounceTimer = null
  }
  const cacheKeyLeft = getBacktrackCacheKey(code.value, leftPeriods.value, backtrackDate.value)
  const cacheKeyW2 = getBacktrackCacheKey(code.value, w2Periods.value, backtrackDate.value)
  const cacheKeyRight = getBacktrackCacheKey(code.value, rightPeriods.value, backtrackDate.value)
  const cacheKeyW4 = getBacktrackCacheKey(code.value, w4Periods.value, backtrackDate.value)

  if (backtrackCache.has(cacheKeyLeft)) {
    chanDataLeft.value = backtrackCache.get(cacheKeyLeft)!
    if (backtrackCache.has(cacheKeyW2)) chanDataW2.value = backtrackCache.get(cacheKeyW2)!
    if (backtrackCache.has(cacheKeyRight)) chanDataRight.value = backtrackCache.get(cacheKeyRight)!
    if (backtrackCache.has(cacheKeyW4)) chanDataW4.value = backtrackCache.get(cacheKeyW4)!
    nextTick(() => {
      renderChart()
    })
    return
  }
  triggerBacktrackLoad()
}

function stepBacktrack(step: number) {
  if (!isBacktrackingMode.value) {
    isBacktrackingMode.value = true
    stopAutoRefresh()
    autoRefresh.value = false
  }
  const activeD = getActiveWindowData()
  const dates = activeD?.backtrack_timeline?.available_dates || availableDates.value || []
  if (dates.length === 0) return

  // 确保当前索引与当前截断时间对齐
  if (backtrackDate.value && (backtrackIndex.value < 0 || backtrackIndex.value >= dates.length || dates[backtrackIndex.value] !== backtrackDate.value)) {
    let matched = dates.indexOf(backtrackDate.value)
    if (matched < 0) {
      for (let i = dates.length - 1; i >= 0; i--) {
        if (dates[i] <= backtrackDate.value) {
          matched = i
          break
        }
      }
    }
    backtrackIndex.value = matched >= 0 ? matched : dates.length - 1
  }

  const nextIdx = backtrackIndex.value + step
  if (nextIdx >= 0 && nextIdx < dates.length) {
    backtrackIndex.value = nextIdx
    backtrackDate.value = dates[nextIdx]
    const cacheKeyLeft = getBacktrackCacheKey(code.value, leftPeriods.value, backtrackDate.value)
    const cacheKeyW2 = getBacktrackCacheKey(code.value, w2Periods.value, backtrackDate.value)
    const cacheKeyRight = getBacktrackCacheKey(code.value, rightPeriods.value, backtrackDate.value)
    const cacheKeyW4 = getBacktrackCacheKey(code.value, w4Periods.value, backtrackDate.value)

    if (backtrackCache.has(cacheKeyLeft)) {
      chanDataLeft.value = backtrackCache.get(cacheKeyLeft)!
      if (backtrackCache.has(cacheKeyW2)) chanDataW2.value = backtrackCache.get(cacheKeyW2)!
      if (backtrackCache.has(cacheKeyRight)) chanDataRight.value = backtrackCache.get(cacheKeyRight)!
      if (backtrackCache.has(cacheKeyW4)) chanDataW4.value = backtrackCache.get(cacheKeyW4)!
      nextTick(() => {
        renderChart()
      })
      return
    }
    if (sliderDebounceTimer) clearTimeout(sliderDebounceTimer)
    sliderDebounceTimer = setTimeout(() => {
      triggerBacktrackLoad()
    }, 100)
  } else if (nextIdx >= dates.length) {
    exitBacktracking()
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

// ── ECharts 配置生成 ─────────────────────────────────────────────────────────
// ── 周期与色彩标准映射 (1F红、5F橙、30F黄、日绿、周蓝、月紫，全屏统一) ──────────
interface PeriodColorTheme {
  primary: string
  line?: string
  badgeBg: string
  badgeBorder?: string
  badgeText: string
  zsFill: string
  name: string
  label: string
}

interface PeriodThemeModeConfig {
  primary: string
  line?: string
  badgeBg: string
  badgeBorder?: string
  badgeText: string
  zsFill: string
}

const PERIOD_THEME_CONFIG: Record<string, { name: string; label: string; dark: PeriodThemeModeConfig; light: PeriodThemeModeConfig }> = {
  MONTH: {
    name: '紫',
    label: '月线',
    dark:  { primary: '#a78bfa', line: '#a78bfa', badgeBg: 'rgba(124, 58, 237, 0.28)', badgeBorder: '#a78bfa', badgeText: '#f5f3ff', zsFill: 'rgba(167, 139, 250, 0.10)' },
    light: { primary: '#7c3aed', line: '#7c3aed', badgeBg: '#f3e8ff', badgeBorder: '#d8b4fe', badgeText: '#6b21a8', zsFill: 'rgba(124, 58, 237, 0.05)' }
  },
  WEEK: {
    name: '蓝',
    label: '周线',
    dark:  { primary: '#60a5fa', line: '#60a5fa', badgeBg: 'rgba(37, 99, 235, 0.28)', badgeBorder: '#60a5fa', badgeText: '#eff6ff', zsFill: 'rgba(96, 165, 250, 0.10)' },
    light: { primary: '#2563eb', line: '#2563eb', badgeBg: '#eff6ff', badgeBorder: '#bfdbfe', badgeText: '#1e40af', zsFill: 'rgba(37, 99, 235, 0.05)' }
  },
  DAY: {
    name: '绿',
    label: '日线',
    dark:  { primary: '#34d399', line: '#34d399', badgeBg: 'rgba(5, 150, 105, 0.28)', badgeBorder: '#34d399', badgeText: '#ecfdf5', zsFill: 'rgba(52, 211, 153, 0.10)' },
    light: { primary: '#059669', line: '#059669', badgeBg: '#ecfdf5', badgeBorder: '#a7f3d0', badgeText: '#065f46', zsFill: 'rgba(5, 150, 105, 0.05)' }
  },
  '120F': {
    name: '靛',
    label: '120F',
    dark:  { primary: '#818cf8', line: '#818cf8', badgeBg: 'rgba(79, 70, 229, 0.28)', badgeBorder: '#818cf8', badgeText: '#eef2ff', zsFill: 'rgba(129, 140, 248, 0.10)' },
    light: { primary: '#4f46e5', line: '#4f46e5', badgeBg: '#eef2ff', badgeBorder: '#c7d2fe', badgeText: '#3730a3', zsFill: 'rgba(79, 70, 229, 0.05)' }
  },
  '60F': {
    name: '青',
    label: '60F',
    dark:  { primary: '#22d3ee', line: '#22d3ee', badgeBg: 'rgba(8, 145, 178, 0.28)', badgeBorder: '#22d3ee', badgeText: '#ecfeff', zsFill: 'rgba(34, 211, 238, 0.10)' },
    light: { primary: '#0891b2', line: '#0891b2', badgeBg: '#ecfeff', badgeBorder: '#a5f3fc', badgeText: '#0e7490', zsFill: 'rgba(8, 145, 178, 0.05)' }
  },
  '30F': {
    name: '黄',
    label: '30F',
    // 护眼暖琥珀金 (告别刺眼柠檬黄与泥黄褐色)
    dark:  { primary: '#fbbf24', line: '#fbbf24', badgeBg: 'rgba(217, 119, 6, 0.28)', badgeBorder: '#fbbf24', badgeText: '#fef9c3', zsFill: 'rgba(251, 191, 36, 0.10)' },
    light: { primary: '#d97706', line: '#d97706', badgeBg: '#fefce8', badgeBorder: '#fef08a', badgeText: '#854d0e', zsFill: 'rgba(217, 119, 6, 0.05)' }
  },
  '15F': {
    name: '琥珀',
    label: '15F',
    dark:  { primary: '#fb923c', line: '#fb923c', badgeBg: 'rgba(234, 88, 12, 0.28)', badgeBorder: '#fb923c', badgeText: '#fff7ed', zsFill: 'rgba(251, 146, 60, 0.10)' },
    light: { primary: '#ea580c', line: '#ea580c', badgeBg: '#fff7ed', badgeBorder: '#fed7aa', badgeText: '#9a3412', zsFill: 'rgba(234, 88, 12, 0.05)' }
  },
  '5F': {
    name: '青',
    label: '5F',
    // 湖青/碧蓝 (与 30F金黄、1F鲜红 形成「冷暖三原色」极致对比)
    dark:  { primary: '#38bdf8', line: '#38bdf8', badgeBg: 'rgba(2, 132, 199, 0.30)', badgeBorder: '#38bdf8', badgeText: '#f0f9ff', zsFill: 'rgba(56, 189, 248, 0.12)' },
    light: { primary: '#0284c7', line: '#0284c7', badgeBg: '#f0f9ff', badgeBorder: '#38bdf8', badgeText: '#0369a1', zsFill: 'rgba(2, 132, 199, 0.05)' }
  },
  '1F': {
    name: '红',
    label: '1F',
    // 纯正鲜红 (鲜艳醒目，纯真红色，告别偏紫/偏粉感)
    dark:  { primary: '#ff4d4f', line: '#ff4d4f', badgeBg: 'rgba(255, 34, 34, 0.32)', badgeBorder: '#ff4d4f', badgeText: '#ffffff', zsFill: 'rgba(255, 34, 34, 0.12)' },
    light: { primary: '#ff1f1f', line: '#ff1f1f', badgeBg: '#fff1f0', badgeBorder: '#ff4d4f', badgeText: '#cf1322', zsFill: 'rgba(255, 31, 31, 0.05)' }
  },
}

function getPeriodTheme(keyOrName?: string, isDark?: boolean): PeriodColorTheme {
  if (isDark === undefined) {
    if (typeof document !== 'undefined' && document.documentElement) {
      isDark = document.documentElement.classList.contains('dark')
    } else {
      isDark = false
    }
  }
  const s = String(keyOrName || '').trim().toUpperCase()
  let key = '30F'
  if (s.includes('月') || s.includes('MONTH') || s === 'M') key = 'MONTH'
  else if (s.includes('周') || s.includes('WEEK') || s === 'W') key = 'WEEK'
  else if (s.includes('日') || s.includes('DAY') || s === 'D') key = 'DAY'
  else if (s.includes('120')) key = '120F'
  else if (s.includes('60')) key = '60F'
  else if (s.includes('30')) key = '30F'
  else if (s.includes('15')) key = '15F'
  else if (s.includes('5')) key = '5F'
  else if (s.includes('1')) key = '1F'
  else if (PERIOD_THEME_CONFIG[s]) key = s

  const cfg = PERIOD_THEME_CONFIG[key] || PERIOD_THEME_CONFIG['30F']
  const modeCfg = isDark ? cfg.dark : cfg.light
  return {
    primary: modeCfg.primary,
    line: modeCfg.line || modeCfg.primary,
    badgeBg: modeCfg.badgeBg,
    badgeBorder: modeCfg.badgeBorder || modeCfg.primary,
    badgeText: modeCfg.badgeText,
    zsFill: modeCfg.zsFill,
    name: cfg.name,
    label: cfg.label,
  }
}

function buildChanlunOption(d: ChanlunResonanceResponse, winKey?: 'left' | 'w2' | 'right' | 'w4'): any {
  const uc = (isKlineMerged.value && d.merged_chart && d.merged_chart.dates && d.merged_chart.dates.length > 0)
    ? d.merged_chart
    : d.unified_chart

  if (!uc || !uc.dates || uc.dates.length === 0) {
    return {}
  }

  const isDark = document.documentElement.classList.contains('dark')

  // 提取当前图表对应的三级别专属周期色彩（统一护眼温润色系）
  const highTheme = getPeriodTheme(d?.periods?.high?.key || d?.periods?.high?.name, isDark)
  const midTheme = getPeriodTheme(d?.periods?.mid?.key || d?.periods?.mid?.name, isDark)
  const lowTheme = getPeriodTheme(d?.periods?.low?.key || d?.periods?.low?.name, isDark)

  // 大级别笔 MarkLines
  const highBiLines = showHighBi.value
    ? uc.high_bis.map((b) => [
        { 
          coord: b.start, 
          lineStyle: { color: highTheme.line || highTheme.primary, width: 2.6, type: 'solid' },
          itemStyle: { color: highTheme.line || highTheme.primary },
          symbolSize: 4,
        },
        { 
          coord: b.end, 
          itemStyle: { color: highTheme.line || highTheme.primary },
          symbolSize: 4,
        },
      ])
    : []

  // 中级别笔 MarkLines
  const midBiLines = showMidBi.value
    ? uc.mid_bis.map((b) => [
        { 
          coord: b.start, 
          lineStyle: { color: midTheme.line || midTheme.primary, width: 1.8, type: 'solid' },
          itemStyle: { color: midTheme.line || midTheme.primary },
          symbolSize: 3.5,
        },
        { 
          coord: b.end,
          itemStyle: { color: midTheme.line || midTheme.primary },
          symbolSize: 3.5,
        },
      ])
    : []

  // 小级别笔 MarkLines
  const lowBiLines = showLowBi.value
    ? uc.low_bis.map((b) => [
        { 
          coord: b.start, 
          lineStyle: { color: lowTheme.line || lowTheme.primary, width: 1.3, type: 'solid' },
          itemStyle: { color: lowTheme.line || lowTheme.primary },
          symbolSize: 3,
        },
        { 
          coord: b.end, 
          itemStyle: { color: lowTheme.line || lowTheme.primary },
          symbolSize: 3,
        },
      ])
    : []

  // 大级别中枢 MarkAreas
  const highZsAreas = showHighZs.value
    ? uc.high_zss.map((zs) => [
        {
          name: `[${d.periods.high.name}中枢]`,
          coord: [zs.start_date, zs.zg],
          itemStyle: { color: highTheme.zsFill, borderColor: highTheme.primary, borderWidth: 1.2, borderType: 'dashed' },
          label: { show: true, position: 'top', color: highTheme.primary, fontSize: 10, formatter: `[${d.periods.high.name}${highTheme.name}中枢]` },
        },
        { coord: [zs.end_date, zs.zd] },
      ])
    : []

  // 中级别中枢 MarkAreas
  const midZsAreas = showMidZs.value
    ? uc.mid_zss.map((zs) => [
        {
          name: `[${d.periods.mid.name}中枢]`,
          coord: [zs.start_date, zs.zg],
          itemStyle: { color: midTheme.zsFill, borderColor: midTheme.primary, borderWidth: 1.0, borderType: 'dashed' },
          label: { show: true, position: 'top', color: midTheme.primary, fontSize: 10, formatter: `[${d.periods.mid.name}${midTheme.name}中枢]` },
        },
        { coord: [zs.end_date, zs.zd] },
      ])
    : []

  // 小级别中枢 MarkAreas
  const lowZsAreas = showLowZs.value
    ? uc.low_zss.map((zs) => [
        {
          name: `[${d.periods.low.name}中枢]`,
          coord: [zs.start_date, zs.zg],
          itemStyle: { color: lowTheme.zsFill, borderColor: lowTheme.primary, borderWidth: 0.8, borderType: 'dotted' },
          label: { show: true, position: 'insideTopLeft', color: lowTheme.primary, fontSize: 9, formatter: `[${d.periods.low.name}${lowTheme.name}中枢]` },
        },
        { coord: [zs.end_date, zs.zd] },
      ])
    : []

  // 紧凑微型买卖箭头 (尺寸精炼为 [5.5, 20]，消除遮挡)
  const ARROW_UP_PATH = 'path://M 0,0 L 2.8,6 L 0.6,6 L 0.6,20 L -0.6,20 L -0.6,6 L -2.8,6 Z'
  const ARROW_DOWN_PATH = 'path://M 0,20 L 2.8,14 L 0.6,14 L 0.6,0 L -0.6,0 L -0.6,14 L -2.8,14 Z'

  // 多级别买卖点同图呈现 markPoints (护眼胶囊标签：温润底色 + 同色调高对比字体 + 优雅小边距)
  const mmdMarkPoints = showMmdMarks.value
    ? uc.mmd_marks.map((m) => {
        const isBig = m.level === 'high'
        const isMid = m.level === 'mid'
        const theme = isBig ? highTheme : (isMid ? midTheme : lowTheme)

        let levelName = '小'
        if (isBig) {
          levelName = d?.periods?.high?.name ? d.periods.high.name.replace('线', '') : '大'
        } else if (isMid) {
          levelName = d?.periods?.mid?.name ? d.periods.mid.name.replace('线', '') : '中'
        } else {
          levelName = d?.periods?.low?.name ? d.periods.low.name.replace('线', '') : '小'
        }

        const mType = (m.type || '').toLowerCase()
        let typeStr = ''
        if (mType.includes('1buy')) typeStr = '1买(底背)'
        else if (mType.includes('2buy')) typeStr = '2买'
        else if (mType.includes('3buy')) typeStr = '3买'
        else if (mType.includes('1sell')) typeStr = '1卖(顶背)'
        else if (mType.includes('2sell')) typeStr = '2卖'
        else if (mType.includes('3sell')) typeStr = '3卖'
        else typeStr = m.short_label || m.label || m.type

        const displayText = `${m.is_buy ? '▲' : '▼'} [${levelName}] ${typeStr}`
        const tagColor = theme.badgeBg
        const tagBorder = theme.badgeBorder || theme.primary
        const tagTextColor = theme.badgeText

        return {
          name: m.type,
          coord: m.coord,
          value: displayText,
          symbol: m.is_buy ? ARROW_UP_PATH : ARROW_DOWN_PATH,
          symbolSize: [5.5, 20],
          symbolOffset: m.is_buy ? [0, '50%'] : [0, '-50%'],
          itemStyle: {
            color: theme.primary,
            borderColor: isDark ? 'rgba(0, 0, 0, 0.4)' : '#ffffff',
            borderWidth: 0.8,
            shadowBlur: isDark ? 2 : 0,
            shadowColor: 'transparent',
          },
          label: {
            show: true,
            position: m.is_buy ? 'bottom' : 'top',
            distance: 2,
            formatter: displayText,
            color: tagTextColor,
            backgroundColor: tagColor,
            borderColor: tagBorder,
            borderWidth: 1.0,
            borderRadius: 3,
            padding: [1.5, 4.5],
            fontWeight: 'bold',
            fontSize: 9.5,
            fontFamily: "'JetBrains Mono', Consolas, -apple-system, sans-serif",
            shadowBlur: isDark ? 3 : 0,
            shadowColor: isDark ? 'rgba(0, 0, 0, 0.4)' : 'transparent',
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

  // 副图指标配置 (默认成交额，可选 主力净流入 / MACD / RSI / KDJ / EXPMA / 关闭)
  const hasSub = subIndicator.value !== 'none'
  const isSubAmount = subIndicator.value === 'amount'
  const isSubInflow = subIndicator.value === 'inflow'
  const isSubMacd = subIndicator.value === 'macd'
  const isSubRsi = subIndicator.value === 'rsi'
  const isSubKdj = subIndicator.value === 'kdj'
  const isSubExpma = subIndicator.value === 'expma'
  const macdData = uc.macd || { hist: [], dif: [], dea: [] }

  // 辅助前端本地计算 (当后端未返回对应字段时平滑兜底)
  const rawCandles = uc.candles || []
  const closes = rawCandles.map((c) => c[1])
  const lows = rawCandles.map((c) => c[2])
  const highs = rawCandles.map((c) => c[3])

  function calcClientInflow(candlesList: any[], amountsList: any[]) {
    const netInflows: number[] = []
    const n = candlesList ? candlesList.length : 0
    for (let i = 0; i < n; i++) {
      const c = candlesList[i]
      const open = Number(c[0] || 0)
      const close = Number(c[1] || 0)
      const low = Number(c[2] || 0)
      const high = Number(c[3] || 0)
      let amt = 0
      if (amountsList && amountsList[i] && amountsList[i][1] != null && !isNaN(amountsList[i][1])) {
        amt = Number(amountsList[i][1])
      } else {
        amt = close * 10000
      }
      const preC = (i > 0 && candlesList[i - 1]) ? Number(candlesList[i - 1][1] || open) : open
      const hlDiff = Math.max(0.001, high - low)
      const bodyR = (close - open) / hlDiff
      const posR = (close - low) / hlDiff - 0.5
      const chgR = ((close / Math.max(0.01, preC)) - 1.0) * 10.0
      let flowR = bodyR * 0.08 + posR * 0.06 + chgR * 0.10
      flowR = Math.max(-0.20, Math.min(0.20, flowR))
      netInflows.push(Number((amt * flowR).toFixed(2)))
    }
    const ma3 = netInflows.map((_, i) => {
      if (i < 2) return null
      let s = 0; for (let j = i - 2; j <= i; j++) s += netInflows[j]; return Number((s / 3).toFixed(2))
    })
    const ma5 = netInflows.map((_, i) => {
      if (i < 4) return null
      let s = 0; for (let j = i - 4; j <= i; j++) s += netInflows[j]; return Number((s / 5).toFixed(2))
    })
    const ma10 = netInflows.map((_, i) => {
      if (i < 9) return null
      let s = 0; for (let j = i - 9; j <= i; j++) s += netInflows[j]; return Number((s / 10).toFixed(2))
    })
    return { net_inflow: netInflows, ma3, ma5, ma10 }
  }

  function calcClientRSI(n: number): (number | null)[] {
    const res: (number | null)[] = []
    let smaup = 0
    let smaabs = 0
    for (let i = 0; i < closes.length; i++) {
      if (i === 0) {
        res.push(null)
        continue
      }
      const dif = closes[i] - closes[i - 1]
      const up = Math.max(dif, 0)
      const abs = Math.abs(dif)
      if (i === 1) {
        smaup = up
        smaabs = abs
      } else {
        smaup = (up + (n - 1) * smaup) / n
        smaabs = (abs + (n - 1) * smaabs) / n
      }
      if (smaabs === 0) {
        res.push(50)
      } else {
        res.push(Number(((smaup / smaabs) * 100).toFixed(2)))
      }
    }
    return res
  }

  function calcClientKDJ(): { k: (number | null)[]; d: (number | null)[]; j: (number | null)[] } {
    const kArr: (number | null)[] = []
    const dArr: (number | null)[] = []
    const jArr: (number | null)[] = []
    let lastK = 50
    let lastD = 50
    for (let i = 0; i < rawCandles.length; i++) {
      const start = Math.max(0, i - 8)
      let minL = lows[start]
      let maxH = highs[start]
      for (let j = start + 1; j <= i; j++) {
        if (lows[j] < minL) minL = lows[j]
        if (highs[j] > maxH) maxH = highs[j]
      }
      const rsv = maxH === minL ? 50 : ((closes[i] - minL) / (maxH - minL)) * 100
      const curK = (1 / 3) * rsv + (2 / 3) * lastK
      const curD = (1 / 3) * curK + (2 / 3) * lastD
      const curJ = 3 * curK - 2 * curD
      lastK = curK
      lastD = curD
      kArr.push(Number(curK.toFixed(2)))
      dArr.push(Number(curD.toFixed(2)))
      jArr.push(Number(curJ.toFixed(2)))
    }
    return { k: kArr, d: dArr, j: jArr }
  }

  function calcClientEMA(span: number): (number | null)[] {
    const res: (number | null)[] = []
    const alpha = 2 / (span + 1)
    let prev = 0
    for (let i = 0; i < closes.length; i++) {
      if (i === 0) {
        prev = closes[i]
      } else {
        prev = alpha * closes[i] + (1 - alpha) * prev
      }
      res.push(Number(prev.toFixed(2)))
    }
    return res
  }

  const rsiData = (uc.rsi && uc.rsi.rsi6 && uc.rsi.rsi6.length > 0)
    ? uc.rsi
    : { rsi6: calcClientRSI(6), rsi12: calcClientRSI(12), rsi24: calcClientRSI(24) }

  const kdjData = (uc.kdj && uc.kdj.k && uc.kdj.k.length > 0)
    ? uc.kdj
    : calcClientKDJ()

  const expmaData = (uc.expma && uc.expma.exp12 && uc.expma.exp12.length > 0)
    ? uc.expma
    : { exp12: calcClientEMA(12), exp50: calcClientEMA(50) }

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
  } else if (isSubInflow) {
    const amountsData = (uc.amounts && uc.amounts.length > 0)
      ? uc.amounts
      : (uc.volumes || []).map((v) => [v[0], v[1] * (uc.candles[v[0]] ? uc.candles[v[0]][1] : 0), v[2]] as [number, number, number])
    const inflowData = (uc.inflow && uc.inflow.net_inflow && uc.inflow.net_inflow.length > 0)
      ? uc.inflow
      : calcClientInflow(uc.candles || [], amountsData)
    const netInflows = inflowData.net_inflow || []
    const ma3 = inflowData.ma3 || []
    const ma5 = inflowData.ma5 || []
    const ma10 = inflowData.ma10 || []

    subSeries.push(
      {
        name: '主力净流入',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: netInflows.map((val: number) => {
          const isPos = (val || 0) >= 0
          return {
            value: val,
            itemStyle: {
              color: isPos ? '#ef4444' : '#10b981',
              borderColor: isPos ? '#dc2626' : '#059669',
              borderWidth: 0.8,
            },
          }
        }),
        barWidth: '55%',
        barMaxWidth: 14,
      },
      {
        name: '流入MA3',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: ma3,
        showSymbol: false,
        lineStyle: { width: 1.1, color: '#FACC15' },
        itemStyle: { color: '#FACC15' },
      },
      {
        name: '流入MA5',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: ma5,
        showSymbol: false,
        lineStyle: { width: 1.1, color: '#38BDF8' },
        itemStyle: { color: '#38BDF8' },
      },
      {
        name: '流入MA10',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: ma10,
        showSymbol: false,
        lineStyle: { width: 1.1, color: '#C084FC' },
        itemStyle: { color: '#C084FC' },
      }
    )
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
  } else if (isSubRsi) {
    subSeries.push(
      {
        name: 'RSI6',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: rsiData.rsi6,
        lineStyle: { color: '#ffffff', width: 1.3 },
        symbol: 'none',
        markLine: {
          symbol: 'none',
          silent: true,
          data: [
            { yAxis: 80, lineStyle: { color: 'rgba(239, 68, 68, 0.65)', type: 'dashed', width: 1 }, label: { show: true, position: 'insideEndTop', formatter: '超买 80', color: '#ef4444', fontSize: 9 } },
            { yAxis: 50, lineStyle: { color: 'rgba(148, 163, 184, 0.4)', type: 'dotted', width: 1 }, label: { show: false } },
            { yAxis: 20, lineStyle: { color: 'rgba(16, 185, 129, 0.65)', type: 'dashed', width: 1 }, label: { show: true, position: 'insideEndBottom', formatter: '超卖 20', color: '#10b981', fontSize: 9 } },
          ],
        },
      },
      {
        name: 'RSI12',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: rsiData.rsi12,
        lineStyle: { color: '#ffd600', width: 1.3 },
        symbol: 'none',
      },
      {
        name: 'RSI24',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: rsiData.rsi24,
        lineStyle: { color: '#c084fc', width: 1.3 },
        symbol: 'none',
      }
    )
  } else if (isSubKdj) {
    subSeries.push(
      {
        name: 'K',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: kdjData.k,
        lineStyle: { color: '#ffffff', width: 1.3 },
        symbol: 'none',
        markLine: {
          symbol: 'none',
          silent: true,
          data: [
            { yAxis: 80, lineStyle: { color: 'rgba(239, 68, 68, 0.65)', type: 'dashed', width: 1 }, label: { show: true, position: 'insideEndTop', formatter: '超买 80', color: '#ef4444', fontSize: 9 } },
            { yAxis: 20, lineStyle: { color: 'rgba(16, 185, 129, 0.65)', type: 'dashed', width: 1 }, label: { show: true, position: 'insideEndBottom', formatter: '超卖 20', color: '#10b981', fontSize: 9 } },
          ],
        },
      },
      {
        name: 'D',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: kdjData.d,
        lineStyle: { color: '#ffd600', width: 1.3 },
        symbol: 'none',
      },
      {
        name: 'J',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: kdjData.j,
        lineStyle: { color: '#f43f5e', width: 1.3 },
        symbol: 'none',
      }
    )
  } else if (isSubExpma) {
    subSeries.push(
      {
        name: 'EXP12',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: expmaData.exp12,
        lineStyle: { color: '#38bdf8', width: 1.4 },
        symbol: 'none',
      },
      {
        name: 'EXP50',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: expmaData.exp50,
        lineStyle: { color: '#f59e0b', width: 1.4 },
        symbol: 'none',
      }
    )
  }


  const highBiLegendName = `大笔·${d.periods.high.name}(${highTheme.name})`
  const midBiLegendName = `中笔·${d.periods.mid.name}(${midTheme.name})`
  const lowBiLegendName = `小笔·${d.periods.low.name}(${lowTheme.name})`

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
        if (dateStr && /^\d{4}[-/]\d{2}/.test(dateStr)) {
          if (winKey === 'left') hoverCandleDateLeft.value = dateStr
          else if (winKey === 'w2') hoverCandleDateW2.value = dateStr
          else if (winKey === 'right') hoverCandleDateRight.value = dateStr
          else if (winKey === 'w4') hoverCandleDateW4.value = dateStr
        }
        const kParam = params.find((p: any) => p.seriesType === 'candlestick')
        let html = `<div style="font-weight:bold; margin-bottom:4px; color:#ffffff;">📅 ${dateStr}</div>`
        if (kParam && kParam.value) {
          let open = 0, close = 0, low = 0, high = 0
          if (Array.isArray(kParam.value)) {
            if (kParam.value.length >= 5) {
              [, open, close, low, high] = kParam.value
            } else {
              [open, close, low, high] = kParam.value
            }
          } else if (Array.isArray(kParam.data)) {
            [open, close, low, high] = kParam.data
          } else if (uc.candles && uc.candles[idx]) {
            [open, close, low, high] = uc.candles[idx]
          }

          const prevC = (idx > 0 && uc.candles && uc.candles[idx - 1]) ? uc.candles[idx - 1][1] : open
          const chg = close - prevC
          const chgPct = prevC > 0 ? (chg / prevC * 100) : 0
          const chgSign = chg > 0 ? '+' : ''
          const isUp = close >= prevC
          const color = isUp ? '#ef4146' : '#089981'
          const ampVal = prevC > 0 ? (Math.abs(high - low) / prevC * 100) : 0
          const curAmt = (uc.amounts && uc.amounts[idx]) ? uc.amounts[idx][1] : ((uc.volumes && uc.volumes[idx]) ? uc.volumes[idx][1] * close : 0)
          let amtStr = '--'
          if (curAmt >= 1e8) amtStr = `¥${(curAmt / 1e8).toFixed(2)}亿`
          else if (curAmt >= 1e4) amtStr = `¥${(curAmt / 1e4).toFixed(1)}万`
          else if (curAmt > 0) amtStr = `¥${curAmt.toFixed(0)}元`

          if (winKey) {
            const isUpChg = chgPct > 0.0001
            const isDownChg = chgPct < -0.0001
            const colorClass = isUpChg ? 'color-up' : (isDownChg ? 'color-down' : 'color-flat')
            let pStr = close.toFixed(2)
            if (Math.abs(Math.round(close * 100) - close * 100) > 0.001) {
              pStr = close.toFixed(3)
            }
            const info: WinCandleInfo = {
              priceStr: pStr,
              chgStr: `${chgSign}${chgPct.toFixed(2)}%`,
              colorClass,
            }
            if (winKey === 'left') hoverCandleLeft.value = info
            else if (winKey === 'w2') hoverCandleW2.value = info
            else if (winKey === 'right') hoverCandleRight.value = info
            else if (winKey === 'w4') hoverCandleW4.value = info
          }

          if (isKlineMerged.value) {
            html += `<div style="color:${color}; margin-bottom:4px;">
              <span style="background:rgba(192,132,252,0.2); color:#d8b4fe; border:1px solid rgba(192,132,252,0.4); border-radius:3px; padding:1px 4px; font-size:10px; margin-right:6px;">缠论K线(无影线)</span>
              高: <b>${high.toFixed(2)}</b> 低: <b>${low.toFixed(2)}</b>
              <span style="margin-left:8px; font-weight:bold;">${chgSign}${chgPct.toFixed(2)}% (${chgSign}${chg.toFixed(2)})</span>
              <span style="margin-left:6px; color:#cbd5e1;">振: <b>${ampVal.toFixed(2)}%</b></span>
              <span style="margin-left:8px; color:#cbd5e1;">额: <b>${amtStr}</b></span>
            </div>`
          } else {
            html += `<div style="color:${color}; margin-bottom:4px;">
              开: <b>${open.toFixed(2)}</b> 高: <b>${high.toFixed(2)}</b> 低: <b>${low.toFixed(2)}</b> 收: <b>${close.toFixed(2)}</b>
              <span style="margin-left:8px; font-weight:bold;">${chgSign}${chgPct.toFixed(2)}% (${chgSign}${chg.toFixed(2)})</span>
              <span style="margin-left:6px; color:#cbd5e1;">振: <b>${ampVal.toFixed(2)}%</b></span>
              <span style="margin-left:8px; color:#cbd5e1;">额: <b>${amtStr}</b></span>
            </div>`
          }
        }
        // 匹配缠论买卖点 (区间套极值买卖点、次级别稳健买卖点、大级别趋势买卖点)
        const matchedMmds = (uc.mmd_marks || []).filter((m) => m.date === dateStr)
        if (matchedMmds.length > 0) {
          matchedMmds.forEach((m) => {
            const isBuy = m.is_buy
            const isNested = m.category?.includes('nested') || m.label.includes('极低') || m.label.includes('极高')
            const isSteady = m.category?.includes('steady') || m.label.includes('稳健')
            const isBig = m.level === 'high' || m.label.includes('大级别')
            let mmdBg = isDark ? (isBuy ? 'rgba(239, 68, 68, 0.22)' : 'rgba(16, 185, 129, 0.22)') : (isBuy ? 'rgba(254, 226, 226, 0.95)' : 'rgba(209, 250, 229, 0.95)')
            let mmdBorder = isBuy ? '#ef4444' : '#10b981'
            let mmdColor = isDark ? (isBuy ? '#fca5a5' : '#86efac') : (isBuy ? '#991b1b' : '#064e3b')
            let icon = isNested ? (isBuy ? '🎯' : '💎') : (isBuy ? '🔺' : '🔻')
            if (isSteady) {
              mmdBg = isDark ? 'rgba(245, 158, 11, 0.22)' : 'rgba(254, 243, 199, 0.95)'
              mmdBorder = '#f59e0b'
              mmdColor = isDark ? '#fde047' : '#92400e'
              icon = '🛡️'
            } else if (isBig) {
              mmdBg = isDark ? 'rgba(147, 51, 234, 0.22)' : 'rgba(243, 232, 255, 0.95)'
              mmdBorder = '#9333ea'
              mmdColor = isDark ? '#d8b4fe' : '#6b21a8'
              icon = '🌐'
            }

            html += `<div style="padding:4px 7px; background:${mmdBg}; border:1px solid ${mmdBorder}; border-radius:4px; margin-top:4px; font-size:11px;">
              <div style="font-weight:bold; color:${mmdColor}; display:flex; justify-content:space-between; align-items:center;">
                <span>${icon} ${m.label}</span>
                <span style="font-family:monospace; margin-left:8px;">¥${m.price.toFixed(2)}</span>
              </div>
              <div style="color:${isDark ? '#cbd5e1' : '#475569'}; margin-top:2px; font-size:10.5px; line-height:1.35;">
                ${m.msg}
              </div>
            </div>`
          })
        }

        // 匹配共振点
        const matchedRes = uc.res_marks.find((r) => r.date === dateStr)
        if (matchedRes) {
          const isBuy = matchedRes.direction === 'BUY'
          const resBg = isDark ? (isBuy ? 'rgba(239, 68, 68, 0.25)' : 'rgba(16, 185, 129, 0.25)') : (isBuy ? 'rgba(254, 226, 226, 0.95)' : 'rgba(209, 250, 229, 0.95)')
          const resBorder = isBuy ? '#f59e0b' : '#06b6d4'
          const resColor = isDark ? (isBuy ? '#fde047' : '#67e8f9') : (isBuy ? '#92400e' : '#0e7490')
          html += `<div style="padding:4px 7px; background:${resBg}; border:1px solid ${resBorder}; border-radius:4px; margin-top:4px; font-weight:bold; color:${resColor}; font-size:11px;">
            ★ ${matchedRes.pattern_name} [${matchedRes.grade}级共振] ¥${matchedRes.price.toFixed(2)}
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

        // 副图数据展示
        if (isSubMacd && macdData.dif && macdData.dif[idx] !== undefined) {
          const difV = macdData.dif[idx]
          const deaV = macdData.dea ? macdData.dea[idx] : undefined
          const histV = macdData.hist ? macdData.hist[idx] : undefined
          html += `<div style="color:#cbd5e1; margin-top:3px; font-size:11px;">
            <span style="color:#ffffff;">DIF: <b>${difV != null ? Number(difV).toFixed(2) : '--'}</b></span>
            <span style="color:#ffd600; margin-left:8px;">DEA: <b>${deaV != null ? Number(deaV).toFixed(2) : '--'}</b></span>
            <span style="color:${(histV || 0) >= 0 ? '#ef4146' : '#089981'}; margin-left:8px;">MACD: <b>${histV != null ? Number(histV).toFixed(2) : '--'}</b></span>
          </div>`
        } else if (isSubRsi && rsiData.rsi6) {
          const r6 = rsiData.rsi6[idx]
          const r12 = rsiData.rsi12[idx]
          const r24 = rsiData.rsi24[idx]
          html += `<div style="color:#cbd5e1; margin-top:3px; font-size:11px;">
            <span style="color:#ffffff;">RSI6: <b>${r6 != null ? Number(r6).toFixed(2) : '--'}</b></span>
            <span style="color:#ffd600; margin-left:8px;">RSI12: <b>${r12 != null ? Number(r12).toFixed(2) : '--'}</b></span>
            <span style="color:#c084fc; margin-left:8px;">RSI24: <b>${r24 != null ? Number(r24).toFixed(2) : '--'}</b></span>
          </div>`
        } else if (isSubKdj && kdjData.k) {
          const kVal = kdjData.k[idx]
          const dVal = kdjData.d[idx]
          const jVal = kdjData.j[idx]
          html += `<div style="color:#cbd5e1; margin-top:3px; font-size:11px;">
            <span style="color:#ffffff;">K: <b>${kVal != null ? Number(kVal).toFixed(2) : '--'}</b></span>
            <span style="color:#ffd600; margin-left:8px;">D: <b>${dVal != null ? Number(dVal).toFixed(2) : '--'}</b></span>
            <span style="color:#f43f5e; margin-left:8px;">J: <b>${jVal != null ? Number(jVal).toFixed(2) : '--'}</b></span>
          </div>`
        } else if (isSubExpma && expmaData.exp12) {
          const e12 = expmaData.exp12[idx]
          const e50 = expmaData.exp50[idx]
          html += `<div style="color:#cbd5e1; margin-top:3px; font-size:11px;">
            <span style="color:#38bdf8;">EXP12: <b>${e12 != null ? Number(e12).toFixed(2) : '--'}</b></span>
            <span style="color:#f59e0b; margin-left:8px;">EXP50: <b>${e50 != null ? Number(e50).toFixed(2) : '--'}</b></span>
          </div>`
        } else if (isSubInflow) {
          const amountsData = (uc.amounts && uc.amounts.length > 0)
            ? uc.amounts
            : (uc.volumes || []).map((v: any) => [v[0], v[1] * (uc.candles[v[0]] ? uc.candles[v[0]][1] : 0), v[2]])
          const inflowData = (uc.inflow && uc.inflow.net_inflow && uc.inflow.net_inflow.length > 0)
            ? uc.inflow
            : calcClientInflow(uc.candles || [], amountsData)
          const flowVal = (inflowData.net_inflow && inflowData.net_inflow[idx] != null) ? inflowData.net_inflow[idx] : 0
          const m3 = (inflowData.ma3 && inflowData.ma3[idx] != null) ? inflowData.ma3[idx] : null
          const m5 = (inflowData.ma5 && inflowData.ma5[idx] != null) ? inflowData.ma5[idx] : null
          const m10 = (inflowData.ma10 && inflowData.ma10[idx] != null) ? inflowData.ma10[idx] : null

          const formatFlow = (val: any) => {
            if (val == null || isNaN(val)) return '--'
            const absV = Math.abs(val)
            const sign = val > 0 ? '+' : (val < 0 ? '-' : '')
            if (absV >= 1e8) return `${sign}${(absV / 1e8).toFixed(2)}亿`
            if (absV >= 1e4) return `${sign}${(absV / 1e4).toFixed(2)}万`
            return `${sign}${absV.toFixed(0)}元`
          }
          const flowColor = flowVal > 0 ? '#ef4444' : (flowVal < 0 ? '#10b981' : (isDark ? '#cbd5e1' : '#64748b'))
          html += `<div style="color:#cbd5e1; margin-top:3px; font-size:11px;">
            <span>主力净流入: <b style="color:${flowColor};">${formatFlow(flowVal)}</b></span>
            <span style="color:#FACC15; margin-left:8px;">MA3: <b>${formatFlow(m3)}</b></span>
            <span style="color:#38BDF8; margin-left:8px;">MA5: <b>${formatFlow(m5)}</b></span>
            <span style="color:#C084FC; margin-left:8px;">MA10: <b>${formatFlow(m10)}</b></span>
          </div>`
        }

        return html
      },
    },
    legend: {
      data: [
        '基准K线',
        highBiLegendName,
        midBiLegendName,
        lowBiLegendName,
        ...(isSubAmount ? ['成交额'] : []),
        ...(isSubInflow ? ['主力净流入', '流入MA3', '流入MA5', '流入MA10'] : []),
        ...(isSubMacd ? ['MACD', 'DIF', 'DEA'] : []),
        ...(isSubRsi ? ['RSI6', 'RSI12', 'RSI24'] : []),
        ...(isSubKdj ? ['K', 'D', 'J'] : []),
        ...(isSubExpma ? ['EXP12', 'EXP50'] : []),
      ],
      selected: {
        基准K线: true,
        [highBiLegendName]: showHighBi.value,
        [midBiLegendName]: showMidBi.value,
        [lowBiLegendName]: showLowBi.value,
        成交额: true,
        主力净流入: true,
        流入MA3: true,
        流入MA5: true,
        流入MA10: true,
        MACD: true,
        DIF: true,
        DEA: true,
        RSI6: true,
        RSI12: true,
        RSI24: true,
        K: true,
        D: true,
        J: true,
        EXP12: true,
        EXP50: true,
      },
      top: 10,
      textStyle: { color: '#a0a6b5', fontSize: 12 },
    },
    grid: [
      { left: '3.5%', right: '3.5%', top: 38, bottom: hasSub ? '24%' : 26 },
      { left: '3.5%', right: '3.5%', height: hasSub ? '14%' : '0%', bottom: 25 },
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
        scale: !isSubAmount && !isSubRsi,
        min: isSubAmount ? 0 : (isSubRsi ? 0 : undefined),
        max: isSubRsi ? 100 : undefined,
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
            : (isSubInflow
                ? (val: any) => {
                    if (val == null || isNaN(val)) return ''
                    const absV = Math.abs(val)
                    const sign = val < 0 ? '-' : ''
                    if (absV >= 1e8) return `${sign}${(absV / 1e8).toFixed(1)}亿`
                    if (absV >= 1e4) return `${sign}${(absV / 1e4).toFixed(0)}万`
                    return `${sign}${absV.toFixed(0)}`
                  }
                : (isSubExpma
                    ? (val: any) => Number(val).toFixed(2)
                    : (isSubRsi || isSubKdj
                        ? (val: any) => Number(val).toFixed(0)
                        : undefined))),
        },
      },
    ],
    ...(() => {
      // 保证每个窗口默认显示窗口中，有且只有一个完整的大周期线段
      const totalBars = uc.dates ? uc.dates.length : 0
      let defaultZoomStart = Math.max(0, 100 - (110 / (totalBars || 1)) * 100)
      let defaultZoomEnd = 100

      const highBis = uc.high_bis || []
      if (highBis.length > 0 && totalBars > 0) {
        const targetBi = highBis[highBis.length - 1]
        const prevBi = highBis.length >= 2 ? highBis[highBis.length - 2] : null

        const targetStartIdx = Math.max(0, Math.min(totalBars - 1, targetBi.start_idx))

        // 留出适度左边距（例如 3~5 根K线），确保起始顶点圆形标记和分型清晰展现；
        // 同时边距严控不超过与前一条线段起点的间距，确保前一条线段在视野内不完整，
        // 从而保证当前默认显示窗口中有且仅有一个完整的大周期线段。
        let leftMargin = 4
        if (prevBi) {
          const prevStartIdx = Math.max(0, prevBi.start_idx)
          const allowedMargin = Math.max(0, Math.floor((targetStartIdx - prevStartIdx) / 4))
          leftMargin = Math.min(leftMargin, allowedMargin)
        }
        const viewStartIdx = Math.max(0, targetStartIdx - leftMargin)

        defaultZoomStart = Math.max(0, Number(((viewStartIdx / totalBars) * 100).toFixed(2)))
        defaultZoomEnd = 100
      } else if ((uc.mid_bis || []).length > 0 && totalBars > 0) {
        // 兜底：若暂无大级别笔，则退化使用中级别最新完整线段
        const midBis = uc.mid_bis || []
        const targetBi = midBis[midBis.length - 1]
        const prevBi = midBis.length >= 2 ? midBis[midBis.length - 2] : null
        const targetStartIdx = Math.max(0, Math.min(totalBars - 1, targetBi.start_idx))
        let leftMargin = 4
        if (prevBi) {
          const prevStartIdx = Math.max(0, prevBi.start_idx)
          const allowedMargin = Math.max(0, Math.floor((targetStartIdx - prevStartIdx) / 4))
          leftMargin = Math.min(leftMargin, allowedMargin)
        }
        const viewStartIdx = Math.max(0, targetStartIdx - leftMargin)
        defaultZoomStart = Math.max(0, Number(((viewStartIdx / totalBars) * 100).toFixed(2)))
        defaultZoomEnd = 100
      }

      return {
        dataZoom: [
          {
            type: 'inside',
            xAxisIndex: [0, 1],
            minValueSpan: 10,
            start: defaultZoomStart,
            end: defaultZoomEnd,
          },
          {
            type: 'slider',
            xAxisIndex: [0, 1],
            bottom: 4,
            height: 14,
            minValueSpan: 10,
            borderColor: '#2a2e39',
            backgroundColor: '#181b27',
            fillerColor: 'rgba(41, 98, 255, 0.25)',
            textStyle: { color: '#888888', fontSize: 10 },
            start: defaultZoomStart,
            end: defaultZoomEnd,
          },
        ],
      }
    })(),
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
          data: [
            ...resonanceVerticalLines,
            ...lowBiLines,     // 小周期底层
            ...midBiLines,     // 中周期中间层
            ...highBiLines,    // 大周期顶层（线段重合时大周期的颜色显示为主！）
          ] as any,
          symbol: ['circle', 'circle'],
          symbolSize: 4,
        },
        markArea: {
          data: [
            ...lowZsAreas,     // 小中枢底层
            ...midZsAreas,     // 中中枢中间层
            ...highZsAreas,    // 大中枢顶层
          ] as any,
        },
      },
      {
        name: highBiLegendName,
        type: 'line',
        data: [],
        color: highTheme.primary,
        itemStyle: { color: highTheme.primary },
        lineStyle: { color: highTheme.primary, width: 3.5 },
      },
      {
        name: midBiLegendName,
        type: 'line',
        data: [],
        color: midTheme.primary,
        itemStyle: { color: midTheme.primary },
        lineStyle: { color: midTheme.primary, width: 2.2 },
      },
      {
        name: lowBiLegendName,
        type: 'line',
        data: [],
        color: lowTheme.primary,
        itemStyle: { color: lowTheme.primary },
        lineStyle: { color: lowTheme.primary, width: 1.5 },
      },
      ...subSeries,
    ],
  }

  return option
}

// ── ECharts 绘制与多分辨率窗口自适应逻辑 ───────────────────────────────────────
const cardHeight = ref<number>(0)

function adjustLayoutHeight() {
  const container = chartContainerLeft.value?.closest('.charts-split-container') as HTMLElement | null
  const topOffset = container ? container.getBoundingClientRect().top : 0
  const bottomMargin = 14
  let targetH = window.innerHeight - topOffset - bottomMargin
  if (targetH < 350 || topOffset <= 0) {
    targetH = Math.max(380, window.innerHeight - 230)
  }
  const baseH = Math.max(360, Math.floor(targetH))
  if (splitMode.value === 'quad' || splitMode.value === 'dual') {
    cardHeight.value = Math.max(330, Math.floor((baseH - 12) / 2))
  } else {
    cardHeight.value = baseH
  }
  nextTick(() => {
    if (chartInstanceLeft) chartInstanceLeft.resize()
    if (splitMode.value === 'quad') {
      if (chartInstanceW2) chartInstanceW2.resize()
      if (chartInstanceRight) chartInstanceRight.resize()
      if (chartInstanceW4) chartInstanceW4.resize()
    } else if (splitMode.value === 'dual') {
      if (chartInstanceRight) chartInstanceRight.resize()
    }
  })
}

function handleResize() {
  adjustLayoutHeight()
}

function extractChanlunDblclickDate(
  params: any,
  dates: string[],
  hoveredDate: string | null,
  instance: echarts.ECharts | null
): string | null {
  // 1. 优先使用鼠标最近悬停/吸附的蜡烛日期（杜绝中枢色块、笔线段、K线间隙导致的误判）
  if (hoveredDate && /^\d{4}[-/]\d{2}/.test(hoveredDate)) {
    return hoveredDate
  }
  // 2. 检查 params.name 是否包含合法日期格式（严格过滤中枢名、画线名、空白等）
  if (params && params.name) {
    const nStr = String(params.name).trim()
    if (/^\d{4}[-/]\d{2}/.test(nStr)) {
      return nStr
    }
  }
  // 3. 检查 params.dataIndex
  if (params && typeof params.dataIndex === 'number' && dates[params.dataIndex]) {
    const dStr = String(dates[params.dataIndex]).trim()
    if (/^\d{4}[-/]\d{2}/.test(dStr)) {
      return dStr
    }
  }
  // 4. 坐标系换算兜底（严格防跳回第0根：严禁超出当前可视区域范围）
  if (params && params.event && instance) {
    try {
      const zrEvt = params.event
      const px = (zrEvt && typeof zrEvt.zrX === 'number') ? zrEvt.zrX : (zrEvt && typeof zrEvt.offsetX === 'number' ? zrEvt.offsetX : null)
      const py = (zrEvt && typeof zrEvt.zrY === 'number') ? zrEvt.zrY : (zrEvt && typeof zrEvt.offsetY === 'number' ? zrEvt.offsetY : null)
      if (px != null && py != null) {
        const pointInGrid = instance.convertFromPixel({ seriesIndex: 0 }, [px, py])
        if (pointInGrid && typeof pointInGrid[0] === 'number' && !isNaN(pointInGrid[0])) {
          const xIdx = Math.round(pointInGrid[0])
          const opt: any = instance.getOption()
          const zoom = opt && opt.dataZoom && opt.dataZoom[0]
          let minValidIdx = 0
          let maxValidIdx = dates.length - 1
          if (zoom && typeof zoom.start === 'number' && typeof zoom.end === 'number') {
            minValidIdx = Math.max(0, Math.floor((zoom.start / 100) * dates.length) - 5)
            maxValidIdx = Math.min(dates.length - 1, Math.ceil((zoom.end / 100) * dates.length) + 5)
          }
          if (xIdx >= minValidIdx && xIdx <= maxValidIdx && dates[xIdx]) {
            const candidate = String(dates[xIdx]).trim()
            if (/^\d{4}[-/]\d{2}/.test(candidate)) {
              return candidate
            }
          }
        }
      }
    } catch (_) {}
  }
  return null
}

function getChartDates(data?: ChanlunResonanceResponse | null): string[] {
  if (!data) return []
  if (isKlineMerged.value && data.merged_chart && data.merged_chart.dates && data.merged_chart.dates.length > 0) {
    return data.merged_chart.dates
  }
  return data.unified_chart?.dates || []
}

function bindLegendEvents(inst: echarts.ECharts) {
  inst.on('legendselectchanged', (params: any) => {
    if (params && params.name) {
      if (params.name.startsWith('大笔')) {
        showHighBi.value = !!params.selected[params.name]
      } else if (params.name.startsWith('中笔')) {
        showMidBi.value = !!params.selected[params.name]
      } else if (params.name.startsWith('小笔')) {
        showLowBi.value = !!params.selected[params.name]
      }
      renderChart()
    }
  })
}

function renderChart() {
  if (chartContainerLeft.value && chanDataLeft.value) {
    if (!chartInstanceLeft) {
      chartInstanceLeft = echarts.init(chartContainerLeft.value, 'dark')
      chartInstanceLeft.on('click', () => { setActiveWindow('left') })
      chartInstanceLeft.on('globalout', () => { hoverCandleLeft.value = null })
      chartInstanceLeft.on('hideTip', () => { hoverCandleLeft.value = null })
      bindLegendEvents(chartInstanceLeft)
      chartInstanceLeft.on('updateAxisPointer', (event: any) => {
        const dates = getChartDates(chanDataLeft.value)
        if (event && typeof event.dataIndex === 'number' && dates[event.dataIndex]) {
          const dStr = String(dates[event.dataIndex]).trim()
          if (/^\d{4}[-/]\d{2}/.test(dStr)) hoverCandleDateLeft.value = dStr
        }
      })
      chartInstanceLeft.on('dblclick', (params: any) => {
        const dates = getChartDates(chanDataLeft.value)
        const targetDate = extractChanlunDblclickDate(params, dates, hoverCandleDateLeft.value, chartInstanceLeft)
        if (targetDate) setBacktrackDateToBar(targetDate, 'left')
      })
      window.addEventListener('resize', handleResize)
    }
    const optionLeft = buildChanlunOption(chanDataLeft.value, 'left')
    chartInstanceLeft.setOption(optionLeft, { notMerge: true, lazyUpdate: true })
  }

  if (splitMode.value === 'quad') {
    if (chartContainerW2.value && chanDataW2.value) {
      if (!chartInstanceW2) {
        chartInstanceW2 = echarts.init(chartContainerW2.value, 'dark')
        chartInstanceW2.on('click', () => { setActiveWindow('w2') })
        chartInstanceW2.on('globalout', () => { hoverCandleW2.value = null })
        chartInstanceW2.on('hideTip', () => { hoverCandleW2.value = null })
        bindLegendEvents(chartInstanceW2)
        chartInstanceW2.on('updateAxisPointer', (event: any) => {
          const dates = getChartDates(chanDataW2.value)
          if (event && typeof event.dataIndex === 'number' && dates[event.dataIndex]) {
            const dStr = String(dates[event.dataIndex]).trim()
            if (/^\d{4}[-/]\d{2}/.test(dStr)) hoverCandleDateW2.value = dStr
          }
        })
        chartInstanceW2.on('dblclick', (params: any) => {
          const dates = getChartDates(chanDataW2.value)
          const targetDate = extractChanlunDblclickDate(params, dates, hoverCandleDateW2.value, chartInstanceW2)
          if (targetDate) setBacktrackDateToBar(targetDate, 'w2')
        })
      }
      const optionW2 = buildChanlunOption(chanDataW2.value, 'w2')
      chartInstanceW2.setOption(optionW2, { notMerge: true, lazyUpdate: true })
    }
    if (chartContainerRight.value && chanDataRight.value) {
      if (!chartInstanceRight) {
        chartInstanceRight = echarts.init(chartContainerRight.value, 'dark')
        chartInstanceRight.on('click', () => { setActiveWindow('right') })
        chartInstanceRight.on('globalout', () => { hoverCandleRight.value = null })
        chartInstanceRight.on('hideTip', () => { hoverCandleRight.value = null })
        bindLegendEvents(chartInstanceRight)
        chartInstanceRight.on('updateAxisPointer', (event: any) => {
          const dates = getChartDates(chanDataRight.value)
          if (event && typeof event.dataIndex === 'number' && dates[event.dataIndex]) {
            const dStr = String(dates[event.dataIndex]).trim()
            if (/^\d{4}[-/]\d{2}/.test(dStr)) hoverCandleDateRight.value = dStr
          }
        })
        chartInstanceRight.on('dblclick', (params: any) => {
          const dates = getChartDates(chanDataRight.value)
          const targetDate = extractChanlunDblclickDate(params, dates, hoverCandleDateRight.value, chartInstanceRight)
          if (targetDate) setBacktrackDateToBar(targetDate, 'right')
        })
      }
      const optionRight = buildChanlunOption(chanDataRight.value, 'right')
      chartInstanceRight.setOption(optionRight, { notMerge: true, lazyUpdate: true })
    }
    if (chartContainerW4.value && chanDataW4.value) {
      if (!chartInstanceW4) {
        chartInstanceW4 = echarts.init(chartContainerW4.value, 'dark')
        chartInstanceW4.on('click', () => { setActiveWindow('w4') })
        chartInstanceW4.on('globalout', () => { hoverCandleW4.value = null })
        chartInstanceW4.on('hideTip', () => { hoverCandleW4.value = null })
        bindLegendEvents(chartInstanceW4)
        chartInstanceW4.on('updateAxisPointer', (event: any) => {
          const dates = getChartDates(chanDataW4.value)
          if (event && typeof event.dataIndex === 'number' && dates[event.dataIndex]) {
            const dStr = String(dates[event.dataIndex]).trim()
            if (/^\d{4}[-/]\d{2}/.test(dStr)) hoverCandleDateW4.value = dStr
          }
        })
        chartInstanceW4.on('dblclick', (params: any) => {
          const dates = getChartDates(chanDataW4.value)
          const targetDate = extractChanlunDblclickDate(params, dates, hoverCandleDateW4.value, chartInstanceW4)
          if (targetDate) setBacktrackDateToBar(targetDate, 'w4')
        })
      }
      const optionW4 = buildChanlunOption(chanDataW4.value, 'w4')
      chartInstanceW4.setOption(optionW4, { notMerge: true, lazyUpdate: true })
    }
  } else if (splitMode.value === 'dual') {
    if (chartContainerRight.value && chanDataRight.value) {
      if (!chartInstanceRight) {
        chartInstanceRight = echarts.init(chartContainerRight.value, 'dark')
        chartInstanceRight.on('click', () => { setActiveWindow('right') })
        chartInstanceRight.on('globalout', () => { hoverCandleRight.value = null })
        chartInstanceRight.on('hideTip', () => { hoverCandleRight.value = null })
        bindLegendEvents(chartInstanceRight)
        chartInstanceRight.on('dblclick', (params: any) => {
          const dates = getChartDates(chanDataRight.value)
          let targetDate: string | null = null
          if (params && params.name) targetDate = String(params.name).trim()
          else if (params && typeof params.dataIndex === 'number' && dates[params.dataIndex]) targetDate = String(dates[params.dataIndex]).trim()
          if (targetDate) setBacktrackDateToBar(targetDate, 'right')
        })
      }
      const optionRight = buildChanlunOption(chanDataRight.value, 'right')
      chartInstanceRight.setOption(optionRight, { notMerge: true, lazyUpdate: true })
    }
  }

  attachSelectionToAllCharts()
  adjustLayoutHeight()
}

function zoomChart(factor: number) {
  const instances = [
    chartInstanceLeft,
    splitMode.value === 'quad' ? chartInstanceW2 : null,
    splitMode.value === 'dual' || splitMode.value === 'quad' ? chartInstanceRight : null,
    splitMode.value === 'quad' ? chartInstanceW4 : null,
  ].filter(Boolean)
  for (const inst of instances) {
    const opt = inst!.getOption() as any
    if (!opt || !opt.dataZoom || !opt.dataZoom[0]) continue
    let start = opt.dataZoom[0].start ?? 40
    let end = opt.dataZoom[0].end ?? 100
    const span = end - start
    const totalBars = chanDataLeft.value?.unified_chart?.dates?.length || 100
    const minSpan = Math.min(100, (20 / totalBars) * 100)
    const newSpan = Math.max(minSpan, Math.min(100, span * factor))
    const delta = (newSpan - span) / 2
    let newStart = Math.max(0, start - delta)
    let newEnd = Math.min(100, end + delta)
    if (newStart === 0) newEnd = Math.min(100, newStart + newSpan)
    if (newEnd === 100) newStart = Math.max(0, newEnd - newSpan)
    inst!.dispatchAction({
      type: 'dataZoom',
      start: newStart,
      end: newEnd,
    })
  }
}

function handleKeyDown(e: KeyboardEvent) {
  if (document.activeElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    zoomChart(0.8)
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    zoomChart(1.25)
  } else if (e.key === 'ArrowLeft') {
    e.preventDefault()
    stepBacktrack(-1)
  } else if (e.key === 'ArrowRight') {
    e.preventDefault()
    stepBacktrack(1)
  } else if (e.code === 'Space') {
    e.preventDefault()
    toggleReplay()
  } else if (e.key === 'End') {
    e.preventDefault()
    exitBacktracking()
  }
}

// ── 生命周期 ─────────────────────────────────────────────────────────────────
onMounted(async () => {
  let qCode = (route.query.code || route.query.symbol) as string | undefined
  if (!qCode && typeof window !== 'undefined') {
    const raw = (window.location.hash || '') + '&' + (window.location.search || '')
    const m = raw.match(/[?&#](?:code|symbol)=([0-9a-zA-Z]+)/i)
    if (m && m[1]) qCode = decodeURIComponent(m[1])
  }
  if (qCode) {
    const clean = qCode.replace(/[^0-9a-zA-Z]/g, '')
    code.value = clean || qCode
    loadHotStocks()
  } else {
    // 默认 K 线显示热门股票 (优先请求最新热门股票池第一名龙头)
    try {
      const hots = await loadHotStocks()
      if (hots && hots.length > 0) {
        code.value = hots[0].code
      }
    } catch {
      // keep default code
    }
  }
  await loadData(true)
  fetchWatchlist()
  clockTimer = setInterval(() => {
    inTradeSession.value = isTradeSession()
  }, 1000)
  if (autoRefresh.value) {
    startAutoRefresh()
  }
  window.addEventListener('keydown', handleKeyDown)
  window.addEventListener('resize', handleResize)
  adjustLayoutHeight()
})

// ── 通达信风格 区间统计与形态匹配选股 ──────────────────────────────────
interface TdxStatData {
  stockName: string
  stockCode: string
  startDate: string
  endDate: string
  periodCount: number
  calendarDays: number
  prevClose: string
  openPrice: string
  highPrice: string
  lowPrice: string
  closePrice: string
  totalVol: string
  totalAmtStr: string
  avgClose: string
  weightedAvg: string
  chgDiff: string
  chgPct: string
  ampDiff: string
  ampPct: string
  maxGain: string
  maxDrawdown: string
  totalTurnover: string
  avgTurnover: string
  annualized: string
  upBars: number
  downBars: number
  flatBars: number
  gainDays: number
  loseDays: number
  evenDays: number
  targetPrices: number[]
}

const showRangeStatModal = ref(false)
const statModalPos = ref({ x: 160, y: 120 })
const statKeepBox = ref(true)
const currentStat = ref<TdxStatData | null>(null)
let activeSelectionBoxEl: HTMLDivElement | null = null

// 形态匹配选股状态
const showPatternMatchModal = ref(false)
const pmUniverse = ref('core')
const pmTargetBadge = ref('')
const pmScanning = ref(false)
const pmStatusText = ref('就绪')
const pmTargetPoints = ref<number[]>([])
const pmMatches = ref<any[]>([])
let currentPmPrices: number[] = []
let currentPmSymbol = ''

function calcRangeStatistics(uc: any, startIdx: number, endIdx: number, name: string, code: string): TdxStatData | null {
  if (!uc || !uc.dates || !uc.candles || uc.dates.length === 0) return null
  startIdx = Math.max(0, Math.min(uc.dates.length - 1, startIdx))
  endIdx = Math.max(0, Math.min(uc.dates.length - 1, endIdx))
  if (startIdx > endIdx) {
    const tmp = startIdx; startIdx = endIdx; endIdx = tmp
  }

  const periodCount = endIdx - startIdx + 1
  if (periodCount <= 0) return null

  const startDate = String(uc.dates[startIdx] || '')
  const endDate = String(uc.dates[endIdx] || '')

  let calendarDays = periodCount
  try {
    const d1 = new Date(startDate.split(' ')[0].replace(/-/g, '/'))
    const d2 = new Date(endDate.split(' ')[0].replace(/-/g, '/'))
    if (!isNaN(d1.getTime()) && !isNaN(d2.getTime())) {
      calendarDays = Math.max(1, Math.round(Math.abs(d2.getTime() - d1.getTime()) / (1000 * 60 * 60 * 24)) + 1)
    }
  } catch (e) {}

  const prevClose = startIdx > 0 ? Number(uc.candles[startIdx - 1][1] || uc.candles[startIdx][0]) : Number(uc.candles[startIdx][0] || 0)
  const openPrice = Number(uc.candles[startIdx][0] || 0)
  const closePrice = Number(uc.candles[endIdx][1] || 0)

  let highPrice = -Infinity
  let lowPrice = Infinity
  let totalVol = 0
  let totalAmt = 0
  let sumClose = 0

  let upBars = 0
  let downBars = 0
  let flatBars = 0

  let gainDays = 0
  let loseDays = 0
  let evenDays = 0

  let maxGain = 0
  let minLowSoFar = Infinity

  let maxHighSoFar = -Infinity
  let maxDrawdown = 0

  const targetPrices: number[] = []

  for (let i = startIdx; i <= endIdx; i++) {
    const c = uc.candles[i] || [0, 0, 0, 0]
    const o = Number(c[0] || 0)
    const cl = Number(c[1] || 0)
    const l = Number(c[2] || 0)
    const h = Number(c[3] || 0)
    const v = Number(uc.volumes ? uc.volumes[i] : 0)
    const a = Number(uc.amounts ? uc.amounts[i] : 0)

    targetPrices.push(cl)

    if (h > highPrice) highPrice = h
    if (l < lowPrice) lowPrice = l
    totalVol += v
    totalAmt += a
    sumClose += cl

    if (cl > o) upBars++
    else if (cl < o) downBars++
    else flatBars++

    const pClose = (i === startIdx) ? prevClose : Number(uc.candles[i - 1][1] || 0)
    if (cl > pClose) gainDays++
    else if (cl < pClose) loseDays++
    else evenDays++

    if (l < minLowSoFar) minLowSoFar = l
    if (minLowSoFar > 0 && h > minLowSoFar) {
      const g = (h - minLowSoFar) / minLowSoFar * 100
      if (g > maxGain) maxGain = g
    }

    if (h > maxHighSoFar) maxHighSoFar = h
    if (maxHighSoFar > 0 && l < maxHighSoFar) {
      const dd = (l - maxHighSoFar) / maxHighSoFar * 100
      if (dd < maxDrawdown) maxDrawdown = dd
    }
  }

  if (highPrice === -Infinity) highPrice = closePrice
  if (lowPrice === Infinity) lowPrice = closePrice

  const chgDiff = closePrice - prevClose
  const chgPct = prevClose > 0 ? (chgDiff / prevClose * 100) : 0
  const ampDiff = highPrice - lowPrice
  const ampPct = prevClose > 0 ? (ampDiff / prevClose * 100) : 0

  const avgClose = periodCount > 0 ? (sumClose / periodCount) : closePrice
  const weightedAvg = totalVol > 0 ? (totalAmt / totalVol) : avgClose

  let annualized = 0
  if (periodCount > 0 && prevClose > 0) {
    const ratio = closePrice / prevClose
    if (ratio > 0) {
      annualized = (Math.pow(ratio, 250 / periodCount) - 1) * 100
    }
  }

  const fmtAmt = (amt: number) => {
    if (amt >= 1e8) return `${(amt / 1e8).toFixed(2)}亿`
    if (amt >= 1e4) return `${(amt / 1e4).toFixed(1)}万`
    return amt.toFixed(0)
  }

  return {
    stockName: name || '标的',
    stockCode: code || '',
    startDate,
    endDate,
    periodCount,
    calendarDays,
    prevClose: prevClose.toFixed(2),
    openPrice: openPrice.toFixed(2),
    highPrice: highPrice.toFixed(2),
    lowPrice: lowPrice.toFixed(2),
    closePrice: closePrice.toFixed(2),
    totalVol: totalVol.toFixed(0),
    totalAmtStr: fmtAmt(totalAmt),
    avgClose: avgClose.toFixed(2),
    weightedAvg: weightedAvg.toFixed(2),
    chgDiff: (chgDiff >= 0 ? `+${chgDiff.toFixed(2)}` : chgDiff.toFixed(2)),
    chgPct: chgPct.toFixed(2),
    ampDiff: ampDiff.toFixed(2),
    ampPct: ampPct.toFixed(2),
    maxGain: maxGain.toFixed(2),
    maxDrawdown: maxDrawdown.toFixed(2),
    totalTurnover: '--',
    avgTurnover: '--',
    annualized: (annualized >= 0 ? `+${annualized.toFixed(2)}%` : `${annualized.toFixed(2)}%`),
    upBars,
    downBars,
    flatBars,
    gainDays,
    loseDays,
    evenDays,
    targetPrices
  }
}

function ensureChartSelectionBoxVue(containerEl: HTMLElement | null): HTMLDivElement | null {
  if (!containerEl) return null
  containerEl.style.position = 'relative'
  let box = containerEl.querySelector('.tdx-chart-selection-box') as HTMLDivElement | null
  if (!box || !containerEl.contains(box)) {
    box = document.createElement('div')
    box.className = 'tdx-chart-selection-box'
    box.style.cssText = 'position: absolute; border: 1.5px dashed #38bdf8; background: rgba(56, 189, 248, 0.18); pointer-events: none; z-index: 999; display: none; box-shadow: 0 0 10px rgba(56, 189, 248, 0.5); border-radius: 2px;'
    containerEl.appendChild(box)
  }
  return box
}

function bindRightClickSelection(containerEl: HTMLElement | null, getInstance: () => echarts.ECharts | null, getData: () => any) {
  if (!containerEl) return
  ;(containerEl as any)._tdxGetInstance = getInstance
  ;(containerEl as any)._tdxGetData = getData
  ensureChartSelectionBoxVue(containerEl)

  if ((containerEl as any)._tdxSelectionBound) return
  ;(containerEl as any)._tdxSelectionBound = true

  let isSelecting = false
  let startX = 0, startY = 0
  let hasDragged = false

  // 彻底拦截图表容器上的原生右键菜单，杜绝打断水平拖拽
  containerEl.addEventListener('contextmenu', (e: MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }, true)

  containerEl.addEventListener('mousedown', (e) => {
    if (e.button !== 2) return
    e.preventDefault()
    e.stopPropagation()

    const box = ensureChartSelectionBoxVue(containerEl)
    const rect = containerEl.getBoundingClientRect()
    startX = Math.max(0, Math.min(rect.width, e.clientX - rect.left))
    startY = Math.max(0, Math.min(rect.height, e.clientY - rect.top))
    isSelecting = true
    hasDragged = false

    if (box) {
      const oldHeader = box.querySelector('.tdx-box-header')
      if (oldHeader) oldHeader.remove()
      box.style.left = `${startX}px`
      box.style.top = `${startY}px`
      box.style.width = '0px'
      box.style.height = '0px'
      box.style.display = 'block'
      activeSelectionBoxEl = box
    }
  }, true)

  window.addEventListener('mousemove', (e) => {
    if (!isSelecting) return
    const box = ensureChartSelectionBoxVue(containerEl)
    const rect = containerEl.getBoundingClientRect()
    const curX = Math.max(0, Math.min(rect.width, e.clientX - rect.left))
    const curY = Math.max(0, Math.min(rect.height, e.clientY - rect.top))

    const left = Math.min(startX, curX)
    const top = Math.min(startY, curY)
    const width = Math.abs(curX - startX)
    const height = Math.abs(curY - startY)

    if (box) {
      box.style.left = `${left}px`
      box.style.top = `${top}px`
      box.style.width = `${width}px`
      box.style.height = `${height}px`
    }

    if (width > 5 || height > 5) {
      hasDragged = true
      if (box) {
        const oldH = box.querySelector('.tdx-box-header')
        if (oldH) oldH.remove()
      }
    }
  }, true)

  window.addEventListener('mouseup', (e) => {
    if (!isSelecting || e.button !== 2) return
    isSelecting = false
    const box = ensureChartSelectionBoxVue(containerEl)

    if (!hasDragged) {
      if (box) box.style.display = 'none'
      return
    }

    const instanceGetter = (containerEl as any)._tdxGetInstance || getInstance
    const chart = (typeof instanceGetter === 'function' ? instanceGetter() : instanceGetter) || (echarts.getInstanceByDom(containerEl) as any)
    if (!chart) {
      if (box) box.style.display = 'none'
      return
    }

    const rect = containerEl.getBoundingClientRect()
    const endX = Math.max(0, Math.min(rect.width, e.clientX - rect.left))
    const minX = Math.min(startX, endX)
    const maxX = Math.max(startX, endX)

    let startIdx = -1
    let endIdx = -1

    const midY = Math.max(10, rect.height * 0.4)
    try {
      const p1 = chart.convertFromPixel({ seriesIndex: 0 }, [minX, midY]) as number[]
      const p2 = chart.convertFromPixel({ seriesIndex: 0 }, [maxX, midY]) as number[]
      if (p1 && p2 && !isNaN(p1[0]) && !isNaN(p2[0])) {
        startIdx = Math.round(p1[0])
        endIdx = Math.round(p2[0])
      }
    } catch (err) {}

    if (startIdx === -1 || endIdx === -1) {
      try {
        const p1 = chart.convertFromPixel({ gridIndex: 0 }, [minX, midY]) as number[]
        const p2 = chart.convertFromPixel({ gridIndex: 0 }, [maxX, midY]) as number[]
        if (p1 && p2 && !isNaN(p1[0]) && !isNaN(p2[0])) {
          startIdx = Math.round(p1[0])
          endIdx = Math.round(p2[0])
        }
      } catch (err2) {}
    }

    const dataGetter = (containerEl as any)._tdxGetData || getData
    const d = (typeof dataGetter === 'function') ? dataGetter() : dataGetter
    let uc = d?.unified_chart
    if (!uc) {
      try {
        const opt = chart.getOption() as any
        const csSeries = opt && opt.series && opt.series.find((s: any) => s.type === 'candlestick')
        const dates = (opt && opt.xAxis && opt.xAxis[0] && opt.xAxis[0].data) || []
        if (csSeries && csSeries.data && dates.length > 0) {
          uc = {
            dates,
            candles: csSeries.data,
            volumes: [],
            amounts: []
          }
        }
      } catch (_) {}
    }

    if (!uc || startIdx === -1 || endIdx === -1) {
      if (box) box.style.display = 'none'
      return
    }

    const stats = calcRangeStatistics(uc, startIdx, endIdx, d?.name || code.value, d?.code || code.value)
    if (stats) {
      currentStat.value = stats
      if (box) {
        let header = box.querySelector('.tdx-box-header') as HTMLDivElement | null
        if (!header) {
          header = document.createElement('div')
          header.className = 'tdx-box-header'
          box.appendChild(header)
        }
        const isUp = (Number(stats.chgPct || 0) >= 0)
        const colorHex = isUp ? '#f43f5e' : '#10b981'
        const sign = isUp ? '+' : ''
        header.innerHTML = `<span>周期: <strong style="color:#38bdf8">${stats.periodCount}</strong>根</span> <span style="opacity:0.5">|</span> <span>涨跌: <strong style="color:${colorHex}">${sign}${stats.chgPct}%</strong></span> <span style="opacity:0.5">|</span> <span>振幅: <strong style="color:#fbbf24">${stats.ampPct}%</strong></span>`
        header.style.cssText = 'position: absolute; top: -28px; left: 0; background: rgba(15, 23, 42, 0.95); color: #e2e8f0; font-size: 11px; font-family: monospace; padding: 3px 8px; border-radius: 4px; border: 1px solid rgba(56, 189, 248, 0.7); white-space: nowrap; pointer-events: none; z-index: 1000; box-shadow: 0 4px 14px rgba(0,0,0,0.6); display: flex; gap: 6px; align-items: center;'
      }
      let posX = e.clientX + 15
      let posY = e.clientY + 15
      const modalW = 360
      const modalH = 490
      if (posX + modalW > window.innerWidth) posX = Math.max(10, e.clientX - modalW - 15)
      if (posY + modalH > window.innerHeight) posY = Math.max(10, window.innerHeight - modalH - 20)
      statModalPos.value = { x: posX, y: posY }
      showRangeStatModal.value = true
    } else {
      if (box) box.style.display = 'none'
    }
  }, true)

  window.addEventListener('contextmenu', (e: MouseEvent) => {
    if (isSelecting || hasDragged) {
      e.preventDefault()
      e.stopPropagation()
    }
  }, true)
}

function attachSelectionToAllCharts() {
  bindRightClickSelection(chartContainerLeft.value, () => chartInstanceLeft, () => chanDataLeft.value)
  if (splitMode.value === 'quad') {
    bindRightClickSelection(chartContainerW2.value, () => chartInstanceW2, () => chanDataW2.value)
    bindRightClickSelection(chartContainerRight.value, () => chartInstanceRight, () => chanDataRight.value)
    bindRightClickSelection(chartContainerW4.value, () => chartInstanceW4, () => chanDataW4.value)
  } else if (splitMode.value === 'dual') {
    bindRightClickSelection(chartContainerRight.value, () => chartInstanceRight, () => chanDataRight.value)
  }
}

function closeRangeStatModal() {
  showRangeStatModal.value = false
  if (!statKeepBox.value && activeSelectionBoxEl) {
    activeSelectionBoxEl.style.display = 'none'
    const h = activeSelectionBoxEl.querySelector('.tdx-box-header')
    if (h) h.remove()
  }
}

// 弹窗拖拽移动
function onStatModalHeaderMousedown(e: MouseEvent) {
  if (e.button !== 0) return
  const startMouseX = e.clientX
  const startMouseY = e.clientY
  const startPosX = statModalPos.value.x
  const startPosY = statModalPos.value.y

  function onMouseMove(ev: MouseEvent) {
    statModalPos.value = {
      x: Math.max(0, Math.min(window.innerWidth - 360, startPosX + ev.clientX - startMouseX)),
      y: Math.max(0, Math.min(window.innerHeight - 490, startPosY + ev.clientY - startMouseY))
    }
  }
  function onMouseUp() {
    window.removeEventListener('mousemove', onMouseMove)
    window.removeEventListener('mouseup', onMouseUp)
  }
  window.addEventListener('mousemove', onMouseMove)
  window.addEventListener('mouseup', onMouseUp)
}

function triggerPatternMatchFromStat() {
  if (!currentStat.value || !currentStat.value.targetPrices || currentStat.value.targetPrices.length < 3) {
    alert('请先框选至少 3 根 K 线的有效形态区间')
    return
  }
  currentPmPrices = currentStat.value.targetPrices
  currentPmSymbol = currentStat.value.stockCode
  pmTargetBadge.value = `模板: ${currentStat.value.stockName} (${currentStat.value.stockCode}) · ${currentStat.value.startDate} ~ ${currentStat.value.endDate} (${currentPmPrices.length}根K线)`
  showPatternMatchModal.value = true
  runPatternMatchScan()
}

async function runPatternMatchScan() {
  if (!currentPmPrices || currentPmPrices.length < 3) return
  pmScanning.value = true
  pmStatusText.value = '正在全市场计算匹配度...'
  pmMatches.value = []

  try {
    const resp = await fetch('/api/screener/pattern-match', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target_prices: currentPmPrices,
        target_symbol: currentPmSymbol,
        universe: pmUniverse.value,
        top_n: 30
      })
    })
    const res = await resp.json()
    if (res.status === 'success') {
      pmStatusText.value = `扫描完成: 耗时 ${res.cost_seconds}s · 扫描 ${res.total_scanned} 只 · 匹配到 ${res.matched_count} 只`
      pmTargetPoints.value = res.target_points || []
      pmMatches.value = res.matches || []
    } else {
      pmStatusText.value = `匹配失败: ${res.message || '未知错误'}`
    }
  } catch (e: any) {
    pmStatusText.value = `网络请求异常: ${e.message || e}`
  } finally {
    pmScanning.value = false
  }
}

function selectMatchedStock(code: string) {
  showPatternMatchModal.value = false
  selectStock(code)
}

function renderPatternSparklineSvg(targetNorm: number[], candNorm: number[]): string {
  if (!candNorm || candNorm.length < 2) return ''
  const w = 110
  const h = 26
  const pad = 3
  const n = candNorm.length
  const step = (w - pad * 2) / (n - 1)

  let tPath = ''
  if (targetNorm && targetNorm.length === n) {
    targetNorm.forEach((v, i) => {
      const x = pad + i * step
      const y = h - pad - (v / 100) * (h - pad * 2)
      tPath += (i === 0 ? `M ${x.toFixed(1)} ${y.toFixed(1)}` : ` L ${x.toFixed(1)} ${y.toFixed(1)}`)
    })
  }

  let cPath = ''
  candNorm.forEach((v, i) => {
    const x = pad + i * step
    const y = h - pad - (v / 100) * (h - pad * 2)
    cPath += (i === 0 ? `M ${x.toFixed(1)} ${y.toFixed(1)}` : ` L ${x.toFixed(1)} ${y.toFixed(1)}`)
  })

  return `<svg width="${w}" height="${h}" class="inline-block overflow-visible">
    ${tPath ? `<path d="${tPath}" fill="none" stroke="#a855f7" stroke-width="1.2" stroke-dasharray="2,2" opacity="0.75" />` : ''}
    <path d="${cPath}" fill="none" stroke="#eab308" stroke-width="1.6" stroke-linecap="round" />
  </svg>`
}

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeyDown)
  if (clockTimer) {
    clearInterval(clockTimer)
    clockTimer = null
  }
  stopAutoRefresh()
  stopReplay()
  window.removeEventListener('resize', handleResize)
  if (chartInstanceLeft) {
    chartInstanceLeft.dispose()
    chartInstanceLeft = null
  }
  if (chartInstanceW2) {
    chartInstanceW2.dispose()
    chartInstanceW2 = null
  }
  if (chartInstanceRight) {
    chartInstanceRight.dispose()
    chartInstanceRight = null
  }
  if (chartInstanceW4) {
    chartInstanceW4.dispose()
    chartInstanceW4 = null
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
        <!-- 实时刷新与休市开关 + 加入/移出自选 -->
        <div class="refresh-box">
          <button
            class="tool-btn"
            :class="{ active: autoRefresh && inTradeSession, pulsing: autoRefresh && inTradeSession, closed: !inTradeSession }"
            @click="toggleAutoRefresh"
            :title="inTradeSession ? (autoRefresh ? `点击暂停实时轮询 (当前周期: ${periodLowLabel}，每 ${periodLowSeconds} 秒自动刷新一次，支持手动立即刷新)` : `点击开启实时自动刷新 (当前周期: ${periodLowLabel}，每 ${periodLowSeconds} 秒自动刷新一次)`) : 'A股非交易时段 自动更新已休眠 (休市中，点击可立即手动刷新最新盘后数据)'"
          >
            <span class="dot" :class="{ live: autoRefresh && inTradeSession }"></span>
            {{ inTradeSession ? (autoRefresh ? `实时: ${periodLowLabel} (${periodLowSeconds}s)` : '实时: 关') : '休市' }}
          </button>
          <button
            class="tool-btn watchlist-btn"
            :class="{ active: isInWatchlist }"
            @click="toggleWatchlist"
            :title="isInWatchlist ? `【${code}】已在自选池中，点击移出 (watchlist.json)` : `点击将【${code}】加入自选监控池 (watchlist.json)`"
          >
            <span>{{ isInWatchlist ? '★ 删除' : '☆ 加入' }}</span>
          </button>
          <button class="icon-btn" @click="loadData(true)" :title="`立即刷新最新${periodLowLabel}K线数据`">
            🔄
          </button>
        </div>

        <!-- 四窗口 / 双窗口 / 单窗口 切换按钮 -->
        <div class="mode-switch-box">
          <button
            class="mode-btn"
            :class="{ active: splitMode === 'quad' }"
            @click="setSplitMode('quad')"
            title="四窗口布局 (日·30F·周·月)"
          >
            ⊞ 四窗口
          </button>
          <button
            class="mode-btn"
            :class="{ active: splitMode === 'dual' }"
            @click="setSplitMode('dual')"
            title="上下双窗口对比 (上: 窗1，下: 窗3)"
          >
            ⬒ 双窗口
          </button>
          <button
            class="mode-btn"
            :class="{ active: splitMode === 'single' }"
            @click="setSplitMode('single')"
            title="单窗口全屏显示"
          >
            ⬜ 单窗口
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
        <div class="state-chip high" :style="{ borderLeftColor: getPeriodTheme(chanData.periods.high.key).primary }">
          <span class="chip-title">【大级别·<span :style="{ color: getPeriodTheme(chanData.periods.high.key).primary }">{{ chanData.periods.high.name }}</span>】</span>
          <span class="chip-val">{{ chanData.summary.high_state.detail }}</span>
        </div>
        <div class="state-chip mid" :style="{ borderLeftColor: getPeriodTheme(chanData.periods.mid.key).primary }">
          <span class="chip-title">【中级别·<span :style="{ color: getPeriodTheme(chanData.periods.mid.key).primary }">{{ chanData.periods.mid.name }}</span>】</span>
          <span class="chip-val">{{ chanData.summary.mid_state.detail }}</span>
        </div>
        <div class="state-chip low" :style="{ borderLeftColor: getPeriodTheme(chanData.periods.low.key).primary }">
          <span class="chip-title">【基准小·<span :style="{ color: getPeriodTheme(chanData.periods.low.key).primary }">{{ chanData.periods.low.name }}</span>】</span>
          <span class="chip-val">{{ chanData.summary.low_state.detail }}</span>
        </div>
        <div class="state-chip resonance-stat">
          <span class="chip-title">共振买卖点</span>
          <span class="chip-badge">{{ chanData.resonances.length }} 处</span>
        </div>
      </div>
    </section>

    <!-- 紧凑级联菜单控制栏 (窗口 + 主图图层 + 副图) -->
    <div class="controls-bar">
      <div class="cascading-controls-row">
        <!-- 1. 窗口级联选择 -->
        <div class="control-group">
          <span class="label">窗口:</span>
          <select v-model="splitMode" class="cascading-select" @change="setSplitMode(splitMode)">
            <option value="quad">⊞ 四窗口 (日·30F·周·月)</option>
            <option value="dual">⬒ 双窗口 (上下对比)</option>
            <option value="single">⬜ 单窗口 (全宽显示)</option>
          </select>
        </div>

        <span class="sub-sep">|</span>

        <!-- 4. 统一周期色彩指引条 -->
        <div class="control-group period-color-legend">
          <span class="label">周期色标:</span>
          <span class="p-color-item" style="color: #7c3aed;">●月(紫)</span>
          <span class="p-color-item" style="color: #2563eb;">●周(蓝)</span>
          <span class="p-color-item" style="color: #059669;">●日(绿)</span>
          <span class="p-color-item" style="color: #d97706;">●30F(黄)</span>
          <span class="p-color-item" style="color: #0284c7;">●5F(青)</span>
          <span class="p-color-item" style="color: #ff1f1f;">●1F(鲜红)</span>
        </div>

        <span class="sub-sep">|</span>

        <!-- 2. 主图图层 级联菜单 (显示全部元素，带 √ 表示 enable显示，否则 disable不显示) -->
        <div class="control-group">
          <span class="label">主图:</span>
          <select class="cascading-select" @change="onMainLayersSelect($event)">
            <option value="" disabled selected>图层开关 ({{ activeLayersCount }}/8)</option>
            <option value="highBi">大级别笔 {{ showHighBi ? '√' : '' }}</option>
            <option value="highZs">大级别中枢 {{ showHighZs ? '√' : '' }}</option>
            <option value="midBi">中级别笔 {{ showMidBi ? '√' : '' }}</option>
            <option value="midZs">中级别中枢 {{ showMidZs ? '√' : '' }}</option>
            <option value="lowBi">小级别笔 {{ showLowBi ? '√' : '' }}</option>
            <option value="lowZs">小级别中枢 {{ showLowZs ? '√' : '' }}</option>
            <option value="mmd">买卖点 {{ showMmdMarks ? '√' : '' }}</option>
            <option value="res">★共振信号 {{ showResonanceMarks ? '√' : '' }}</option>
            <option value="__ALL_ON__">── 全部开启 √ ──</option>
            <option value="__ALL_OFF__">── 全部关闭 ──</option>
          </select>
        </div>

        <span class="sub-sep">|</span>

        <!-- 3. 副图级联选择 -->
        <div class="control-group">
          <span class="label">副图:</span>
          <select v-model="subIndicator" class="cascading-select" @change="renderChart">
            <option value="amount">成交额</option>
            <option value="inflow">主力净流入</option>
            <option value="macd">MACD</option>
            <option value="rsi">RSI</option>
            <option value="kdj">KDJ</option>
            <option value="expma">EXPMA</option>
            <option value="none">关闭副图</option>
          </select>
        </div>

        <span class="sub-sep">|</span>

        <!-- 4. K线合并开关 (严格按缠论包含关系标准合并K线，默认关闭) -->
        <div class="control-group">
          <label class="merge-toggle-label" title="开启后，所有K线窗口严格按照缠论包含关系标准显示合并后的K线图">
            <input type="checkbox" v-model="isKlineMerged" @change="renderChart" class="merge-checkbox" />
            <span class="merge-label-text">K线合并</span>
          </label>
        </div>
      </div>
    </div>

    <!-- 历史回溯时光机操作条（激活时显示） -->
    <div v-if="isBacktrackingMode" class="backtrack-panel">
      <div class="backtrack-header">
        <div class="backtrack-title">
          <span>🕰️ 历史回溯推演态 (无未来函数)</span>
          <span class="current-cutoff">截断时间: <b>{{ backtrackDate || '最新' }}</b> (窗{{ activeWindowNum }}主控: {{ backtrackIndex + 1 }} / {{ availableDates.length }} 根K线)</span>
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
        <span class="slider-bound">{{ getActiveWindowData()?.backtrack_timeline?.min_date || chanData?.backtrack_timeline?.min_date }}</span>
        <input
          type="range"
          min="0"
          :max="maxBacktrackIndex"
          :value="backtrackIndex"
          class="time-slider"
          @input="onSliderInput"
          @change="onSliderChange"
        />
        <span class="slider-bound">{{ getActiveWindowData()?.backtrack_timeline?.max_date || chanData?.backtrack_timeline?.max_date }}</span>
      </div>
    </div>

    <!-- 主图表区 (支持单窗口 / 双窗口 / 四窗口) -->
    <div class="charts-split-container" :class="{ 'is-quad': splitMode === 'quad', 'is-dual': splitMode === 'dual' }">
      <!-- 窗口 1: 周·日·30F (左窗/第1窗) -->
      <div
        class="chart-window-card left-card"
        :class="{ 'is-active-window': activeWindow === 'left' }"
        :style="cardHeight ? { height: cardHeight + 'px' } : undefined"
        @click="setActiveWindow('left')"
      >
        <div class="window-card-header">
          <div class="win-tag-box">
            <span class="win-pill left-pill">
              <span class="win-idx">窗1:</span>
              <template v-if="chanDataLeft?.summary?.is_single_period">
                <span class="p-dot-item" :style="{ color: getPeriodTheme(chanDataLeft?.periods?.low?.key || '30F').primary }">●{{ chanDataLeft?.periods?.low?.name || '30F' }}</span>
              </template>
              <template v-else>
                <span class="p-dot-item" :style="{ color: getPeriodTheme(chanDataLeft?.periods?.high?.key || 'WEEK').primary }">●{{ chanDataLeft?.periods?.high?.name || '周' }}</span>
                <span class="p-dot-sep">·</span>
                <span class="p-dot-item" :style="{ color: getPeriodTheme(chanDataLeft?.periods?.mid?.key || 'DAY').primary }">●{{ chanDataLeft?.periods?.mid?.name || '日' }}</span>
                <span class="p-dot-sep">·</span>
                <span class="p-dot-item" :style="{ color: getPeriodTheme(chanDataLeft?.periods?.low?.key || '30F').primary }">●{{ chanDataLeft?.periods?.low?.name || '30F' }}</span>
              </template>
              <span v-if="activeWindow === 'left'" class="win-active-badge">主控回溯</span>
            </span>
            <div class="win-stock-header-info">
              <span class="win-stock-title">{{ chanDataLeft?.code }} {{ chanDataLeft?.name }}</span>
              <span v-if="candleInfoLeft" class="win-stock-price" :class="candleInfoLeft.colorClass">{{ candleInfoLeft.priceStr }}</span>
              <span v-if="candleInfoLeft" class="win-stock-chg" :class="candleInfoLeft.colorClass">{{ candleInfoLeft.chgStr }}</span>
            </div>
          </div>
          <div class="win-tools-box">
            <select
              :value="leftPeriods"
              class="win-preset-select"
              @change="applyWindowPreset('left', ($event.target as HTMLSelectElement).value)"
            >
              <option v-for="p in periodPresets" :key="p.value" :value="p.value">{{ p.label }}</option>
            </select>
          </div>
        </div>

        <div v-if="loading && !chanDataLeft" class="chart-loading-overlay">
          <div class="spinner"></div>
          <span>正在运行窗口1缠论立体共振计算...</span>
        </div>
        <div v-if="errorMsg" class="chart-error-banner">
          ⚠️ {{ errorMsg }}
        </div>

        <div ref="chartContainerLeft" class="main-echart"></div>
      </div>

      <!-- 窗口 2: 月·周·日 (四窗口模式激活时显示) -->
      <div
        v-if="splitMode === 'quad'"
        class="chart-window-card w2-card"
        :class="{ 'is-active-window': activeWindow === 'w2' }"
        :style="cardHeight ? { height: cardHeight + 'px' } : undefined"
        @click="setActiveWindow('w2')"
      >
        <div class="window-card-header">
          <div class="win-tag-box">
            <span class="win-pill w2-pill">
              <span class="win-idx">窗2:</span>
              <template v-if="chanDataW2?.summary?.is_single_period">
                <span class="p-dot-item" :style="{ color: getPeriodTheme(chanDataW2?.periods?.low?.key || 'DAY').primary }">●{{ chanDataW2?.periods?.low?.name || '日' }}</span>
              </template>
              <template v-else>
                <span class="p-dot-item" :style="{ color: getPeriodTheme(chanDataW2?.periods?.high?.key || 'MONTH').primary }">●{{ chanDataW2?.periods?.high?.name || '月' }}</span>
                <span class="p-dot-sep">·</span>
                <span class="p-dot-item" :style="{ color: getPeriodTheme(chanDataW2?.periods?.mid?.key || 'WEEK').primary }">●{{ chanDataW2?.periods?.mid?.name || '周' }}</span>
                <span class="p-dot-sep">·</span>
                <span class="p-dot-item" :style="{ color: getPeriodTheme(chanDataW2?.periods?.low?.key || 'DAY').primary }">●{{ chanDataW2?.periods?.low?.name || '日' }}</span>
              </template>
              <span v-if="activeWindow === 'w2'" class="win-active-badge">主控回溯</span>
            </span>
            <div class="win-stock-header-info">
              <span class="win-stock-title">{{ chanDataW2?.code }} {{ chanDataW2?.name }}</span>
              <span v-if="candleInfoW2" class="win-stock-price" :class="candleInfoW2.colorClass">{{ candleInfoW2.priceStr }}</span>
              <span v-if="candleInfoW2" class="win-stock-chg" :class="candleInfoW2.colorClass">{{ candleInfoW2.chgStr }}</span>
            </div>
          </div>
          <div class="win-tools-box">
            <select
              :value="w2Periods"
              class="win-preset-select"
              @change="applyWindowPreset('w2', ($event.target as HTMLSelectElement).value)"
            >
              <option v-for="p in periodPresets" :key="p.value" :value="p.value">{{ p.label }}</option>
            </select>
          </div>
        </div>

        <div v-if="loading && !chanDataW2" class="chart-loading-overlay">
          <div class="spinner"></div>
          <span>正在运行窗口2缠论立体共振计算...</span>
        </div>

        <div ref="chartContainerW2" class="main-echart"></div>
      </div>

      <!-- 窗口 3: 日·30F·5F (双窗口或四窗口激活时显示) -->
      <div
        v-if="splitMode === 'dual' || splitMode === 'quad'"
        class="chart-window-card right-card"
        :class="{ 'is-active-window': activeWindow === 'right' }"
        :style="cardHeight ? { height: cardHeight + 'px' } : undefined"
        @click="setActiveWindow('right')"
      >
        <div class="window-card-header">
          <div class="win-tag-box">
            <span class="win-pill right-pill">
              <span class="win-idx">窗3:</span>
              <template v-if="chanDataRight?.summary?.is_single_period">
                <span class="p-dot-item" :style="{ color: getPeriodTheme(chanDataRight?.periods?.low?.key || '5F').primary }">●{{ chanDataRight?.periods?.low?.name || '5F' }}</span>
              </template>
              <template v-else>
                <span class="p-dot-item" :style="{ color: getPeriodTheme(chanDataRight?.periods?.high?.key || 'DAY').primary }">●{{ chanDataRight?.periods?.high?.name || '日' }}</span>
                <span class="p-dot-sep">·</span>
                <span class="p-dot-item" :style="{ color: getPeriodTheme(chanDataRight?.periods?.mid?.key || '30F').primary }">●{{ chanDataRight?.periods?.mid?.name || '30F' }}</span>
                <span class="p-dot-sep">·</span>
                <span class="p-dot-item" :style="{ color: getPeriodTheme(chanDataRight?.periods?.low?.key || '5F').primary }">●{{ chanDataRight?.periods?.low?.name || '5F' }}</span>
              </template>
              <span v-if="activeWindow === 'right'" class="win-active-badge">主控回溯</span>
            </span>
            <div class="win-stock-header-info">
              <span class="win-stock-title">{{ chanDataRight?.code }} {{ chanDataRight?.name }}</span>
              <span v-if="candleInfoRight" class="win-stock-price" :class="candleInfoRight.colorClass">{{ candleInfoRight.priceStr }}</span>
              <span v-if="candleInfoRight" class="win-stock-chg" :class="candleInfoRight.colorClass">{{ candleInfoRight.chgStr }}</span>
            </div>
          </div>
          <div class="win-tools-box">
            <select
              :value="rightPeriods"
              class="win-preset-select"
              @change="applyWindowPreset('right', ($event.target as HTMLSelectElement).value)"
            >
              <option v-for="p in periodPresets" :key="p.value" :value="p.value">{{ p.label }}</option>
            </select>
          </div>
        </div>

        <div v-if="loading && !chanDataRight" class="chart-loading-overlay">
          <div class="spinner"></div>
          <span>正在运行窗口3缠论立体共振计算...</span>
        </div>

        <div ref="chartContainerRight" class="main-echart"></div>
      </div>

      <!-- 窗口 4: 30F·5F·1F (四窗口模式激活时显示) -->
      <div
        v-if="splitMode === 'quad'"
        class="chart-window-card w4-card"
        :class="{ 'is-active-window': activeWindow === 'w4' }"
        :style="cardHeight ? { height: cardHeight + 'px' } : undefined"
        @click="setActiveWindow('w4')"
      >
        <div class="window-card-header">
          <div class="win-tag-box">
            <span class="win-pill w4-pill">
              <span class="win-idx">窗4:</span>
              <template v-if="chanDataW4?.summary?.is_single_period">
                <span class="p-dot-item" :style="{ color: getPeriodTheme(chanDataW4?.periods?.low?.key || '1F').primary }">●{{ chanDataW4?.periods?.low?.name || '1F' }}</span>
              </template>
              <template v-else>
                <span class="p-dot-item" :style="{ color: getPeriodTheme(chanDataW4?.periods?.high?.key || '30F').primary }">●{{ chanDataW4?.periods?.high?.name || '30F' }}</span>
                <span class="p-dot-sep">·</span>
                <span class="p-dot-item" :style="{ color: getPeriodTheme(chanDataW4?.periods?.mid?.key || '5F').primary }">●{{ chanDataW4?.periods?.mid?.name || '5F' }}</span>
                <span class="p-dot-sep">·</span>
                <span class="p-dot-item" :style="{ color: getPeriodTheme(chanDataW4?.periods?.low?.key || '1F').primary }">●{{ chanDataW4?.periods?.low?.name || '1F' }}</span>
              </template>
              <span v-if="activeWindow === 'w4'" class="win-active-badge">主控回溯</span>
            </span>
            <div class="win-stock-header-info">
              <span class="win-stock-title">{{ chanDataW4?.code }} {{ chanDataW4?.name }}</span>
              <span v-if="candleInfoW4" class="win-stock-price" :class="candleInfoW4.colorClass">{{ candleInfoW4.priceStr }}</span>
              <span v-if="candleInfoW4" class="win-stock-chg" :class="candleInfoW4.colorClass">{{ candleInfoW4.chgStr }}</span>
            </div>
          </div>
          <div class="win-tools-box">
            <select
              :value="w4Periods"
              class="win-preset-select"
              @change="applyWindowPreset('w4', ($event.target as HTMLSelectElement).value)"
            >
              <option v-for="p in periodPresets" :key="p.value" :value="p.value">{{ p.label }}</option>
            </select>
          </div>
        </div>

        <div v-if="loading && !chanDataW4" class="chart-loading-overlay">
          <div class="spinner"></div>
          <span>正在运行窗口4缠论立体共振计算...</span>
        </div>

        <div ref="chartContainerW4" class="main-echart"></div>
      </div>
    </div>

    <!-- ==================== 通达信风格 区间统计(复权) 弹窗 ==================== -->
    <Teleport to="body">
      <div
        v-if="showRangeStatModal && currentStat"
        id="tdx-range-stat-modal"
        class="tdx-modal-window"
        :style="{ left: statModalPos.x + 'px', top: statModalPos.y + 'px' }"
      >
        <div class="tdx-modal-header" @mousedown="onStatModalHeaderMousedown">
          <span class="tdx-modal-title">{{ currentStat.stockName }} 区间统计(复权)</span>
          <button class="tdx-modal-close" @click="closeRangeStatModal">&times;</button>
        </div>

      <div class="tdx-modal-body">
        <div class="tdx-row-between">
          <div class="tdx-field-inline">
            <span class="tdx-label">起始时间</span>
            <input type="text" readonly :value="currentStat.startDate.split(' ')[0]" class="tdx-input-ro tdx-w-date" />
          </div>
          <div class="tdx-count-info">
            周期数 <strong class="color-up">{{ currentStat.periodCount }}</strong>个
          </div>
        </div>

        <div class="tdx-row-between">
          <div class="tdx-field-inline">
            <span class="tdx-label">截止时间</span>
            <input type="text" readonly :value="currentStat.endDate.split(' ')[0]" class="tdx-input-ro tdx-w-date" />
          </div>
          <div class="tdx-count-info">
            自然日 <strong style="color: #38bdf8;">{{ currentStat.calendarDays }}</strong>天
          </div>
        </div>

        <div class="tdx-split-grid">
          <!-- 左侧指标列表 -->
          <div class="tdx-metrics-col">
            <div class="tdx-metric-row"><span class="tdx-label">前收盘价</span><input type="text" readonly :value="currentStat.prevClose" class="tdx-input-ro" /></div>
            <div class="tdx-metric-row"><span class="tdx-label">开盘价</span><input type="text" readonly :value="currentStat.openPrice" class="tdx-input-ro" /></div>
            <div class="tdx-metric-row"><span class="tdx-label">最高价</span><input type="text" readonly :value="currentStat.highPrice" class="tdx-input-ro color-up font-bold" /></div>
            <div class="tdx-metric-row"><span class="tdx-label">最低价</span><input type="text" readonly :value="currentStat.lowPrice" class="tdx-input-ro color-down font-bold" /></div>
            <div class="tdx-metric-row"><span class="tdx-label">收盘价</span><input type="text" readonly :value="currentStat.closePrice" class="tdx-input-ro font-bold" /></div>
            <div class="tdx-metric-row"><span class="tdx-label">成交量</span><input type="text" readonly :value="currentStat.totalVol" class="tdx-input-ro" /></div>
            <div class="tdx-metric-row"><span class="tdx-label">成交额</span><input type="text" readonly :value="currentStat.totalAmtStr" class="tdx-input-ro text-amber-400 font-bold" /></div>
            <div class="tdx-metric-row"><span class="tdx-label">收盘平均</span><input type="text" readonly :value="currentStat.avgClose" class="tdx-input-ro" /></div>
            <div class="tdx-metric-row"><span class="tdx-label">加权均价</span><input type="text" readonly :value="currentStat.weightedAvg" class="tdx-input-ro text-amber-300" /></div>
            <div class="tdx-metric-row"><span class="tdx-label">区间涨幅</span><input type="text" readonly :value="`${currentStat.chgDiff} (${currentStat.chgPct}%)`" class="tdx-input-ro font-bold" :class="Number(currentStat.chgPct) >= 0 ? 'color-up' : 'color-down'" /></div>
            <div class="tdx-metric-row"><span class="tdx-label">区间振幅</span><input type="text" readonly :value="`${currentStat.ampDiff} (${currentStat.ampPct}%)`" class="tdx-input-ro font-bold" /></div>
            <div class="tdx-metric-row"><span class="tdx-label">最大上涨</span><input type="text" readonly :value="`+${currentStat.maxGain}%`" class="tdx-input-ro color-up font-bold" /></div>
            <div class="tdx-metric-row"><span class="tdx-label">最大回撤</span><input type="text" readonly :value="`${currentStat.maxDrawdown}%`" class="tdx-input-ro color-down font-bold" /></div>
            <div class="tdx-metric-row"><span class="tdx-label">累计换手</span><input type="text" readonly :value="currentStat.totalTurnover" class="tdx-input-ro" /></div>
            <div class="tdx-metric-row"><span class="tdx-label">平均换手</span><input type="text" readonly :value="currentStat.avgTurnover" class="tdx-input-ro" /></div>
            <div class="tdx-metric-row"><span class="tdx-label">年化收益</span><input type="text" readonly :value="currentStat.annualized" class="tdx-input-ro font-bold" :class="currentStat.annualized.startsWith('+') ? 'color-up' : 'color-down'" /></div>
          </div>

          <!-- 右侧统计与操作 -->
          <div class="tdx-actions-col">
            <div class="tdx-bars-summary">
              <div class="tdx-stat-item"><span>阳线</span><strong class="color-up">{{ currentStat.upBars }}个</strong></div>
              <div class="tdx-stat-item"><span>阴线</span><strong class="color-down">{{ currentStat.downBars }}个</strong></div>
              <div class="tdx-stat-item"><span>平线</span><span>{{ currentStat.flatBars }}个</span></div>
              <div class="tdx-hr"></div>
              <div class="tdx-stat-item"><span>上涨</span><strong class="color-up">{{ currentStat.gainDays }}个</strong></div>
              <div class="tdx-stat-item"><span>下跌</span><strong class="color-down">{{ currentStat.loseDays }}个</strong></div>
              <div class="tdx-stat-item"><span>平盘</span><span>{{ currentStat.evenDays }}个</span></div>
            </div>

            <div class="tdx-btns-box">
              <button class="tdx-btn-pattern" @click="triggerPatternMatchFromStat">✨ 形态匹配</button>
              <button class="tdx-btn-close" @click="closeRangeStatModal">关闭</button>
              <label class="tdx-checkbox-label">
                <input v-model="statKeepBox" type="checkbox" />
                <span>保留区间线</span>
              </label>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>

    <!-- ==================== 形态匹配选股 弹窗 ==================== -->
    <Teleport to="body">
      <div v-if="showPatternMatchModal" class="tdx-pm-overlay" @click.self="showPatternMatchModal = false">
        <div class="tdx-pm-modal">
          <div class="tdx-pm-header">
            <div class="tdx-pm-title-box">
            <span class="tdx-pm-icon">✨</span>
            <div>
              <div class="tdx-pm-title">
                <span>形态匹配选股 (Pattern Matching)</span>
                <span class="tdx-pm-badge">{{ pmTargetBadge }}</span>
              </div>
              <div class="tdx-pm-subtitle">基于皮尔逊相关系数算法，在指定股票池中寻找走势形态最相似的标的</div>
            </div>
          </div>
          <button class="tdx-modal-close" @click="showPatternMatchModal = false">&times;</button>
        </div>

        <div class="tdx-pm-toolbar">
          <div class="tdx-pm-filter">
            <span>股票池:</span>
            <select v-model="pmUniverse" class="tdx-pm-select" @change="runPatternMatchScan">
              <option value="core">核心流动性龙头池 (159只 · 推荐极速)</option>
              <option value="hs300">沪深 300 权重池 (300只)</option>
              <option value="zz500">中证 500 主力池 (500只)</option>
              <option value="zz1000">中证 1000 活跃池 (1000只)</option>
              <option value="all">全市场 A 股 (5200+只)</option>
            </select>
            <button class="tdx-pm-btn-rescan" :disabled="pmScanning" @click="runPatternMatchScan">
              {{ pmScanning ? '扫描中...' : '重新匹配' }}
            </button>
          </div>
          <div class="tdx-pm-status">{{ pmStatusText }}</div>
        </div>

        <div class="tdx-pm-body">
          <div v-if="pmScanning" class="tdx-pm-loading">
            <div class="spinner"></div>
            <span>正在全市场多线程并行提取K线并计算形态相关系数...</span>
          </div>

          <table v-else class="tdx-pm-table">
            <thead>
              <tr>
                <th class="w-10 text-center">#</th>
                <th>代码</th>
                <th>名称</th>
                <th>形态相似度</th>
                <th class="text-center">走势拟合对比</th>
                <th class="text-right">现价</th>
                <th class="text-right">涨跌幅</th>
                <th class="text-center">匹配区间</th>
                <th class="text-center">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="pmMatches.length === 0">
                <td colspan="9" class="tdx-empty-cell">未找到相似度达标的标的</td>
              </tr>
              <tr v-for="(m, idx) in pmMatches" :key="m.code" class="tdx-pm-row">
                <td class="text-center">{{ idx + 1 }}</td>
                <td>
                  <button class="tdx-code-btn" @click="selectMatchedStock(m.code)">{{ m.code }}</button>
                </td>
                <td class="tdx-name-cell">
                  <button class="tdx-name-btn" @click="selectMatchedStock(m.code)">{{ m.name || '--' }}</button>
                </td>
                <td>
                  <div class="tdx-sim-cell">
                    <span class="tdx-sim-val" :class="{ 'gold': Number(m.similarity) >= 90 }">{{ Number(m.similarity).toFixed(1) }}%</span>
                    <div class="tdx-sim-bar-bg">
                      <div class="tdx-sim-bar-fill" :style="{ width: Math.min(100, Math.max(0, Number(m.similarity))) + '%' }"></div>
                    </div>
                  </div>
                </td>
                <td class="text-center" v-html="renderPatternSparklineSvg(pmTargetPoints, m.cand_points)"></td>
                <td class="text-right font-bold">¥{{ Number(m.latest_price || 0).toFixed(2) }}</td>
                <td class="text-right font-bold" :class="Number(m.pct_change) >= 0 ? 'color-up' : 'color-down'">
                  {{ Number(m.pct_change) >= 0 ? '+' : '' }}{{ Number(m.pct_change || 0).toFixed(2) }}%
                </td>
                <td class="text-center tdx-date-cell">{{ m.start_date }} ~ {{ m.end_date }}</td>
                <td class="text-center">
                  <button class="tdx-btn-switch" @click="selectMatchedStock(m.code)">载入</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </Teleport>
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
  padding: 0 16px 12px 16px;
  margin-top: 0;
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
.merge-toggle-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
  user-select: none;
  font-size: 11px;
  font-weight: 500;
  color: #e2e8f0;
  padding: 2px 4px;
  border-radius: 4px;
  transition: background-color 0.15s ease;
}
.merge-toggle-label:hover {
  background-color: rgba(147, 51, 234, 0.15);
}
.merge-checkbox {
  cursor: pointer;
  accent-color: #9333ea;
  width: 13px;
  height: 13px;
}
.merge-label-text {
  font-size: 11px;
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
.period-color-legend {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 11px;
  font-weight: bold;
}
.p-color-item {
  display: inline-flex;
  align-items: center;
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
.low-dot { background: #3b82f6; }
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

/* 级联菜单紧凑样式 */
.cascading-controls-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.control-group {
  display: flex;
  align-items: center;
  gap: 5px;
  position: relative;
}
.cascading-select {
  height: 26px;
  background: #181b27;
  border: 1px solid #2a2e39;
  border-radius: 6px;
  color: #c792ea;
  font-size: 11px;
  padding: 0 8px;
  outline: none;
  cursor: pointer;
  transition: border-color 0.15s ease;
}
.cascading-select:hover {
  border-color: #a855f7;
}
.tune-btn {
  height: 24px;
  padding: 0 6px;
  border-radius: 4px;
  background: #1e2230;
  border: 1px solid #2a2e39;
  color: #787b86;
  font-size: 11px;
  cursor: pointer;
}
.tune-btn:hover {
  color: #c792ea;
  border-color: #a855f7;
}
.flex-btn {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.caret {
  font-size: 9px;
  color: #787b86;
}
.layers-dropdown-popover {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 6px;
  width: 215px;
  background: #181b27;
  border: 1px solid #2a2e39;
  border-radius: 10px;
  padding: 8px;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
  z-index: 100;
}
.popover-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 6px;
  margin-bottom: 4px;
  border-bottom: 1px solid #2a2e39;
  font-size: 11px;
}
.popover-title {
  font-weight: 600;
  color: #d1d4dc;
}
.popover-actions {
  display: flex;
  gap: 4px;
  color: #c792ea;
  font-size: 10px;
}
.popover-actions button {
  background: none;
  border: none;
  color: #c792ea;
  cursor: pointer;
  padding: 0;
}
.popover-actions button:hover {
  text-decoration: underline;
}
.popover-items-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.popover-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 5px 8px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
  color: #d1d4dc;
  transition: background 0.15s, opacity 0.15s;
}
.popover-item:hover {
  background: rgba(168, 85, 247, 0.12);
}
.popover-item.disabled {
  opacity: 0.45;
}
.popover-item.sep-top {
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  margin-top: 2px;
  padding-top: 6px;
}
.item-name {
  display: flex;
  align-items: center;
  gap: 6px;
}
.item-switch-box {
  display: flex;
  align-items: center;
  gap: 6px;
}
.item-tick {
  font-weight: bold;
  font-size: 12px;
  color: #a855f7;
  width: 12px;
  text-align: center;
}
.switch-pill {
  width: 28px;
  height: 15px;
  border-radius: 9999px;
  background: #363c4e;
  padding: 1.5px;
  display: flex;
  align-items: center;
  transition: background-color 0.2s ease;
}
.switch-knob {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
  transition: transform 0.2s ease;
}
.switch-pill.active.purple { background: #9333ea; }
.switch-pill.active.amber { background: #d97706; }
.switch-pill.active.blue { background: #2563eb; }
.switch-pill.active.rose { background: #e11d48; }
.switch-pill.active.yellow { background: #ca8a04; }
.switch-pill.active .switch-knob {
  transform: translateX(13px);
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
}
.purple-dot { background: #c084fc; }
.amber-dot { background: #facc15; }
.blue-dot { background: #3b82f6; }
.rose-dot { background: #f43f5e; }
.yellow-dot { background: #eab308; }

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
  height: 6px;
  border-radius: 9999px;
  background: #2a2e39;
  border: 1px solid rgba(255, 255, 255, 0.1);
  accent-color: #a855f7;
  cursor: pointer;
}

/* 主图表容器与分屏卡片 */
.charts-split-container {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
  flex-shrink: 0;
}
@media (min-width: 1200px) {
  .charts-split-container.is-dual {
    flex-direction: column;
  }
  .charts-split-container.is-quad {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }
}
.charts-split-container.is-dual .chart-window-card,
.charts-split-container.is-quad .chart-window-card {
  min-height: 280px;
}
.chart-window-card {
  position: relative;
  background: #181b27;
  border: 1px solid #2a2e39;
  border-radius: 8px;
  height: calc(100vh - 240px);
  min-height: 380px;
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
  cursor: pointer;
}
.chart-window-card.is-active-window {
  border-color: rgba(168, 85, 247, 0.9) !important;
  box-shadow: 0 0 16px rgba(168, 85, 247, 0.28), inset 0 0 8px rgba(168, 85, 247, 0.08);
}
.win-active-badge {
  background: #a855f7;
  color: #ffffff;
  font-size: 10px;
  font-weight: bold;
  padding: 1px 5px;
  border-radius: 3px;
  margin-left: 6px;
  letter-spacing: 0.02em;
}
.window-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 12px;
  background: #1e222d;
  border-bottom: 1px solid #2a2e39;
  font-size: 11px;
  flex-shrink: 0;
}
.win-tag-box {
  display: flex;
  align-items: center;
  gap: 8px;
}
.win-pill {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(30, 41, 59, 0.75);
  border: 1px solid #334155;
  font-weight: bold;
  font-size: 11px;
}
.win-idx {
  color: #94a3b8;
  font-weight: 700;
  margin-right: 2px;
}
.p-dot-item {
  font-weight: 700;
  display: inline-flex;
  align-items: center;
}
.p-dot-sep {
  color: #64748b;
  font-size: 10px;
}
.left-pill, .w2-pill, .right-pill, .w4-pill {
  background: rgba(30, 41, 59, 0.75);
  border: 1px solid #334155;
  color: #e2e8f0;
}
.win-stock-header-info {
  display: flex;
  align-items: center;
  font-family: 'JetBrains Mono', Consolas, monospace;
}
.win-stock-title {
  color: #cbd5e1;
  font-size: 11px;
  font-weight: 600;
}
.win-stock-price {
  margin-left: 8px;
  font-size: 12px;
  font-weight: 700;
}
.win-stock-chg {
  margin-left: 6px;
  font-size: 11px;
  font-weight: 700;
}
.color-up {
  color: #ef4444;
}
.color-down {
  color: #10b981;
}
.color-flat {
  color: #94a3b8;
}
.win-preset-select {
  background: #131722;
  border: 1px solid #363c4e;
  color: #e2e8f0;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 11px;
  cursor: pointer;
}
.chart-wrapper {
  position: relative;
  background: #181b27;
  border: 1px solid #2a2e39;
  border-radius: 8px;
  height: calc(100vh - 240px);
  min-height: 380px;
  flex-shrink: 0;
}
.main-echart {
  width: 100%;
  flex: 1;
  min-height: 0;
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

/* ==================== 通达信风格 区间统计与形态匹配样式 ==================== */
.tdx-modal-window {
  position: fixed;
  z-index: 9999;
  width: 360px;
  background: #ece9d8;
  border: 1px solid #a01010;
  border-radius: 6px;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.65);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
  color: #111827;
  overflow: hidden;
  user-select: none;
}
:root.dark .tdx-modal-window, .chanlun-container .tdx-modal-window {
  background: #1a1f2c;
  border-color: #334155;
  color: #f1f5f9;
}
.tdx-modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 12px;
  background: #800000;
  color: #ffffff;
  cursor: move;
  font-size: 12px;
  font-weight: bold;
}
.chanlun-container .tdx-modal-header {
  background: #450a0a;
}
.tdx-modal-title {
  font-family: inherit;
  letter-spacing: 0.5px;
}
.tdx-modal-close {
  background: transparent;
  border: none;
  color: #ffffff;
  font-size: 16px;
  font-weight: bold;
  cursor: pointer;
  line-height: 1;
}
.tdx-modal-close:hover {
  color: #fca5a5;
}
.tdx-modal-body {
  padding: 10px;
  font-size: 11px;
}
.tdx-row-between {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.tdx-field-inline {
  display: flex;
  align-items: center;
  gap: 4px;
}
.tdx-label {
  width: 52px;
  color: #94a3b8;
  font-size: 11px;
}
.tdx-input-ro {
  width: 96px;
  padding: 2px 4px;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 3px;
  color: #e2e8f0;
  text-align: right;
  font-family: monospace;
  font-size: 11px;
}
.tdx-w-date {
  width: 90px;
  text-align: center;
}
.tdx-count-info {
  font-size: 11px;
}
.tdx-split-grid {
  display: grid;
  grid-template-columns: 8fr 4fr;
  gap: 8px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid #334155;
}
.tdx-metrics-col {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.tdx-metric-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.tdx-actions-col {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding-left: 6px;
  border-left: 1px solid #334155;
}
.tdx-bars-summary {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tdx-stat-item {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
}
.tdx-hr {
  height: 1px;
  background: #334155;
  margin: 4px 0;
}
.tdx-btns-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 8px;
}
.tdx-btn-pattern {
  background: #f59e0b;
  color: #0f172a;
  border: none;
  font-weight: bold;
  font-size: 11px;
  padding: 5px 0;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}
.tdx-btn-pattern:hover {
  background: #d97706;
}
.tdx-btn-close {
  background: #334155;
  color: #f1f5f9;
  border: 1px solid #475569;
  font-size: 11px;
  padding: 4px 0;
  border-radius: 4px;
  cursor: pointer;
}
.tdx-btn-close:hover {
  background: #475569;
}
.tdx-checkbox-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10.5px;
  color: #94a3b8;
  cursor: pointer;
}

/* 形态匹配选股弹窗样式 */
.tdx-pm-overlay {
  position: fixed;
  inset: 0;
  z-index: 10000;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}
.tdx-pm-modal {
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 14px;
  width: 100%;
  max-width: 920px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.8);
  overflow: hidden;
}
.tdx-pm-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: #1e293b;
  border-bottom: 1px solid #334155;
}
.tdx-pm-title-box {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tdx-pm-icon {
  font-size: 18px;
}
.tdx-pm-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: bold;
  font-size: 14px;
  color: #ffffff;
}
.tdx-pm-badge {
  font-size: 11px;
  font-weight: normal;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(2, 132, 199, 0.2);
  color: #38bdf8;
  border: 1px solid rgba(56, 189, 248, 0.4);
}
.tdx-pm-subtitle {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 2px;
}
.tdx-pm-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  background: rgba(15, 23, 42, 0.6);
  border-bottom: 1px solid #1e293b;
  font-size: 12px;
}
.tdx-pm-filter {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #94a3b8;
}
.tdx-pm-select {
  background: #1e293b;
  border: 1px solid #475569;
  border-radius: 4px;
  color: #f1f5f9;
  padding: 4px 8px;
  font-size: 11px;
}
.tdx-pm-btn-rescan {
  background: #f59e0b;
  color: #0f172a;
  border: none;
  border-radius: 4px;
  font-weight: bold;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 11px;
}
.tdx-pm-btn-rescan:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.tdx-pm-status {
  font-family: monospace;
  font-size: 11px;
  color: #64748b;
}
.tdx-pm-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
  min-height: 260px;
}
.tdx-pm-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
  gap: 12px;
  color: #38bdf8;
  font-size: 12px;
}
.tdx-pm-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.tdx-pm-table th {
  padding: 8px 6px;
  color: #94a3b8;
  border-bottom: 1px solid #334155;
  font-size: 11px;
}
.tdx-pm-row {
  border-bottom: 1px solid #1e293b;
  transition: background 0.15s;
}
.tdx-pm-row:hover {
  background: rgba(30, 41, 59, 0.6);
}
.tdx-pm-row td {
  padding: 8px 6px;
}
.tdx-code-btn, .tdx-name-btn {
  background: transparent;
  border: none;
  font-family: inherit;
  font-weight: bold;
  color: #38bdf8;
  cursor: pointer;
  text-align: left;
  padding: 0;
}
.tdx-code-btn:hover, .tdx-name-btn:hover {
  text-decoration: underline;
}
.tdx-name-btn {
  color: #f1f5f9;
}
.tdx-sim-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tdx-sim-val {
  font-family: monospace;
  font-weight: bold;
  color: #e2e8f0;
  min-width: 44px;
}
.tdx-sim-val.gold {
  color: #fbbf24;
}
.tdx-sim-bar-bg {
  width: 60px;
  height: 6px;
  background: #334155;
  border-radius: 3px;
  overflow: hidden;
}
.tdx-sim-bar-fill {
  height: 100%;
  background: #fbbf24;
}
.tdx-date-cell {
  color: #64748b;
  font-size: 11px;
}
.tdx-btn-switch {
  background: rgba(56, 189, 248, 0.15);
  border: 1px solid rgba(56, 189, 248, 0.4);
  color: #38bdf8;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
}
.tdx-btn-switch:hover {
  background: rgba(56, 189, 248, 0.3);
}
.tdx-empty-cell {
  padding: 30px;
  text-align: center;
  color: #64748b;
}
</style>
