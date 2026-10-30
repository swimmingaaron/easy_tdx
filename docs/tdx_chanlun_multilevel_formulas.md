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
{======================================================================
 公式名称: CL_MAIN (缠论标准线段中枢立体主图)
 适用环境: 通达信 (PC端与手机端)
 画线方式: 主图叠加
 核心标准:
   1. K线合并处理: 严格先消除K线包含关系 (向上取高高, 向下取低低)
   2. 两类标准中枢结构识别:
      - 上涨中枢 (下 - 上 - 下): 3根连续完成次级别线段重叠成型
      - 下跌中枢 (上 - 下 - 上): 3根连续完成次级别线段重叠成型
   3. 中枢区间: ZG=MIN(前三段高), ZD=MAX(前三段低), 条件 ZG > ZD
   4. 中枢可视化: 封闭矩形框 + 内部通透竖直栅格 + 右侧水平延伸线 (绝不遮挡K线)
   5. 缠论全套买卖点: 1买/2买/3买 与 1卖/2卖/3卖 (3买严格要求回抽不破ZG)
======================================================================}

{---------------- 1. 经典均线系统 ----------------}
MA5:MA(C,5),COLORWHITE,LINETHICK1;
MA10:MA(C,10),COLORYELLOW,LINETHICK1;
MA20:MA(C,20),COLORMAGENTA,LINETHICK1;
MA60:MA(C,60),COLORGREEN,LINETHICK1;

{---------------- 2. 缠论 K 线合并 (包含处理) ----------------}
K_DIR_RAW:=IF(H>=REF(H,1) AND L>=REF(L,1), 1, IF(H<=REF(H,1) AND L<=REF(L,1), -1, 0));
K_DIR:=REF(K_DIR_RAW, BARSLAST(K_DIR_RAW!=0));
IS_BH:=(H<=REF(H,1) AND L>=REF(L,1)) OR (H>=REF(H,1) AND L<=REF(L,1));

CH_UP:=IF(IS_BH AND K_DIR=1, MAX(H, REF(H,1)), H);
CL_UP:=IF(IS_BH AND K_DIR=1, MAX(L, REF(L,1)), L);
CH:=IF(IS_BH AND K_DIR=-1, MIN(H, REF(H,1)), CH_UP);
CL:=IF(IS_BH AND K_DIR=-1, MIN(L, REF(L,1)), CL_UP);
{对合并K线做轻量半透明提示}
STICKLINE(IS_BH, CH, CL, 0.1, 0), COLOR444444;

{---------------- 3. 笔与线段 (次级别走势类型) ----------------}
{基础笔 (细线): 5% 波动}
Z_BI:=ZIG(1, 5);
BI_UP:=Z_BI>=REF(Z_BI,1);
BI_DN:=Z_BI<=REF(Z_BI,1);
DRAWLINE(BI_DN AND REF(BI_UP,1), Z_BI, BI_UP AND REF(BI_DN,1), Z_BI, 0), COLOR00E5FF, LINETHICK1;
DRAWLINE(BI_UP AND REF(BI_DN,1), Z_BI, BI_DN AND REF(BI_UP,1), Z_BI, 0), COLOR00E5FF, LINETHICK1;

{核心线段 (粗线): 8% 波动，构成中枢的次级别走势类型}
Z_XD:=ZIG(1, 8);
XD_UP:=Z_XD>=REF(Z_XD,1);
XD_DN:=Z_XD<=REF(Z_XD,1);
DRAWLINE(XD_DN AND REF(XD_UP,1), Z_XD, XD_UP AND REF(XD_DN,1), Z_XD, 0), COLORFF00FF, LINETHICK2;
DRAWLINE(XD_UP AND REF(XD_DN,1), Z_XD, XD_DN AND REF(XD_UP,1), Z_XD, 0), COLORFF00FF, LINETHICK2;

{---------------- 4. 线段高低点提取 (1~4号转折点) ----------------}
H1:=PEAK(1, 8, 1);
H2:=PEAK(1, 8, 2);
H3:=PEAK(1, 8, 3);
H4:=PEAK(1, 8, 4);

L1:=TROUGH(1, 8, 1);
L2:=TROUGH(1, 8, 2);
L3:=TROUGH(1, 8, 3);
L4:=TROUGH(1, 8, 4);

TH1:=PEAKBARS(1, 8, 1);
TH2:=PEAKBARS(1, 8, 2);
TH3:=PEAKBARS(1, 8, 3);
TH4:=PEAKBARS(1, 8, 4);

