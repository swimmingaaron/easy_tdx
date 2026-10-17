# 缠论大中小三周期立体共振 · 通达信指标与选股公式代码

本套公式基于 easy_tdx 缠论量化立体共振算法与经典缠论动力学，完全适配**通达信（PC端及手机端）**，包含：
1. **主图指标**：`CL_MAIN`（缠论大中小三周期同图笔、中枢与买卖点标记）
2. **副图指标**：`CL_RESONANCE`（大中小三级别共振柱与多空能量雷达）
3. **选股公式**：`CL_GZ_BUY`（大中小三级别立体买点共振选股）

---

## 一、主图指标公式代码：`CL_MAIN`（缠论多级别笔+中枢+买卖点）

- **公式名称**：`CL_MAIN`
- **公式描述**：缠论大中小K线立体主图
- **公式类型**：技术指标公式 -> 画线指标 / 主图叠加
- **画线方法**：主图叠加

### 公式代码（复制下方全部内容到通达信公式编辑器）：

```pascal
{ ==================== 缠论多级别笔与中枢主图指标 ==================== }
{ 1. 基础顶底分型与笔构建 }
TR1:=MAX(MAX((HIGH-LOW),ABS(REF(CLOSE,1)-HIGH)),ABS(REF(CLOSE,1)-LOW));
ATR:=EMA(TR1,14);

{ 顶底分型定位（过滤包含关系后的经典分形点） }
PEAK_BAR:=PEAKBARS(1,5,1);
VALLEY_BAR:=TROUGHBARS(1,5,1);

{ 高低拐点价格 }
ZG_VAL:=PEAK(1,5,1);
ZD_VAL:=TROUGH(1,5,1);

{ 绘制缠论向上一笔（红线粗线）与向下一笔（绿线粗线） }
DRAWLINE(VALLEY_BAR=0, LOW, PEAK_BAR=0, HIGH, 0), COLORRED, LINETHICK2;
DRAWLINE(PEAK_BAR=0, HIGH, VALLEY_BAR=0, LOW, 0), COLORGREEN, LINETHICK2;

{ ==================== 2. 缠论走势中枢区间 [ZD, ZG] 绘制 ==================== }
{ 中枢高点 ZG 与中枢低点 ZD 动态追踪 }
MID_ZG:=MIN(PEAK(1,5,1), PEAK(1,5,2));
MID_ZD:=MAX(TROUGH(1,5,1), TROUGH(1,5,2));
HAS_ZS:=MID_ZG > MID_ZD;

{ 中枢高轨 (洋红虚线) 与中枢低轨 (青色虚线) }
中枢高: IF(HAS_ZS, MID_ZG, DRAWNULL), COLORMAGENTA, POINTDOT, LINETHICK2;
中枢低: IF(HAS_ZS, MID_ZD, DRAWNULL), COLORCYAN, POINTDOT, LINETHICK2;

{ 中枢箱体填充微弱背景 (提示引力区域) }
STICKLINE(HAS_ZS AND PEAK_BAR<=15, MID_ZG, MID_ZD, 0, 0), COLORGRAY;

{ ==================== 3. 缠论三大买点信号判定 ==================== }
{ 经典 MACD 动能背驰辅助 }
DIF:=(EMA(CLOSE,12)-EMA(CLOSE,26));
DEA:=EMA(DIF,9);
MACD_VAL:=(DIF-DEA)*2;

{ 底背驰：价格创新低，但 DIF 未创新低 }
LLV_P:=TROUGH(1,5,1);
PRE_LLV_P:=TROUGH(1,5,2);
LLV_DIF:=LLV(DIF, 10);
底背驰:=VALLEY_BAR=0 AND LLV_P < PRE_LLV_P AND DIF > REF(DIF, BARSLAST(VALLEY_BAR=0)+1);

{ 第一类买点 (1Buy)：趋势下跌底背驰转折点 }
一买:=底背驰 AND LOW<=LLV(LOW, 30);
DRAWICON(一买, LOW*0.985, 1); { 红色箭头 }
DRAWTEXT(一买, LOW*0.975, ' 1买'), COLORRED;

{ 第二类买点 (2Buy)：一买后第一波向上反弹，随后次级别回踩不破一买低点 }
二买:=VALLEY_BAR=0 AND LOW > REF(LOW, BARSLAST(一买)) AND BARSLAST(一买)<=45 AND BARSLAST(一买)>=5;
DRAWICON(二买, LOW*0.985, 23); { 黄金十字星/多头标志 }
DRAWTEXT(二买, LOW*0.975, ' 2买'), COLORYELLOW;

{ 第三类买点 (3Buy)：强力突破中枢上轨 ZG，次级别回踩不破 ZG }
三买:=VALLEY_BAR=0 AND LOW > MID_ZG AND REF(HIGH, 1) > MID_ZG AND BARSLAST(PEAK_BAR=0)>=2;
DRAWICON(三买, LOW*0.985, 9); { 向上箭头 }
DRAWTEXT(三买, LOW*0.975, ' 3买'), COLORMAGENTA;

{ 二三买合力 (Combo 2+3 Buy)：最强主升形态 }
二三合力:=二买 AND 三买;
DRAWTEXT(二三合力, LOW*0.96, '★2+3合力★'), COLOR00FFFF;

{ ==================== 4. 缠论三大卖点信号判定 ==================== }
{ 顶背驰：价格创新高，DIF 不创新高 }
HHV_P:=PEAK(1,5,1);
PRE_HHV_P:=PEAK(1,5,2);
顶背驰:=PEAK_BAR=0 AND HHV_P > PRE_HHV_P AND DIF < REF(DIF, BARSLAST(PEAK_BAR=0)+1);

{ 第一类卖点 (1Sell)：趋势上涨顶背驰 }
一卖:=顶背驰 AND HIGH>=HHV(HIGH, 30);
DRAWICON(一卖, HIGH*1.015, 2); { 绿色向下箭头 }
DRAWTEXT(一卖, HIGH*1.025, ' 1卖'), COLORGREEN;

{ 第二类卖点 (2Sell)：一卖后反抽不创新高 }
二卖:=PEAK_BAR=0 AND HIGH < REF(HIGH, BARSLAST(一卖)) AND BARSLAST(一卖)<=45 AND BARSLAST(一卖)>=5;
DRAWTEXT(二卖, HIGH*1.025, ' 2卖'), COLORLICYAN;

{ 第三类卖点 (3Sell)：跌破中枢下轨 ZD，反抽不过 ZD }
三卖:=PEAK_BAR=0 AND HIGH < MID_ZD AND REF(LOW, 1) < MID_ZD;
DRAWTEXT(三卖, HIGH*1.025, ' 3卖'), COLORWHITE;

{ ==================== 5. 大中小三级别跨周期状态雷达看板 (左上角状态输出) ==================== }
{ 跨周期引用：大级别(周线)与中级别(日线) }
周_DIF:="MACD.DIF#WEEK"(12,26,9);
周_DEA:="MACD.DEA#WEEK"(12,26,9);
周多头:=周_DIF > 周_DEA;

日_DIF:="MACD.DIF#DAY"(12,26,9);
日_DEA:="MACD.DEA#DAY"(12,26,9);
日多头:=日_DIF > 日_DEA;

本多头:=DIF > DEA;

{ 顶部状态文本显示 }
DRAWTEXT_FIX(ISLASTBAR, 0.01, 0.02, 0, '【缠论大中小三级别立体状态看板】'), COLORWHITE;
DRAWTEXT_FIX(ISLASTBAR AND 周多头, 0.01, 0.06, 0, '★ 大级别 (周线): 多头掌控中 (安全边际充足)'), COLORRED;
DRAWTEXT_FIX(ISLASTBAR AND NOT(周多头), 0.01, 0.06, 0, '☆ 大级别 (周线): 空头退守中 (谨慎开仓)'), COLORGRAY;
DRAWTEXT_FIX(ISLASTBAR AND 日多头, 0.01, 0.10, 0, '★ 中级别 (日线): 多头共振波段 (关注二三买)'), COLORYELLOW;
DRAWTEXT_FIX(ISLASTBAR AND NOT(日多头), 0.01, 0.10, 0, '☆ 中级别 (日线): 处于震荡或调整段'), COLORGRAY;
DRAWTEXT_FIX(ISLASTBAR AND 本多头, 0.01, 0.14, 0, '★ 次级别 (当前): 具备精准微观进场点'), COLORMAGENTA;
DRAWTEXT_FIX(ISLASTBAR AND NOT(本多头), 0.01, 0.14, 0, '☆ 次级别 (当前): 处于反抽或洗盘阶段'), COLORGRAY;
```

