import { createRouter, createWebHistory } from 'vue-router'

import BacktestView from './views/BacktestView.vue'
import ChanlunView from './views/ChanlunView.vue'
import CompareView from './views/CompareView.vue'
import OptimizeView from './views/OptimizeView.vue'
import PortfolioView from './views/PortfolioView.vue'
import ServerSettingsView from './views/ServerSettingsView.vue'
import SignalRadarView from './views/SignalRadarView.vue'
import StrategiesView from './views/StrategiesView.vue'

// 单标的回测（/）+ 缠论多周期立体共振（/chanlun 或 /#chanlun）+ 组合回测（/portfolio）+ 参数寻优（/optimize）+ 结果对比（/compare）
// + 策略库（/strategies）+ 信号雷达（/signals）+ 服务器设置（/settings）。
const routes = [
  { path: '/', name: 'backtest', component: BacktestView },
  { path: '/chanlun', name: 'chanlun', component: ChanlunView },
  { path: '/portfolio', name: 'portfolio', component: PortfolioView },
  { path: '/optimize', name: 'optimize', component: OptimizeView },
  { path: '/compare', name: 'compare', component: CompareView },
  { path: '/strategies', name: 'strategies', component: StrategiesView },
  { path: '/signals', name: 'signals', component: SignalRadarView },
  { path: '/settings', name: 'settings', component: ServerSettingsView },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 支持用户通过 http://localhost:8000/#chanlun 或 #/chanlun 直接打开缠论页面
router.beforeEach((to, _from, next) => {
  const hash = window.location.hash.toLowerCase()
  if (hash === '#chanlun' || hash === '#/chanlun') {
    if (to.path !== '/chanlun') {
      return next('/chanlun')
    }
  }
  next()
})

// 初次加载时检测并自动纠偏 hash 路由
if (typeof window !== 'undefined') {
  const initHash = window.location.hash.toLowerCase()
  if (initHash === '#chanlun' || initHash === '#/chanlun') {
    router.replace('/chanlun').catch(() => {})
  }
}