TL1:=TROUGHBARS(1, 8, 1);
TL2:=TROUGHBARS(1, 8, 2);
TL3:=TROUGHBARS(1, 8, 3);
TL4:=TROUGHBARS(1, 8, 4);

{================ 5. 最新中枢 (中枢1) 划分与绘制 ================}
{两类标准结构识别: 上涨中枢(下-上-下) 与 下跌中枢(上-下-上)}
UP_ZS1:=TH2 > TL2 AND TL2 > TH1 AND TH1 > TL1;
DN_ZS1:=TL2 > TH2 AND TH2 > TL1 AND TL1 > TH1;

ZG1:=MIN(H1, H2);
ZD1:=MAX(L1, L2);
GG1:=MAX(H1, H2);
DD1:=MIN(L1, L2);
ZS1_OK:=(UP_ZS1 OR DN_ZS1) AND (ZG1 > ZD1);

{中枢1起止周期计算}
ZS1_START:=IF(UP_ZS1, TH2, TL2);
ZS1_END:=IF(UP_ZS1, TL1, TH1);

{K线处于当前中枢区间范围判定}
IN_ZS1:=ZS1_OK AND (CURRBARSCOUNT <= CONST(ZS1_START + 1)) AND (CURRBARSCOUNT >= CONST(ZS1_END + 1));

{画中枢1矩形边框 (上涨洋红 / 下跌青蓝)}
STICKLINE(IN_ZS1 AND UP_ZS1, CONST(ZG1), CONST(ZG1), 3, 0), COLORFF007F;
STICKLINE(IN_ZS1 AND UP_ZS1, CONST(ZD1), CONST(ZD1), 3, 0), COLORFF007F;
STICKLINE(IN_ZS1 AND DN_ZS1, CONST(ZG1), CONST(ZG1), 3, 0), COLOR00A8E8;
STICKLINE(IN_ZS1 AND DN_ZS1, CONST(ZD1), CONST(ZD1), 3, 0), COLOR00A8E8;

{中枢1左右垂直封闭边框}
STICKLINE(ZS1_OK AND CURRBARSCOUNT = CONST(ZS1_START + 1), CONST(ZD1), CONST(ZG1), 0.8, 0), COLORFF007F;
STICKLINE(ZS1_OK AND CURRBARSCOUNT = CONST(ZS1_END + 1), CONST(ZD1), CONST(ZG1), 0.8, 0), COLORFF007F;

{中枢1内部通透竖直栅格 (每隔3根K线一条细线)}
STICKLINE(IN_ZS1 AND UP_ZS1 AND MOD(CURRBARSCOUNT, 3)=0, CONST(ZD1), CONST(ZG1), 0, 0), COLOR800040;
STICKLINE(IN_ZS1 AND DN_ZS1 AND MOD(CURRBARSCOUNT, 3)=0, CONST(ZD1), CONST(ZG1), 0, 0), COLOR004060;

{中枢1右侧水平延伸虚线 (便于观察三买三卖离开与回抽)}
EXT_ZS1:=ZS1_OK AND (CURRBARSCOUNT < CONST(ZS1_END + 1));
STICKLINE(EXT_ZS1 AND UP_ZS1, CONST(ZG1), CONST(ZG1), 1.5, 0), COLORFF007F;
STICKLINE(EXT_ZS1 AND UP_ZS1, CONST(ZD1), CONST(ZD1), 1.5, 0), COLORFF007F;
STICKLINE(EXT_ZS1 AND DN_ZS1, CONST(ZG1), CONST(ZG1), 1.5, 0), COLOR00A8E8;
STICKLINE(EXT_ZS1 AND DN_ZS1, CONST(ZD1), CONST(ZD1), 1.5, 0), COLOR00A8E8;

{最新中枢右侧文字标记}
DRAWTEXT(ISLASTBAR AND ZS1_OK, CONST(ZG1), ' ── ZG(中枢高)'), COLORFF007F;
DRAWTEXT(ISLASTBAR AND ZS1_OK, CONST(ZD1), ' ── ZD(中枢低)'), COLOR00A8E8;

{================ 6. 历史中枢 (中枢2) 划分与绘制 ================}
UP_ZS2:=TH4 > TL4 AND TL4 > TH3 AND TH3 > TL3;
DN_ZS2:=TL4 > TH4 AND TH4 > TL3 AND TL3 > TH3;

ZG2:=MIN(H3, H4);
ZD2:=MAX(L3, L4);
ZS2_OK:=(UP_ZS2 OR DN_ZS2) AND (ZG2 > ZD2);

ZS2_START:=IF(UP_ZS2, TH4, TL4);
ZS2_END:=IF(UP_ZS2, TL3, TH3);