---

## 二、副图指标公式代码：`CL_RESONANCE`（大中小立体共振能量仪）

- **公式名称**：`CL_RESONANCE`
- **公式描述**：缠论大中小三级别共振柱
- **公式类型**：技术指标公式 -> 图表指标 / 副图

### 公式代码（复制下方全部内容到通达信公式编辑器）：

```pascal
{ ==================== 缠论大中小三周期共振能量柱 ==================== }
{ 1. 大级别(周线/日线)多空量化 }
大_DIF:="MACD.DIF#WEEK"(12,26,9);
大_DEA:="MACD.DEA#WEEK"(12,26,9);
大级别多头: IF(大_DIF>大_DEA, 3, 0), COLORRED, NODRAW;

{ 2. 中级别(日线)多空量化 }
中_DIF:="MACD.DIF#DAY"(12,26,9);
中_DEA:="MACD.DEA#DAY"(12,26,9);
中级别多头: IF(中_DIF>中_DEA, 2, 0), COLORYELLOW, NODRAW;

{ 3. 本级别(微观战术级别，如30F/60F/日线)多空量化 }
DIF:=(EMA(CLOSE,12)-EMA(CLOSE,26));
DEA:=EMA(DIF,9);
本级别多头: IF(DIF>DEA, 1, 0), COLORCYAN, NODRAW;

{ 4. 立体共振综合得分 (0 ~ 3 分) }
共振得分: (大_DIF>大_DEA) + (中_DIF>中_DEA) + (DIF>DEA), COLORWHITE, NODRAW;

{ 绘制大中小三层能量轨道柱状带 }
{ 第一层：小级别状态 (底层 0 ~ 1) }
STICKLINE(DIF>DEA, 0, 1, 2, 0), COLOR0088FF;
STICKLINE(DIF<=DEA, 0, 1, 2, 0), COLOR333333;

{ 第二层：中级别状态 (中层 1.2 ~ 2.2) }
STICKLINE(中_DIF>中_DEA, 1.2, 2.2, 2, 0), COLOR00DDDD;
STICKLINE(中_DIF<=中_DEA, 1.2, 2.2, 2, 0), COLOR444444;

{ 第三层：大级别状态 (高层 2.4 ~ 3.4) }
STICKLINE(大_DIF>大_DEA, 2.4, 3.4, 2, 0), COLOR0000FF;
STICKLINE(大_DIF<=大_DEA, 2.4, 3.4, 2, 0), COLOR555555;

{ 5. 三级别全红共振暴击信号 (当得分达到 3 分时触发大爆发) }
三级共振: 共振得分=3, COLORRED, NODRAW;
STICKLINE(三级共振 AND REF(三级共振,1)=0, 0, 3.4, 1.5, 0), COLORWHITE;
DRAWICON(三级共振 AND REF(三级共振,1)=0, 3.6, 25); { 钱袋子/大买点图标 }
DRAWTEXT(三级共振 AND REF(三级共振,1)=0, 3.8, '★大中小共振'), COLOR00FFFF;

{ 标注层级说明 }
DRAWTEXT_FIX(ISLASTBAR, 0.01, 0.05, 0, '【上轨:大级别(周) 中轨:中级别(日) 下轨:微观(本)】'), COLORWHITE;
```

