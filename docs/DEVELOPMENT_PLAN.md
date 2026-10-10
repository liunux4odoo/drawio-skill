# Drawio Skill 缺陷修复开发计划

> 交付对象：code agent（执行者）。
> 背景：二轮人工 review 对技能自带的两个 Python 工具做了端到端实测 + 渲染截图比对，
> 发现校验器/渲染器的实际行为与 `SKILL.md` 的承诺存在多处落差。本计划逐条给出
> 问题、边界维度、修复要求与可执行验收命令。
>
> 本文件是**任务契约**：WHAT 必须达成，HOW 由你决定。

---

## 0. 全局约束

1. 三个脚本继续保持 **Python 标准库零依赖**（`render_drawio.py --png` 对 cairosvg 的
   可选依赖不变）。仅兼容 Python 3.10+（本机 3.12）。
2. **向后兼容**：现有 CLI 参数、退出码语义（0 通过 / 1 错误 / 2 文件错误）、stdout
   基本格式不得破坏；允许新增 flag 和输出行。
3. **文档同步是任务的一部分**：任何行为变更都必须同步 `SKILL.md` / `patterns.md` /
   `README.md` 的相关表述，不允许代码改了文档还在承诺旧行为。
4. 生成器输出保持确定性（无时间戳/随机数）。
5. 提交前删除测试产生的 `__pycache__`；生成物不要留在仓库里。
6. 仓库当前 git 无任何提交。建议首个 commit 先固化现状，修复按任务分批 commit，
   commit message 中文、简短；如果你所在环境不允许 commit，至少保证工作区状态干净可 diff。

### 沟通规约（重要）

- **QUESTIONS.md（仓库根）**：遇到契约歧义、两种合理实现无法抉择、或发现本计划
  自相矛盾时，停下来把问题写进该文件，**不要自己发明 workaround 再往下跑**。
  写清楚：歧义点、涉及的任务号、候选方案及各自代价。
- **FINDINGS.md（仓库根）**：记录计划之外的意外发现（新 bug、draw.io 行为与预期
  不符、测试中暴露的其他问题），每条附复现方式。
- 没有相关内容时可不建文件；任务结束时保留这两个文件作为交付说明的一部分。

### 优先级

- **P0（T1–T5）+ P1（T6–T7）必做**，是本次验收主体。
- **P2（T8–T9）文档必做**，成本极低。
- **P3（T10–T13）可选**，不做不阻塞验收；建议至少做 T12（回归测试）。

---

## P0 — verify_diagram.py 正确性缺陷

### T1. 多页文件被误判为非法

**现象（已实测）**：含两个 `<diagram>` 的合法文件报
`duplicate cell id: '0'/'1'` 和同坐标 `overlap`，且 page 尺寸只取第一页。

**要求**：

1. 重构 cell 收集与检查逻辑，按 `<diagram>` 分页：每个页面各自拥有独立的
   `id="0"`/`id="1"` 根 cell，不允许跨页判重、不允许跨页判重叠/间距。
2. 全局唯一的问题（如两个 `<diagram>` 的 `id` 属性相同）仍应检查——diagram 的
   id 在文件级应唯一。
3. 每页独立读取 `pageWidth/pageHeight/page`，输出中按页报告。
4. edge 的 source/target、cell 的 parent **只在同页内解析**；跨页引用报 error。
5. 单页文件的输出与现状保持一致。

**边界维度（测试用例源头）**：

| # | 输入 | 期望 |
|---|---|---|
| 1 | 两页，各自含 id=0/1 和同坐标 box | exit 0，无重复/重叠错误 |
| 2 | 两页，`<diagram id="same">` | exit 1，diagram id 重复 |
| 3 | edge 的 source 指向另一页的 cell | exit 1，引用不存在（跨页） |
| 4 | 两页 pageWidth 不同 | 分别按各自尺寸检查出页 |
| 5 | 单页标准文件 | 行为/输出与修复前一致 |

**验收**：见文末 §A 全套命令；构造上述文件逐条核对。

