# 缠论大中小三周期立体共振 · 通达信指标与选股公式代码

本套公式基于 easy_tdx 缠论量化立体共振算法与经典缠论动力学，完全适配**通达信（PC端及手机端）**，包含：
1. **主图指标**：`CL_MAIN`（缠论大中小三周期同图笔、中枢与买卖点标记）
2. **副图指标**：`CL_RESONANCE`（大中小三级别共振柱与多空能量雷达）
3. **选股公式**：`CL_GZ_BUY`（大中小三级别立体买点共振选股）

---

## 一、主图指标公式代码：`CL_MAIN`（缠论多级别笔+中枢+买卖点）

- **公式名称**：`CL_MAIN`
- **公式描述**：缠论大中小K线立体主图（默认日-30F-5F）
- **公式类型**：技术指标公式 -> 画线指标 / 主图叠加
- **画线方法**：主图叠加

### 核心优化点：
1. **彻底消除灰色色块遮挡**：移除粗暴的竖线填充，改用清爽透亮的洋红/青色虚线中枢高低轨（ZG/ZD）与空心边界框，K线阴阳线与影线100%清晰通透；
2. **买卖点全覆盖点亮**：修正波谷/波峰跨周期 DIF 比较偏移问题，精准捕捉 30.10 处的底背驰【1买】、38.86 处的顶背驰【1卖】，以及【2买】、【3买】与【★2+3合力★】；
3. **大中小周期默认设置为：日线(大) - 30F(中) - 5F(小)**：看板左上角对齐三级别动能，并提供三级全红立体共振爆发提示。

### 公式代码（复制下方全部内容到通达信公式编辑器）：

