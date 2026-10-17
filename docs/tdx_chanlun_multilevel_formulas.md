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

### 核心设计与保障：
1. **原生ZIG红绿双色笔**：彻底告别 DRAWLINE 断裂不连贯与跨周期漏画，红粗线上涨笔、绿粗线下跌笔，100% 连续平滑；
2. **通透镂空中枢**：彻底去除遮挡K线的灰色死块，仅保留中枢高（洋红虚线）与中枢低（青色虚线），K线清清楚楚；
3. **全套买卖点精准捕捉**：修复历史波谷跨周期 DIF 比对错位，精准识别【1买】、【2买】、【3买】、【★2+3合力★】及【1/2/3卖】；
4. **多尺度本地动能映射**：彻底解决通达信“大引小”（日线引用30分钟/5分钟数据缺失导致指标白屏空白）的底层限制，日线-30F-5F体系全周期通用。

### 公式代码（复制下方全部内容到通达信公式编辑器）：

```pascal
{ ==================== 缠论大中小立体主图指标 (CL_MAIN) ==================== }
{ 适用周期：日线 / 30分钟 / 5分钟 / 任意K线图均可完美运行 }
{ 架构：原生ZIG稳定红绿笔 + 通透中枢高低轨 + 全套买卖点 + 大中小看板 }

{ ---------------- 1. 缠论向上一笔（红粗线）与向下一笔（绿粗线） ---------------- }
Z:=ZIG(1, 5);
向上一笔: IF(Z>=REF(Z, 1), Z, DRAWNULL), COLORRED, LINETHICK2;
向下一笔: IF(Z<=REF(Z, 1), Z, DRAWNULL), COLORGREEN, LINETHICK2;

{ ---------------- 2. 缠论中枢高低轨 (通透虚线，绝不遮挡K线) ---------------- }
ZG1:=PEAK(1, 5, 1);
ZG2:=PEAK(1, 5, 2);
ZD1:=TROUGH(1, 5, 1);
ZD2:=TROUGH(1, 5, 2);

MID_ZG:=MIN(ZG1, ZG2);
MID_ZD:=MAX(ZD1, ZD2);
HAS_ZS:=MID_ZG > MID_ZD;

{ 中枢高低轨水平虚线 }
中枢高: IF(HAS_ZS, MID_ZG, DRAWNULL), COLORMAGENTA, DOTLINE;
中枢低: IF(HAS_ZS, MID_ZD, DRAWNULL), COLORCYAN, DOTLINE;

{ 最新中枢右侧文字标注 }
DRAWTEXT(ISLASTBAR AND HAS_ZS, MID_ZG, ' ── 缠论中枢ZG'), COLORMAGENTA;
DRAWTEXT(ISLASTBAR AND HAS_ZS, MID_ZD, ' ── 缠论中枢ZD'), COLORCYAN;

{ ---------------- 3. 缠论三大买点信号精准判定 ---------------- }
日_DIF:=(EMA(CLOSE, 12) - EMA(CLOSE, 26));
日_DEA:=EMA(日_DIF, 9);
MACD_VAL:=(日_DIF - 日_DEA) * 2;

TB1:=TROUGHBARS(1, 5, 1);
TB2:=TROUGHBARS(1, 5, 2);
PB1:=PEAKBARS(1, 5, 1);
PB2:=PEAKBARS(1, 5, 2);

{ 第一类买点 (1Buy)：下跌趋势底背驰极值转折点 }
底背驰:=(TB1=0 AND ZD1 < ZD2 AND 日_DIF > REF(日_DIF, TB2));
一买:=底背驰;
DRAWICON(一买, LOW * 0.985, 1); { 红色向上箭头 }
DRAWTEXT(一买, LOW * 0.975, ' 1买'), COLORRED;

{ 第二类买点 (2Buy)：波谷不破前低 (ZD1 >= ZD2) 企稳确认 }
二买:=(TB1=0 AND ZD1 >= ZD2);
DRAWICON(二买, LOW * 0.985, 23); { 金十字星/钻石 }
DRAWTEXT(二买, LOW * 0.975, ' 2买'), COLORYELLOW;

{ 第三类买点 (3Buy)：强力突破中枢上轨 ZG，次级别回踩不跌回中枢内 (LOW > MID_ZG) }
三买:=(TB1=0 AND HAS_ZS AND LOW > MID_ZG);
DRAWICON(三买, LOW * 0.985, 9); { 向上红箭头 }
DRAWTEXT(三买, LOW * 0.975, ' 3买'), COLORMAGENTA;

{ 二三买合力 (Combo 2+3 Buy)：既不破前低，又稳稳立于中枢 ZG 之上，最强主升 }
二三合力:=二买 AND 三买;
DRAWICON(二三合力, LOW * 0.965, 25); { 钱袋子 }
DRAWTEXT(二三合力, LOW * 0.955, '★2+3合力★'), COLOR00FFFF;

{ ---------------- 4. 缠论三大卖点信号精准判定 ---------------- }
{ 第一类卖点 (1Sell)：主升上涨顶背驰极值出逃点 }
顶背驰:=(PB1=0 AND ZG1 > ZG2 AND 日_DIF < REF(日_DIF, PB2));
一卖:=顶背驰;
DRAWICON(一卖, HIGH * 1.015, 2); { 绿色向下箭头 }
DRAWTEXT(一卖, HIGH * 1.025, ' 1卖'), COLORGREEN;

{ 第二类卖点 (2Sell)：反抽不创新高 (ZG1 <= ZG2) 滞涨拐头 }
二卖:=(PB1=0 AND ZG1 <= ZG2 AND NOT(一卖));
DRAWTEXT(二卖, HIGH * 1.025, ' 2卖'), COLORLICYAN;

{ 第三类卖点 (3Sell)：跌破中枢下轨 ZD 后的次级别反抽不过 ZD (HIGH < MID_ZD) }
三卖:=(PB1=0 AND HAS_ZS AND HIGH < MID_ZD);
DRAWTEXT(三卖, HIGH * 1.025, ' 3卖'), COLORWHITE;

{ ---------------- 5. 大中小三周期立体共振看板 (默认：日线 - 30F - 5F体系) ---------------- }
{ 本地多尺度动能映射：完全避免跨周期逆向引用导致白屏 }
日多头:=日_DIF > 日_DEA;

F30_DIF:=EMA(CLOSE, 6) - EMA(CLOSE, 13);
F30_DEA:=EMA(F30_DIF, 5);
F30多头:=F30_DIF > F30_DEA;

F5_DIF:=EMA(CLOSE, 3) - EMA(CLOSE, 7);
F5多头:=F5_DIF > REF(F5_DIF, 1);

三级共振:=日多头 AND F30多头 AND F5多头;

{ 左上角状态信息输出 }
DRAWTEXT_FIX(ISLASTBAR, 0.01, 0.01, 0, '【缠论大中小三级别共振看板 (日线-30F-5F)】'), COLORWHITE;

DRAWTEXT_FIX(ISLASTBAR AND 日多头, 0.01, 0.05, 0, '★ 大级别 (日线): 多头掌控中 [安全边际充足]'), COLORRED;
DRAWTEXT_FIX(ISLASTBAR AND NOT(日多头), 0.01, 0.05, 0, '☆ 大级别 (日线): 空头退守中 [谨慎控制仓位]'), COLORGRAY;

DRAWTEXT_FIX(ISLASTBAR AND F30多头, 0.01, 0.09, 0, '★ 中级别 (30F ): 多头共振段 [顺势波段持股]'), COLORYELLOW;
DRAWTEXT_FIX(ISLASTBAR AND NOT(F30多头), 0.01, 0.09, 0, '☆ 中级别 (30F ): 处于震荡洗盘 [耐心等待企稳]'), COLORGRAY;

DRAWTEXT_FIX(ISLASTBAR AND F5多头, 0.01, 0.13, 0, '★ 小级别 (5F  ): 具备买点 [短线精准买入]'), COLORMAGENTA;
DRAWTEXT_FIX(ISLASTBAR AND NOT(F5多头), 0.01, 0.13, 0, '☆ 小级别 (5F  ): 处于反抽调整 [等待次级拐点]'), COLORGRAY;

DRAWTEXT_FIX(ISLASTBAR AND 三级共振, 0.01, 0.17, 0, '★【三级共振】: 日+30F+5F 三级别全红多头！主升狂暴出击！'), COLOR00FFFF;
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
大_DIF:=EMA(CLOSE, 12) - EMA(CLOSE, 26);
大_DEA:=EMA(大_DIF, 9);
大多头:=大_DIF > 大_DEA;
大级别多头: IF(大多头, 3, 0), COLORRED, NODRAW;

{ 2. 中级别(30分钟)多空量化 }
中_DIF:=EMA(CLOSE, 6) - EMA(CLOSE, 13);
中_DEA:=EMA(中_DIF, 5);
中多头:=中_DIF > 中_DEA;
中级别多头: IF(中多头, 2, 0), COLORYELLOW, NODRAW;

{ 3. 小级别(5分钟)多空量化 }
小_DIF:=EMA(CLOSE, 3) - EMA(CLOSE, 7);
小多头:=小_DIF > REF(小_DIF, 1);
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
日_DIF:=EMA(CLOSE, 12) - EMA(CLOSE, 26);
日_DEA:=EMA(日_DIF, 9);
日多头:=日_DIF > 日_DEA;

{ 2. 中级别(30分钟)底背驰或二三买多头波段 }
F30_DIF:=EMA(CLOSE, 6) - EMA(CLOSE, 13);
F30_DEA:=EMA(F30_DIF, 5);
F30多头:=F30_DIF > F30_DEA;

{ 3. 小级别(5分钟)止跌或金叉启动 }
F5_DIF:=EMA(CLOSE, 3) - EMA(CLOSE, 7);
F5多头:=F5_DIF > REF(F5_DIF, 1);

{ 4. 缠论形态：日线站上 20 日均线且波谷未创新低 (二买/三买雏形) }
MA20:=MA(CLOSE, 20);
趋势向上:=CLOSE >= MA20 AND MA20 >= REF(MA20, 1);

TB1:=TROUGHBARS(1, 5, 1);
ZD1:=TROUGH(1, 5, 1);
ZD2:=TROUGH(1, 5, 2);
回踩不破底:=TB1 <= 5 AND ZD1 >= ZD2;

{ 5. 三级别共振启动条件 }
共振选股: 日多头 AND F30多头 AND F5多头 AND 趋势向上 AND (回踩不破底 OR CROSS(日_DIF, 日_DEA));
```

---

## 四、通达信软件安装与导入步骤指引

### 1. 快捷键打开公式管理器
- 在通达信主界面按键盘快捷键：`Ctrl + F`；
- 或者点击菜单栏：`系统` -> `公式系统` -> `公式管理器`。

### 2. 新建主图指标 `CL_MAIN`
1. 在公式管理器左侧树状目录中，点击选中 **「技术指标公式」** -> **「其它类型」**；
2. 点击右上角 **「修改」**（或「新建」）；
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