---

### T2. CJK 标签溢出漏报（截图实锤）

**现象（已实测）**：31 个中文字放入 width=160 的盒子，真实渲染左右被裁切，
校验器报 OK。根因：`CHAR_W_FACTOR=0.6` 按拉丁平均字宽估算，CJK 全角字实际约 1.0em；
`split_lines` 的每行容量同样偏小、换行点错误。

**要求**：

1. 在 `verify_diagram.py` 与 `render_drawio.py` 中引入**同一个字宽规则**（可分别
   落地但行为必须一致，注释互相标明）：
   - `unicodedata.east_asian_width(ch)` 为 `W`/`F`（及你判断需要的 `A`）→ 1.0em
   - `Na`/`H` 等 → 0.6em（沿用现有拉丁估算）
2. 标签宽度 = 逐字宽度 × fontSize 之和；wrap 模式的每行容量按同一规则计算。
3. 仍报 warning（与现有严重度约定一致），`--strict` 升级 error 的行为不变。

**边界维度**：

| # | 输入 | 期望 |
|---|---|---|
| 1 | 31 个中文字 / 160px 宽 / wrap | 横向溢出 warning（实测真实溢出） |
| 2 | 短中文（如"用户认证"，4 字）/ 160px | 无 warning |
| 3 | 纯拉丁长词 / wrap 关闭 | 行为与修复前一致 |
| 4 | 中英混排（如"User 用户认证 Service"） | 按逐字规则估算，不报明显错误的 |
| 5 | 中文多行导致纵向超高 | 纵向溢出 warning |

---

### T3. edge crossing 检查的几何模型与真实路由不一致

**现象（已实测）**：

- 对角节点 A(40,40)→B(520,240)、障碍 C(280,140)：正交 L 路由不穿 C，
  校验器按中心直线误报 crossing（exit 1）。
- `curved=1` 弧线穿障碍时直线模型漏报。

根因：检查折线恒为 `center → points → center`（约 verify_diagram.py:388），
未使用 style 中的 exitX/exitY/entryX/entryY，也未复刻正交折弯。

**要求**：

1. 边的起终点改为按 style 显式锚点计算；无显式锚点时采用与 `render_drawio.py`
   `anchor()` 相同的默认规则（朝向目标的边中点）。
2. 无 waypoint 的 `orthogonalEdgeStyle` 边：插入与 renderer 相同的单折弯点
   （水平差≥竖直差先走横，否则先走竖），检查折线按折弯后的路径构造。
3. 非正交、无 waypoint 的边：保持起终点直线段检查。
4. `curved=1`：直线模型无法代表弧线，**降级为 warning**（文案：曲线边无法机械
   判定 crossing，需视觉确认），不得静默跳过。
5. 检查范围仍对齐 bundled renderer 的近似定位：它是布局检查工具，不追求
   draw.io 像素级路由仿真。

**边界维度**：

| # | 输入 | 期望 |
|---|---|---|
| 1 | 对角节点 + 正交 L 路由绕开障碍 | exit 0，不误报 |
| 2 | 同行节点、直线必然穿过中间障碍 | exit 1，真实报出（已实测此场景为真阳性） |
| 3 | curved=1 弧线（无论是否穿障碍） | warning，提示视觉确认 |
| 4 | 显式 exitX/Y + entryX/Y 锚点 | 按锚点位置构造检查折线 |
| 5 | 带 2 个 waypoint 的绕行边 | 沿用 waypoint 折线，行为不变 |

---

### T4. 压缩载荷无专门识别，报错误导

**现象（已实测）**：压缩图表报 `no mxCell found` + `missing 0/1` 三条错误，
而非按 SKILL §1 CRITICAL 提示"这是压缩载荷"。

**要求**：

1. 检测条件：`<diagram>` 含非空文本内容但内部没有 `mxGraphModel`/`mxCell` 子元素
   （典型为 base64 串，常以 `zZ` 开头，但**不要只认 zZ 前缀**）。