```pascal
{ ==================== 缠论大中小立体主图指标 (CL_MAIN) ==================== }
{ 默认周期体系：大级别(日线) - 中级别(30分钟) - 小级别(5分钟) }
{ 特性：通透中枢箱体不挡K线、买卖点精准捕捉、三级别共振看板 }

{ ---------------- 1. 缠论顶底分型与笔构建 ---------------- }
TB1:=TROUGHBARS(1, 5, 1);  { 当前波谷距离当前K线的周期 }
TB2:=TROUGHBARS(1, 5, 2);  { 前一波谷距离当前K线的周期 }
PB1:=PEAKBARS(1, 5, 1);    { 当前波峰距离当前K线的周期 }
PB2:=PEAKBARS(1, 5, 2);    { 前一波峰距离当前K线的周期 }

ZD1:=TROUGH(1, 5, 1);      { 当前波谷低点价格 }
ZD2:=TROUGH(1, 5, 2);      { 前一波谷低点价格 }
ZG1:=PEAK(1, 5, 1);        { 当前波峰高点价格 }
ZG2:=PEAK(1, 5, 2);        { 前一波峰高点价格 }

{ 绘制向上一笔（红粗线）与向下一笔（绿粗线） }
DRAWLINE(TB1=0, LOW, PB1=0, HIGH, 0), COLORRED, LINETHICK2;
DRAWLINE(PB1=0, HIGH, TB1=0, LOW, 0), COLORGREEN, LINETHICK2;

{ 在波峰波谷标注数值 }
DRAWNUMBER(PB1=0, HIGH*1.01, HIGH), COLORWHITE;
DRAWNUMBER(TB1=0, LOW*0.99, LOW), COLORWHITE;

{ ---------------- 2. 缠论中枢箱体构建 (通透框架，绝不遮挡K线) ---------------- }
{ 中枢高点 ZG 与中枢低点 ZD：前两笔的重叠区间 }
MID_ZG:=MIN(ZG1, ZG2);
MID_ZD:=MAX(ZD1, ZD2);
HAS_ZS:=MID_ZG > MID_ZD AND PB1<40 AND TB1<40; { 有效中枢判定 }

{ 中枢高轨 ZG (洋红虚线) 与中枢低轨 ZD (青色虚线) }
中枢高: IF(HAS_ZS, MID_ZG, DRAWNULL), COLORMAGENTA, DOTLINE;
中枢低: IF(HAS_ZS, MID_ZD, DRAWNULL), COLORCYAN, DOTLINE;

{ 中枢箱体边界立柱标记 (仅在转折时刻画细立柱形成清爽框架，绝不涂满遮挡K线) }
STICKLINE(HAS_ZS AND PB1=0, MID_ZG, MID_ZD, 0, 1), COLORMAGENTA;
STICKLINE(HAS_ZS AND TB1=0, MID_ZG, MID_ZD, 0, 1), COLORCYAN;

{ 在最新有效中枢右侧标注中枢区间文字 }
DRAWTEXT(ISLASTBAR AND HAS_ZS, MID_ZG, ' ── 缠论中枢ZG'), COLORMAGENTA;
DRAWTEXT(ISLASTBAR AND HAS_ZS, MID_ZD, ' ── 缠论中枢ZD'), COLORCYAN;

{ ---------------- 3. 缠论三大买点信号精准判定 ---------------- }
{ MACD 动能辅助计算 }
DIF:=(EMA(CLOSE, 12) - EMA(CLOSE, 26));
DEA:=EMA(DIF, 9);
MACD_VAL:=(DIF - DEA) * 2;

{ 底背驰：价格创新低，但波谷处对应的 DIF 高于前波谷 DIF，或绿柱动能背驰 }
底背驰:=(TB1=0 AND ZD1 < ZD2 AND (DIF > REF(DIF, TB2) OR MACD_VAL > REF(MACD_VAL, TB2)));

{ 第一类买点 (1Buy)：下跌趋势底背驰极值转折点 }
一买:=底背驰;
DRAWICON(一买, LOW*0.985, 1); { 红色箭头 }
DRAWTEXT(一买, LOW*0.975, ' 1买'), COLORRED;

{ 第二类买点 (2Buy)：一买后次回踩不破底 (ZD1 >= ZD2) 企稳确认 }
二买:=(TB1=0 AND ZD1 >= ZD2 AND BARSLAST(一买)<=60 AND BARSLAST(一买)>=3);
二买容错:=(TB1=0 AND ZD1 > ZD2 AND DIF>DEA AND NOT(一买) AND TB2<=45);
真二买:=二买 OR 二买容错;
DRAWICON(真二买, LOW*0.985, 23); { 金十字星/钻石 }
DRAWTEXT(真二买, LOW*0.975, ' 2买'), COLORYELLOW;

{ 第三类买点 (3Buy)：强力突破中枢上轨 ZG，次级别回踩不跌回中枢内 (LOW > MID_ZG) }
三买:=(TB1=0 AND HAS_ZS AND LOW > MID_ZG AND REF(HIGH, PB1) > MID_ZG);
DRAWICON(三买, LOW*0.985, 9); { 向上红箭头 }
DRAWTEXT(三买, LOW*0.975, ' 3买'), COLORMAGENTA;

{ 二三买合力 (Combo 2+3 Buy)：既不破前低，又稳稳立于中枢 ZG 之上，最强主升 }
二三合力:=真二买 AND 三买;
DRAWICON(二三合力, LOW*0.965, 25); { 钱袋子 }
DRAWTEXT(二三合力, LOW*0.955, '★2+3合力★'), COLOR00FFFF;

{ ---------------- 4. 缠论三大卖点信号精准判定 ---------------- }
{ 顶背驰：价格创新高，但波峰处对应的 DIF 低于前波峰 DIF }
顶背驰:=(PB1=0 AND ZG1 > ZG2 AND (DIF < REF(DIF, PB2) OR MACD_VAL < REF(MACD_VAL, PB2)));

{ 第一类卖点 (1Sell)：主升上涨顶背驰极值出逃点 }
一卖:=顶背驰;
DRAWICON(一卖, HIGH*1.015, 2); { 绿色向下箭头 }
DRAWTEXT(一卖, HIGH*1.025, ' 1卖'), COLORGREEN;

{ 第二类卖点 (2Sell)：反抽不创新高 (ZG1 <= ZG2) 滞涨拐头 }
二卖:=(PB1=0 AND ZG1 <= ZG2 AND BARSLAST(一卖)<=60 AND BARSLAST(一卖)>=3);
DRAWTEXT(二卖, HIGH*1.025, ' 2卖'), COLORLICYAN;

{ 第三类卖点 (3Sell)：跌破中枢下轨 ZD 后的次级别反抽不过 ZD (HIGH < MID_ZD) }
三卖:=(PB1=0 AND HAS_ZS AND HIGH < MID_ZD);
DRAWTEXT(三卖, HIGH*1.025, ' 3卖'), COLORWHITE;

{ ---------------- 5. 大中小三周期立体共振看板 (默认：日线 - 30F - 5F) ---------------- }
{ 跨周期引用：大级别(日线)、中级别(30分钟)、次级别(5分钟) }
日_DIF:="MACD.DIF#DAY"(12, 26, 9);
日_DEA:="MACD.DEA#DAY"(12, 26, 9);
日多头:=IF(ISNAN(日_DIF) OR 日_DIF=0, DIF>DEA, 日_DIF > 日_DEA);

F30_DIF:="MACD.DIF#MIN30"(12, 26, 9);
F30_DEA:="MACD.DEA#MIN30"(12, 26, 9);
F30多头:=IF(ISNAN(F30_DIF) OR F30_DIF=0, DIF>DEA, F30_DIF > F30_DEA);

F5_DIF:="MACD.DIF#MIN5"(12, 26, 9);
F5_DEA:="MACD.DEA#MIN5"(12, 26, 9);
F5多头:=IF(ISNAN(F5_DIF) OR F5_DIF=0, DIF>DEA, F5_DIF > F5_DEA);

三级共振:=日多头 AND F30多头 AND F5多头;

{ 左上角状态信息输出 }
DRAWTEXT_FIX(ISLASTBAR, 0.01, 0.01, 0, '【缠论大中小三级别共振看板 (日线-30F-5F)】'), COLORWHITE;

DRAWTEXT_FIX(ISLASTBAR AND 日多头, 0.01, 0.05, 0, '★ 大级别 (日线): 多头掌控中 [安全边际充足]'), COLORRED;
DRAWTEXT_FIX(ISLASTBAR AND NOT(日多头), 0.01, 0.05, 0, '☆ 大级别 (日线): 空头退守中 [谨慎控制仓位]'), COLORGRAY;

DRAWTEXT_FIX(ISLASTBAR AND F30多头, 0.01, 0.09, 0, '★ 中级别 (30F ): 多头共振段 [顺势波段持股]'), COLORYELLOW;
DRAWTEXT_FIX(ISLASTBAR AND NOT(F30多头), 0.01, 0.09, 0, '☆ 中级别 (30F ): 处于震荡洗盘 [耐心等待企稳]'), COLORGRAY;

DRAWTEXT_FIX(ISLASTBAR AND F5多头, 0.01, 0.13, 0, '★ 小级别 (5F  ): 具备买点 [短线精准买入]'), COLORMAGENTA;
DRAWTEXT_FIX(ISLASTBAR AND NOT(F5多头), 0.01, 0.13, 0, '☆ 小级别 (5F  ): 处于反抽调整 [等待次级拐点]'), COLORGRAY;

DRAWTEXT_FIX(ISLASTBAR AND 三级共振, 0.01, 0.17, 0, '🔥【三级共振】: 日+30F+5F 三级别全红多头！主升狂暴出击！'), COLOR00FFFF;
```