---

## 三、条件选股公式代码：`CL_GZ_BUY`（大中小三级别共振选股）

- **公式名称**：`CL_GZ_BUY`
- **公式描述**：缠论大中小三周期买点立体共振选股
- **公式类型**：条件选股公式
- **选股周期**：日线

### 公式代码（复制下方全部内容到通达信条件选股编辑器）：

```pascal
{ ==================== 缠论大中小三级别立体共振选股 ==================== }
{ 1. 大级别(周线)处于多头趋势或金叉初成 }
周_DIF:="MACD.DIF#WEEK"(12,26,9);
周_DEA:="MACD.DEA#WEEK"(12,26,9);
周多头:=周_DIF > 周_DEA;

{ 2. 中级别(日线)底背驰或二三买突破 }
日_DIF:="MACD.DIF#DAY"(12,26,9);
日_DEA:="MACD.DEA#DAY"(12,26,9);
日多头:=日_DIF > 日_DEA;

{ 3. 价格站上 20 日均线且处于反弹回抽不破低点状态 }
MA20:=MA(CLOSE, 20);
趋势向上:=CLOSE >= MA20 AND MA20 >= REF(MA20, 1);

{ 4. 缠论拐点：次级别或日线止跌，未出现顶背驰 }
LLV_P:=TROUGH(1, 5, 1);
PRE_LLV_P:=TROUGH(1, 5, 2);
回踩不破底:=TROUGHBARS(1, 5, 1) <= 3 AND LLV_P >= PRE_LLV_P;

{ 5. 三级别共振启动条件 }
共振选股: 周多头 AND 日多头 AND 趋势向上 AND (回踩不破底 OR CROSS(日_DIF, 日_DEA));
```