2. 输出一条明确 error，文案包含：检测到压缩/编码图表载荷、不要手改、请先在
   draw.io 中 `Extras → Uncompressed XML` 导出后再编辑。
3. 此场景下不再输出"missing 0/1"等误导性错误。

---

### T5. waypoint 出页不检查

**现象**：on-page 检查只遍历顶点矩形，边的 waypoint 超出页面不报错。

**要求**：`page != "0"` 时，对每条边的检查折线（锚点 + waypoint，绝对坐标）
检查是否超出 `pageWidth/pageHeight`；超出报 error，指出边 id 与越界坐标。
顶点的既有出页检查不变。

---

## P1 — render_drawio.py 缺陷

### T6. `shape=xxx` 写法的三种形状渲染成矩形（截图实锤）

**现象**：`patterns.md` 推荐的 `shape=cylinder3` / `shape=hexagon` /
`shape=parallelogram`，经 `parse_style` 后位于 `st["shape"]`，而代码（约 235/239/243
行）用 `"hexagon" in st` 判断**键名包含**，永不命中。

**要求**：

1. 判断改为同时识别两种写法：`st.get("shape") == "<name>"` 或裸键 `"<name>" in st`。
2. 对 cylinder3 / hexagon / parallelogram 三种形状都生效，渲染出与各自裸键写法
   相同的图形。
3. patterns.md 无需改写法（两种都合法），但确认文档示例渲染正确。

### T7. SVG viewport 裁剪 waypoint 绕行路线

**现象**：`render()` 的边界只从顶点包围盒聚合，含 waypoint 的绕行段落在 viewBox
外被裁掉——视觉检查时看不到最该检查的路线。

**要求**：viewport 边界同时聚合每条边的**实际锚点与全部 waypoint**（边处理需要在
bounds 计算前完成；锚点复用 T3 统一后的规则）。顶点与边的绘制顺序不变。

---

## P2 — 文档与模板

### T8. SKILL.md §8.1 列表格式

1. 修复第 7/8/9 项（约 206–208 行）多出来的一个前导空格，恢复有序列表连续编号。
2. §8.1 第 5 项声称 gap ≥40 被机械拦截，但实际 verifier 报 warning（exit 0）。
   修改文档措辞，如实说明：重叠为 error、间距不足为 warning（`--min-gap` 可调）。
   **不要**为了迁就文档把 gap 全面升级成 error（会产生大量噪音）。

### T9. README.md 两处表述

1. "register this repository as a plugin marketplace" 的说法目前不成立——仓库没有
   `.claude-plugin/marketplace.json`。二选一：删除该安装路径，或补齐清单文件。
   若选择补文件，保持最小有效结构，并实际验证路径自洽。**默认建议：删除该说法**。
2. `generate_diagram.py` 的 `emit()` 中 `agent="kilo"` 与技能通用定位不符，
   改为中性值（如删除 agent 属性），跑一遍确认输出仍通过 verifier。

---

## P3 — 可选增强（不阻塞验收）

- **T10. verifier 补两条零成本检查**：
  - corner anchor：exitX/exitY（或 entryX/entryY）同时为 0/1 → warning（§6 rule 3）；
  - 同 source/target 的两条边四锚点完全相同 → warning（§6 rule 2）。
- **T11.** edge 缺 source 或 target 时目前静默跳过几何检查：改为 error，明确指出
  边 id 缺哪个属性。
- **T12（强烈建议）. 回归测试**：在 `tests/` 下用 pytest 固化本次全部 P0/P1 场景。
  建议目录：
  ```
  tests/
  ├── conftest.py
  ├── fixtures/            # 每个边界维度一个最小 .drawio
  │   ├── multipage.drawio
  │   ├── cjk_overflow.drawio
  │   ├── compressed.drawio
  │   ├── shape_styles.drawio
  │   └── edge_crossing_*.drawio
  ├── test_verify.py
  ├── test_render.py       # 至少断言 SVG 良构 + 形状 path/标签出现
  └── test_generator.py
  ```
  测试不得依赖网络/cairosvg；fixture 同时用于人工按 §A 验收。