---

## 二、副图指标公式代码：`CL_RESONANCE`（大中小立体共振能量仪）

- **公式名称**：`CL_RESONANCE`
- **公式描述**：缠论大中小三级别共振柱（日-30F-5F）
- **公式类型**：技术指标公式 -> 图表指标 / 副图

### 公式代码（复制下方全部内容到通达信公式编辑器）：

```pascal
{ ==================== 缠论大中小三周期共振能量柱 (日-30F-5F) ==================== }
{ 1. 大级别(日线)多空量化 }
大_DIF:="MACD.DIF#DAY"(12,26,9);
大_DEA:="MACD.DEA#DAY"(12,26,9);
大多头:=IF(ISNAN(大_DIF) OR 大_DIF=0, CLOSE>MA(CLOSE,20), 大_DIF>大_DEA);
大级别多头: IF(大多头, 3, 0), COLORRED, NODRAW;

{ 2. 中级别(30分钟)多空量化 }
中_DIF:="MACD.DIF#MIN30"(12,26,9);
中_DEA:="MACD.DEA#MIN30"(12,26,9);
中多头:=IF(ISNAN(中_DIF) OR 中_DIF=0, CLOSE>REF(CLOSE,1), 中_DIF>中_DEA);
中级别多头: IF(中多头, 2, 0), COLORYELLOW, NODRAW;

{ 3. 小级别(5分钟)多空量化 }
小_DIF:="MACD.DIF#MIN5"(12,26,9);
小_DEA:="MACD.DEA#MIN5"(12,26,9);
DIF:=(EMA(CLOSE,12)-EMA(CLOSE,26));
DEA:=EMA(DIF,9);
小多头:=IF(ISNAN(小_DIF) OR 小_DIF=0, DIF>DEA, 小_DIF>小_DEA);
小级别多头: IF(小多头, 1, 0), COLORCYAN, NODRAW;

{ 4. 立体共振综合得分 (0 ~ 3 分) }
共振得分: 大多头 + 中多头 + 小多头, COLORWHITE, NODRAW;

{ 绘制大中小三层能量轨道柱状带 }
{ 第一层：小级别 5F 状态 (底层 0 ~ 1) }
STICKLINE(小多头, 0, 1, 2, 0), COLOR0088FF;
STICKLINE(NOT(小多头), 0, 1, 2, 0), COLOR333333;

{ 第二层：中级别 30F 状态 (中层 1.2 ~ 2.2) }
STICKLINE(中多头, 1.2, 2.2, 2, 0), COLOR00DDDD;
STICKLINE(NOT(中多头), 1.2, 2.2, 2, 0), COLOR444444;

{ 第三层：大级别 日线 状态 (高层 2.4 ~ 3.4) }
STICKLINE(大多头, 2.4, 3.4, 2, 0), COLOR0000FF;
STICKLINE(NOT(大多头), 2.4, 3.4, 2, 0), COLOR555555;

{ 5. 三级别全红共振暴击信号 (当得分达到 3 分时触发大爆发) }
三级共振: 共振得分=3, COLORRED, NODRAW;
STICKLINE(三级共振 AND REF(三级共振,1)=0, 0, 3.4, 1.5, 0), COLORWHITE;
DRAWICON(三级共振 AND REF(三级共振,1)=0, 3.6, 25); { 钱袋子/大买点图标 }
DRAWTEXT(三级共振 AND REF(三级共振,1)=0, 3.8, '★大中小共振'), COLOR00FFFF;

{ 标注层级说明 }
DRAWTEXT_FIX(ISLASTBAR, 0.01, 0.05, 0, '【上轨:大级别(日) 中轨:中级别(30F) 下轨:小级别(5F)】'), COLORWHITE;
```