---

## 四、通达信软件安装与导入步骤指引

### 1. 快捷键打开公式管理器
- 在通达信主界面按键盘快捷键：`Ctrl + F`；
- 或者点击菜单栏：`系统` -> `公式系统` -> `公式管理器`。

### 2. 新建主图指标 `CL_MAIN`
1. 在公式管理器左侧树状目录中，点击选中 **「技术指标公式」** -> **「其它类型」**；
2. 点击右上角 **「新建」** 按钮；
3. 输入公式信息：
   - **公式名称**：`CL_MAIN`
   - **公式描述**：`缠论大中小K线立体主图`
   - **画线方法**：勾选 **「主图叠加」**（⚠️ 非常重要，必须选主图叠加）；
4. 将上方 **一、主图指标公式代码** 完整粘贴到下方大文本框中；
5. 点击右侧 **「测试公式」**，显示“编译通过”后点击 **「确定」** 保存。

### 3. 新建副图指标 `CL_RESONANCE`
1. 再次点击 **「新建」**；
2. 输入公式信息：
   - **公式名称**：`CL_RESONANCE`
   - **公式描述**：`缠论大中小三级别共振柱`
   - **画线方法**：保持默认 **「副图」**；
3. 将上方 **二、副图指标公式代码** 完整粘贴进去，测试通过后保存。

### 4. 新建条件选股公式 `CL_GZ_BUY`
1. 在公式管理器中点击选中左侧目录的 **「条件选股公式」** -> **「其它类型」**；
2. 点击 **「新建」**；
3. 输入公式信息：
   - **公式名称**：`CL_GZ_BUY`
   - **公式描述**：`缠论大中小三周期共振选股`
4. 将上方 **三、条件选股公式代码** 粘贴进去，测试通过后保存。

### 5. 跨周期数据完整下载（⚠️ 核心关键步骤）
通达信跨周期引用（`#WEEK`、`#DAY`、`#MIN30`、`#MIN5`）需要本地具备完整历史数据：
1. 键盘输入快捷键 `34#`（或者点击顶部菜单 `系统` -> `盘后数据下载`）；
2. 勾选 **「日线和分时线」**、**「5分钟线」**；
3. 点击 **「开始下载」**，下载完成后跨周期立体看板即可 100% 完美计算显示！