- **T13.** renderer 多页时目前静默合并为一张 SVG：可加 `--page N`（按页序号或
  名称选择）；未指定时输出中提示包含多页。

---

## 建议实施顺序

1. **T1**（分页重构）——后续所有 verifier 任务都在新结构上做，先改地基。
2. T6、T7（renderer，互相独立）。
3. T2（CJK，verifier 与 renderer 同步）。
4. T3（crossing 模型，复用 T7 的锚点/边界成果，最大的一项）。
5. T4、T5（小改动）。
6. T8、T9（文档）。
7. T12（回归测试，边做边补也可以；最后跑全绿）。
8. T10/T11/T13 视精力。

---

## §A 验收命令（全部须实际执行通过）

以下命令在仓库根执行；fixture 文件由你在实现时按边界维度创建（建议放 `tests/fixtures/`）。

```bash
# 1. 三个脚本语法与基础流程
python3 -m py_compile skills/drawio/references/*.py
python3 skills/drawio/references/generate_diagram.py > /tmp/_pipeline.drawio
python3 skills/drawio/references/verify_diagram.py /tmp/_pipeline.drawio        # exit 0, OK
python3 skills/drawio/references/render_drawio.py /tmp/_pipeline.drawio -o /tmp/_pipeline.svg
python3 -c "import xml.etree.ElementTree as ET; ET.parse('/tmp/_pipeline.svg')" # SVG 良构

# 2. 多页文件不再误报（fixture：两页同坐标 box）
python3 skills/drawio/references/verify_diagram.py tests/fixtures/multipage.drawio   # exit 0

# 3. CJK 溢出被检出（fixture：31 中文字 / 160px / wrap）
python3 skills/drawio/references/verify_diagram.py tests/fixtures/cjk_overflow.drawio
# 期望：含 "overflow" 的 WARNING；--strict 时 exit 1
python3 skills/drawio/references/verify_diagram.py --strict tests/fixtures/cjk_overflow.drawio

# 4. 对角正交边不误报 / curved 仅 warning
python3 skills/drawio/references/verify_diagram.py tests/fixtures/edge_diagonal_lroute.drawio  # exit 0
python3 skills/drawio/references/verify_diagram.py tests/fixtures/edge_curved.drawio           # exit 0 + warning

# 5. 压缩载荷给出专门提示
python3 skills/drawio/references/verify_diagram.py tests/fixtures/compressed.drawio
# 期望输出含 "compressed"/"压缩" 字样，且不含 "missing root cell"

# 6. shape= 三种形状真正渲染（SVG 中应出现 polygon/path/ellipse 而非仅 rect）
python3 skills/drawio/references/render_drawio.py tests/fixtures/shape_styles.drawio -o /tmp/_shapes.svg
grep -c "polygon\|<ellipse" /tmp/_shapes.svg   # >= 2（hexagon + parallelogram，cylinder 含 ellipse）

# 7. waypoint 绕行不被 viewport 裁剪（fixture：waypoint 远在顶点包围盒外）
python3 skills/drawio/references/render_drawio.py tests/fixtures/waypoint_detour.drawio -o /tmp/_detour.svg
grep -o 'viewBox="[^"]*"' /tmp/_detour.svg   # 边界须覆盖 waypoint 坐标

# 8. 文档格式与残留检查
grep -n '^ 7\.\|^ 8\.\|^ 9\.' skills/drawio/SKILL.md && exit 1 || true   # 无输出=已修复
! grep -q 'plugin marketplace' README.md || test -f .claude-plugin/marketplace.json
! grep -q 'agent="kilo"' skills/drawio/references/generate_diagram.py

# 9. 回归测试（若做 T12）
python3 -m pytest -q
```

验收标准：上述命令逐条满足；`QUESTIONS.md` 中的问题有结论或已上报；
`FINDINGS.md` 如实记录；最终汇报列出每个任务的改动文件与对应验收结果。