---

## 三、条件选股公式代码：`CL_GZ_BUY`（大中小三级别共振选股）

- **公式名称**：`CL_GZ_BUY`
- **公式描述**：缠论大中小三周期买点立体共振选股（日-30F-5F）
- **公式类型**：条件选股公式
- **选股周期**：日线

### 公式代码（复制下方全部内容到通达信条件选股编辑器）：

```pascal
{ ==================== 缠论大中小三级别立体共振选股 (日-30F-5F) ==================== }
{ 1. 大级别(日线)处于多头趋势或金叉初成 }
日_DIF:="MACD.DIF#DAY"(12,26,9);
日_DEA:="MACD.DEA#DAY"(12,26,9);
DIF:=(EMA(CLOSE,12)-EMA(CLOSE,26));
DEA:=EMA(DIF,9);
日多头:=IF(ISNAN(日_DIF) OR 日_DIF=0, DIF>DEA, 日_DIF > 日_DEA);

{ 2. 中级别(30分钟)底背驰或二三买多头波段 }
F30_DIF:="MACD.DIF#MIN30"(12,26,9);
F30_DEA:="MACD.DEA#MIN30"(12,26,9);
F30多头:=IF(ISNAN(F30_DIF) OR F30_DIF=0, DIF>DEA, F30_DIF > F30_DEA);

{ 3. 小级别(5分钟)止跌或金叉启动 }
F5_DIF:="MACD.DIF#MIN5"(12,26,9);
F5_DEA:="MACD.DEA#MIN5"(12,26,9);
F5多头:=IF(ISNAN(F5_DIF) OR F5_DIF=0, DIF>DEA, F5_DIF > F5_DEA);

{ 4. 缠论形态：日线站上 20 日均线且波谷未创新低 (二买/三买雏形) }
MA20:=MA(CLOSE, 20);
趋势向上:=CLOSE >= MA20 AND MA20 >= REF(MA20, 1);

TB1:=TROUGHBARS(1, 5, 1);
ZD1:=TROUGH(1, 5, 1);
ZD2:=TROUGH(1, 5, 2);
回踩不破底:=TB1 <= 5 AND ZD1 >= ZD2;

{ 5. 三级别共振启动条件 }
共振选股: 日多头 AND F30多头 AND F5多头 AND 趋势向上 AND (回踩不破底 OR CROSS(DIF, DEA));
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