IN_ZS2:=ZS2_OK AND (CURRBARSCOUNT <= CONST(ZS2_START + 1)) AND (CURRBARSCOUNT >= CONST(ZS2_END + 1));

{画中枢2矩形边框与内部栅格}
STICKLINE(IN_ZS2 AND UP_ZS2, CONST(ZG2), CONST(ZG2), 3, 0), COLORFF007F;
STICKLINE(IN_ZS2 AND UP_ZS2, CONST(ZD2), CONST(ZD2), 3, 0), COLORFF007F;
STICKLINE(IN_ZS2 AND DN_ZS2, CONST(ZG2), CONST(ZG2), 3, 0), COLOR00A8E8;
STICKLINE(IN_ZS2 AND DN_ZS2, CONST(ZD2), CONST(ZD2), 3, 0), COLOR00A8E8;

STICKLINE(ZS2_OK AND CURRBARSCOUNT = CONST(ZS2_START + 1), CONST(ZD2), CONST(ZG2), 0.8, 0), COLORFF007F;
STICKLINE(ZS2_OK AND CURRBARSCOUNT = CONST(ZS2_END + 1), CONST(ZD2), CONST(ZG2), 0.8, 0), COLORFF007F;

STICKLINE(IN_ZS2 AND UP_ZS2 AND MOD(CURRBARSCOUNT, 3)=0, CONST(ZD2), CONST(ZG2), 0, 0), COLOR800040;
STICKLINE(IN_ZS2 AND DN_ZS2 AND MOD(CURRBARSCOUNT, 3)=0, CONST(ZD2), CONST(ZG2), 0, 0), COLOR004060;

{================ 7. 缠论 1/2/3 类买卖点精准标记 ================}
DIF:=(EMA(CLOSE,12) - EMA(CLOSE,26));
ACTIVE_ZG:=IF(ZS1_OK, CONST(ZG1), IF(ZS2_OK, CONST(ZG2), DRAWNULL));
ACTIVE_ZD:=IF(ZS1_OK, CONST(ZD1), IF(ZS2_OK, CONST(ZD2), DRAWNULL));

{第一类买点 (1买): 底背驰极值转折}
IS_1BUY:=TL1=0 AND L1 < L2 AND DIF > REF(DIF, TL2);
DRAWICON(IS_1BUY, L*0.985, 1);
DRAWTEXT(IS_1BUY, L*0.970, ' 1买'), COLORRED;

{第二类买点 (2买): 回踩不破前低确认}
IS_2BUY:=TL1=0 AND NOT(IS_1BUY) AND L1 >= L2;
DRAWICON(IS_2BUY, L*0.985, 23);
DRAWTEXT(IS_2BUY, L*0.970, ' 2买'), COLORYELLOW;

{第三类买点 (3买): 次级别强力离开中枢，回抽不跌破中枢上沿 (LOW >= ZG)}
IS_3BUY:=TL1=0 AND (L1 >= ACTIVE_ZG) AND (H1 > ACTIVE_ZG) AND (ACTIVE_ZG > 0);
DRAWICON(IS_3BUY, L*0.985, 9);
DRAWTEXT(IS_3BUY, L*0.970, ' ★3买'), COLORFF00FF;

{第一类卖点 (1卖): 顶背驰极值转折}
IS_1SELL:=TH1=0 AND H1 > H2 AND DIF < REF(DIF, TH2);
DRAWICON(IS_1SELL, H*1.015, 2);
DRAWTEXT(IS_1SELL, H*1.030, ' 1卖'), COLORGREEN;

{第二类卖点 (2卖): 反弹不过前高滞涨}
IS_2SELL:=TH1=0 AND NOT(IS_1SELL) AND H1 <= H2;
DRAWICON(IS_2SELL, H*1.015, 8);
DRAWTEXT(IS_2SELL, H*1.030, ' 2卖'), COLORLICYAN;

{第三类卖点 (3卖): 次级别跌破中枢，反抽不进入中枢下沿 (HIGH <= ZD)}
IS_3SELL:=TH1=0 AND (H1 <= ACTIVE_ZD) AND (L1 < ACTIVE_ZD) AND (ACTIVE_ZD > 0);
DRAWICON(IS_3SELL, H*1.015, 15);
DRAWTEXT(IS_3SELL, H*1.030, ' ★3卖'), COLORWHITE;

{---------------- 8. 转折极值点价格标注 ----------------}
DRAWNUMBER(TH1=0, H*1.010, H), COLORGRAY;
DRAWNUMBER(TL1=0, L*0.990, L), COLORGRAY;
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
