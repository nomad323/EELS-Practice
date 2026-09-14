# 离线软件验证记录

当前快捷键见「截图风格、显示顺序与键盘滚轮会话（2026-09-14）」及末节「滚轮模式左右键单步调整」；配色以「恢复原有深色配色」为准。前面“单击按钮启用”、粉色界面等均为保留的历史记录。

## 环境与范围

- 检查日期：2026-09-12（环境时区 +08:00）；执行者：AI 编码助手。
- 实际环境：Linux `6.18.33.2-microsoft-standard-WSL2` / x86_64；Python 3.14.4、NumPy 2.3.5、Pillow 12.1.1；Node v22.22.1；已有缓存 Chromium / Chrome 149.0.7827.55。
- 没有安装依赖、检索/导入外部源码、连接仪器、提交、推送或部署。HTTP 仅在离线测试时绑定回环地址，测试结束后关闭；没有留下运行中的练习服务或测试浏览器。
- 这是单元/算法与本地浏览器验证，不是实验光学模型、色差系数、安全或硬件验收。没有验证 Windows 浏览器→WSL2 localhost 转发。

## 原始资料保护与回归

原件保持不变，结束时复核 SHA256 与开始时一致：

| 文件 | SHA256 |
|---|---|
| `raw/20260912/xiangcha.py` | `1a9baa4ecbaae4d3118c530a94a816a1487857145a618d3fa55cca9ba0b720e9` |
| `raw/20260912/微信图片_20260906202340_284_99.jpg` | `b976dbd07d59f6219732aae79267b38da0ae4c93ffe71c5d01feeaf987594fb6` |

`legacy.py` 的默认 NumPy 随机顺序、狭缝及落点映射与原脚本对照。测试只从已检查的原脚本 AST 提取数值函数和常量到内存，不执行 Matplotlib import、绘图、主入口或输出写入。原件不随分发存在时，这个对照测试会明确跳过，固定数值回归仍执行。

- 原默认 500,000 光线：通过 490,940，通过率 0.98188。
- 原默认探测器 x 标准差：0.007175429422932736（原任意单位）。
- 50,000 光线 / seed=1234 的九项混合：逐字段与原脚本数值部分核对通过，容差 rtol=1e-14、atol=1e-16。
- 以上是旧算法回归，不表示其仪器物理假设已验证。

## 实际执行的检查

### 1. 单元、算法和 HTTP

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

最终结果：**24 个测试全部通过，1.630 s**；输出保存在 `processed/validation/unit-http-tests.txt`。

覆盖：九项定义/别名/叠加、非法输入、8 meV 基线与计数守恒、采样/像素/视野变化、D01 倾斜的积分展宽、额外高斯展宽方差合成、角窗口透过率、视野裁切、背景/低计数/多段半高区、对称孔径等价解、随机题复现和难度分离、精确补偿归零、灰度方向/上下翻转/锁定强度、不变更计数的显示、无 pickle NPZ、隐藏/揭示/重试/导出与独立会话、本地 HTTP 访问限制和静态资源白名单、原脚本回归。

修复过程如实记录：
- 第一轮 23 项中有 1 项失败：伪造 Host 的本地 HTTP 测试被环境代理处理，观察到 502 而非本地预期 403；并有测试未关闭 HTTPError 的 ResourceWarning。将测试 urllib opener 明确设为 `ProxyHandler({})`，并关闭错误响应后复测通过。不是放松应用的 Host 检查，也未修改系统代理配置。
- 代码复查发现统一视野预算可能把九项题的多个难度压缩到相同系数。改为不同难度不同视野预算，并新增回归测试；最终为 24 项。

### 2. 实际 Chromium 浏览器

```bash
node tests/browser_smoke.mjs /home/agent/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome
```

最终结果：**PASS**，JSON 输出在 `processed/validation/browser-test.json`。

使用已有 Chromium、Node 原生 WebSocket 和 DevTools Protocol，不安装 Playwright/npm 包。临时启动本地服务和独立无头浏览器，结束后停止。临时浏览器 profile 位于 `/tmp/eels-browser-*`，不复用个人浏览器资料，未自动删除这些临时目录。

实际浏览器检查了：
- 页面初始化、九滑块、数值输入同步与多项叠加；还通过 Chromium `Input.dispatchMouseEvent` 执行了真正的指针拖动。
- 默认 FWHM 显示 `8.002`；D01=40 的积分 FWHM 大于 60 meV；全部归零恢复基线。
- gamma 改变后谱线数组完全不变。
- 练习答案默认不在帧响应中；揭示后显示九行；把显示答案逐项输入，残差 RMS=0、FWHM 恢复基线；重试隐藏答案并清零补偿；新题流程。
- 1600 px 桌面和 390 px 窄屏布局，窄屏无页面横向溢出；没有捕获到 JS 运行异常或页面对外请求。

保存并人工读取检查了截图：
- `processed/validation/browser-desktop.png`
- `processed/validation/browser-narrow.png`

黑底白亮信号、谱线、半高标记、滑块和答案表均实际渲染。该检查不替代 Windows 浏览器的下载保存对话框、长期人工操作或目标机器转发验收；NPZ 下载接口的内容另由 HTTP 测试验证。

### 3. 基线、收敛、示例和性能

可重现命令（只刷新 `processed/` 派生输出）：

```bash
PYTHONPATH=src python3 tests/offline_report.py
```

2026-09-12 15:59:24 +08:00 的实际记录位于 `processed/validation/numerical-summary.json`：

| 场景 | FWHM / meV |
|---|---:|
| 默认零系数，65,536 光线、801 能量像素、±120 meV | 8.0020321711 |
| 零系数，4,096 光线、801 像素、±40 meV | 8.0000000000 |
| 零系数，262,144 光线、1601 像素、±120 meV | 8.0004699363 |
| 零系数，16,384 光线、801 像素、±480 meV | 8.0369884928 |
| 中级九项题 seed=42，未补偿，默认场景 | 12.7967698468 |

均属于合成程序结果，不是实测分辨率。默认零系数的总计数 999999.9999999893，与 1,000,000 相差约 1e-8；RMS 能量宽度 3.3972871092 meV。补偿恢复基线由单元测试和浏览器测试分别检查。

同环境、默认 65,536 光线 / 801×181 图像、暖缓存、30 次变更 D01 并保留 D20/D11 的 `Application.dispatch('/api/frame', ...)`：中位数 **10.81 ms**，P95 **12.97 ms**，最大 **13.69 ms**。包括数值计算、PNG 编码和响应数据构造，不包括 HTTP 传输、JSON 字节编码、浏览器绘制、首版的 90 ms 尾随防抖或 Windows 转发；不是端到端帧率承诺。该性能记录针对首版；下方交互改进已替换此防抖调度。

生成的派生示例：
- `processed/examples/baseline.png`、`baseline.npz`
- `processed/examples/training_seed42.png`、`training_seed42.npz`

PNG 仅显示；NPZ 含完整线性数据、能量/纵向坐标、模型配置/版本及适用的题目标签。没有真实测量数据或神经网络训练。

### 4. 语法、格式和工作区

实际执行并通过：

```bash
python3 -m compileall -q src run.py tests
node --check src/eels_sim/web/app.js
node --check tests/browser_smoke.mjs
```

还对 15 个新增源码/测试/入口文本文件检查了行尾空白与末尾换行，通过；针对本次跟踪文件的 `git diff --check -- .gitignore README.md docs/requirements.md docs/validation.md docs/decisions` 通过。

全工作区 `git diff --check` **未通过**：报告先前已有的 `logs/project.log:5: new blank line at EOF`。该文件在开工前已是人工修改状态，本次未改它或暂存区，未擅自清理这一无关差异。

## 本次交付路径与回退

- 新建：`run.py`、`requirements.txt`；`src/eels_sim/{__init__,model,legacy,training,presentation,server}.py`；`src/eels_sim/web/{index.html,style.css,app.js}`；`tests/{test_model.py,test_server.py,browser_smoke.mjs,offline_report.py}`；`docs/decisions/0001-effective-model-and-local-ui.md`。
- 更新：`.gitignore`、`README.md`、`docs/requirements.md`、`docs/validation.md`；通过 research-plan 维护 `PLAN.md`。
- 派生：上列 `processed/examples/`、`processed/validation/` 文件；由 `.gitignore` 排除。Python 自动缓存亦已忽略。
- 未改：raw 原件、AGENTS、原有管理日志、系统/仪器配置；未进行 Git 提交或暂存操作。
- 回退：停止 `run.py` 即停止新应用；原件与 `legacy.py` 默认数值路径仍在，没有替换标定、原始配置或部署系统服务。

## 限制与待用户验收

1. 请在 Windows 浏览器打开 `http://localhost:8765`，实际验证 WSL2 转发、屏幕尺寸、操作手感和下载位置。
2. 8 meV 是有效总能量响应，不是从数据确定的 Cc。真实能角色差耦合、有限源/能量选择狭缝主模型、完整设备传递、衍射、校正器耦合和实验拟合延期；仅 legacy 保存原能量狭缝默认算法。
3. 视野改变也改变能量像素尺寸；已验证默认零系数的上述组合，不代表所有极端叠加、所有噪声强度或任意配置均有同样宽度精度。强裁切/低计数会明确不给有效 FWHM；低于半高的长尾还需观察 RMS/形状。
4. 九参数逆问题存在等价解。仅有本合成模型生成的标签，未训练网络、未验证仿真到实测迁移。
5. 这是可信本地使用的标准库服务，不做公网安全或多用户并发生产服务承诺。没有硬件接入/验收。

## 交互改进：拖动更新与滚轮微调（2026-09-12）

### 用户反馈与改动范围

用户反馈总体可用，并要求拖动中实时更新，以及双击某项后用可设步长的滚轮调节。本轮只改前端、浏览器测试与软件说明，不改物理模型、采样档位、Dij 约定、原始文件或后端接口；没有安装依赖、操作硬件、提交或重启用户自己的运行服务。

实际修改：
- `src/eels_sim/web/app.js`：去掉 90 ms 尾随防抖，用浏览器动画帧合并输入、单请求流水更新。可显示同上下文内已完成的中间帧，但不覆盖较新的控件值；题目/模式/场景/显式操作变化后拒绝旧上下文帧。最终参数追上后才允许导出。
- `src/eels_sim/web/index.html`、`style.css`：交互说明、选中行高亮和每行独立步长。默认 0.1，最小/精度 0.01，最大 120；整数百分单位累加，避免浮点累积误差；结果限制在 ±120。只拦截启用行参数区的垂直滚轮，不拦截 Ctrl/Meta+滚轮或全页面滚动。
- `tests/browser_smoke.mjs`：增加持续拖动、慢响应、滚轮与退出行为回归，并支持显式派生输出目录；保留旧版验证截图。
- `README.md`、`docs/requirements.md`、本文件：操作说明、验收条件与实际结果。

### 先复现再修复

1. 在旧前端上运行新增的持续拖动测试：按住鼠标，连续发出 36 次移动事件，每次间隔 15 ms（另有协议耗时），并将每个帧响应在浏览器端额外延迟 80 ms。断言失败：**松手前显示的中间帧为 0**。原逻辑既反复推迟请求，又会丢弃输入已变化时返回的帧，确实存在持续拖动无更新的问题；旧测试只检查松手后的最终值，没有覆盖此行为。
2. 加入滚轮交互后的第一轮浏览器测试失败：双击 D01 实际选中 D20。原因是 pointerdown 取消旧选中行时折叠了步长区，后续点击坐标下方的参数发生移动。改为所有步长区常驻且保持行高，启用/关闭只改变状态和高亮，不折叠行。随后完整复测通过。

### 最终实际检查

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check src/eels_sim/web/app.js
node --check tests/browser_smoke.mjs
node tests/browser_smoke.mjs /home/agent/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome processed/validation/interaction-v2
```

- **24 项 Python 单元/HTTP 测试通过，1.560 s**；两项 Node 语法检查通过。
- **Chromium 149.0.7827.55 实际浏览器检查 PASS**。在上述额外 80 ms 延迟条件下，松手前显示 **6 帧**，有多个不同参数值且 FWHM 随之变化；最大在途帧请求为 1，控件不回退，停止后最终帧与最终控件一致。这是测试情景结果，不是正常运行的固定帧率或端到端延迟承诺。
- 慢帧在途时切换自由/练习模式，不把旧模式图像绘入新模式。
- 实际双击/滚轮测试：默认步长 0.1、修改为 0.25、方向反转、步长逐行保留、只启用一行、非法步长（0、负值、空值、精度不符）拒绝、±120 边界限制、未启用的聚焦数值框不被浏览器原生滚轮误改且页面仍滚动、启用时页面不随该滚轮滚动。
- 退出方式验证：再次双击、Escape、行外指针点击、窗口失焦；另检查 Ctrl+滚轮事件不被拦截。
- 原有自由叠加、灰度不改谱、隐藏/揭示答案、精确补偿、重试/新题、窄屏无横向溢出检查继续通过；没有捕获到 JS 异常或页面对外请求。基线仍显示 **8.002 meV**。

新增派生路径（未覆盖首版记录）：
- `processed/validation/interaction-v2/unit-http-tests.txt`
- `processed/validation/interaction-v2/browser-test.json`
- `processed/validation/interaction-v2/browser-desktop.png`
- `processed/validation/interaction-v2/browser-narrow.png`

已读取检查桌面与窄屏截图。测试创建的临时本地服务和 Chromium 已停止；用户自己的服务未停止。若服务仍运行，强制刷新网页即可加载新的静态前端，无需重启后端。实际 Windows 鼠标/触控板事件频率和操作手感仍需用户试用；每个有效滚轮事件对应一步，触控板较敏感时可减小步长。

## 交互改进：按钮启用、全页滚轮与 Esc 撤销（2026-09-12）

本节为当前滚轮行为，取代上一节的“双击启用、仅行内生效、Esc 只退出”；上一节记录保留为历史证据。用户要求改为按钮启用，启用后滚轮只调整选中量、不翻页，左键结束，Esc 回到本次调整前的状态。

### 实现与边界

- 每行“滚轮调节”按钮启动一次调整，记录当前九项系数快照；高亮及浮动提示指明正在调哪一项。仍保留逐行步长；不再双击启用。
- 在 document 捕获全页滚轮，包括光斑、其他系数框和步长框上的事件；只改变选中系数，并阻止默认页面/输入框滚动。水平与 Ctrl/Meta 修饰滚轮不调系数，也不滚动/缩放。未启用时恢复正常滚动。
- 下一次页面左键点击保留本次结果并停止，消费停止用的 pointerdown/pointerup/click，避免顺带触发归零、换题或再次进入同一/另一项。
- Esc 恢复本次启用时的系数快照并刷新同源图谱/指标/残差，不是清零或撤销先前已经确认的调整。撤销推进请求上下文版本，使在途旧帧失效。步长不是物理系数快照的一部分。
- 窗口失焦或显式模式/场景操作保留当前值并结束捕获，防止跨上下文恢复；这不是系统级鼠标钩子，不捕获浏览器页面以外的事件。

### 实际检查

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check src/eels_sim/web/app.js
node --check tests/browser_smoke.mjs
node tests/browser_smoke.mjs /home/agent/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome processed/validation/interaction-v3
```

- 最终 **24 项 Python 单元/HTTP 测试通过，1.600 s**；两项 Node 语法检查通过。本轮未遇到测试失败。
- 实际 Chromium 149.0.7827.55 检查 **PASS**：按钮启用不会被自身的点击立即结束；双击数值不启用；实际滚轮在光斑、其他系数和步长框上都只改变选中项，不滚页、不触发原生数值框增减。保留步长、方向、非法输入和边界检查。
- 左键点“全部归零”只确认并停止，不误触归零；点另一项启用按钮时第一次只停止当前会话，第二次才启用新项；点击当前按钮停止后不重新启用。
- 非零起点验证：D10=7.5、D01=2.25，滚轮三步后左键确认 D10=7.8；再次启用、调整后 Esc 恢复 **7.8 而不是 7.5 或 0**。对比恢复前后的系数、PNG、谱线和指标完全一致。
- 对响应额外延迟 80 ms，调节帧在途时 Esc 撤销，验证晚到帧不覆盖恢复结果；练习模式撤销后题目、答案显示状态和残差完全恢复。Ctrl/水平滚轮捕获分支用浏览器内合成 WheelEvent 验证；普通左键及滚轮使用实际 DevTools 输入事件。
- 既有持续拖动检查仍在松手前显示 6 帧（测试额外延迟条件），最大在途帧请求为 1；其余叠加、随机练习、精确补偿、窄屏布局检查继续通过。没有捕获到 JS 异常或页面对外请求；基线仍为 **8.002 meV**。

本轮实际修改 7 个文件：`src/eels_sim/web/{app.js,index.html,style.css}`、`tests/browser_smoke.mjs`、`README.md`、`docs/requirements.md`、本文件。派生结果独立保存在 `processed/validation/interaction-v3/{unit-http-tests.txt,browser-test.json,browser-desktop.png,browser-narrow.png}`，未覆盖 v2 记录；已读取检查桌面及窄屏截图。

物理模型、后端、原始文件、依赖和用户运行服务未改；没有安装、提交或硬件操作。测试创建的临时服务和浏览器结束后停止。正在运行的页面可强制刷新加载新前端，Windows 实体鼠标/触控板的手感仍待用户试用。

## 布局改进：九项与图谱同屏（2026-09-12）

用户要求避免调整下面的系数时看不到画面。本轮只更改浏览器布局、显示重绘及相应测试/说明，保留九项、滚轮确认/撤销和模拟模型。

### 实现

- 模式与出题设置移至顶部紧凑工具条。桌面左侧为九项单行控件，右侧并排显示光斑和能谱及三项指标；较矮桌面进一步缩小行间距。
- 答案、场景设置、显示诊断/导出及模型说明放在调节区之后，不把下方参数挤离画面。导出按钮现位于“显示说明、诊断与导出”折叠区。
- ≤1100 CSS 像素宽度改为上图下控，参数为三列/两列网格；图谱在参数区域滚动期间吸附于页头下方。窄屏允许滚动参数，不声称任意小窗口能同时容纳九项。
- 活动滚轮提示移至顶部，避免覆盖最低一行或能谱。Canvas 按容器大小和 devicePixelRatio 重绘最近完成帧，轴文字不再随固定 800×550 位图一起缩小；不重新模拟，不改原始图谱、FWHM、系数或 PNG/NPZ 导出数据。显示纵横比例仍非探测器几何标定。

### 复现与修正

1. 修改布局之前运行新增可见性断言，在 **1366×768** 自由模式失败：D02、D30、D21、D12、D03 的滑块、数值、滚轮按钮和步长不在可见视口内。输出保留在 `before-layout.txt`。
2. 新布局首次完整回归在 **1280×600** 练习模式失败：D03 仍超出底边。为标签/输入设置明确行高，并对较矮桌面减小行间距后通过，未取消该尺寸检查。
3. 增加整行外框及提示遮挡检查后，390×844 的 `scrollIntoView` 将整行底边放在 **844.296875 px**（滚动偏移取整而网格盒保留小数）。诊断保留在 `layout-boundary-check.txt`。测试仅对整行外框允许 0.5 CSS 像素边界误差；实际输入、按钮、画布的视口检查与遮挡检查保持严格。

### 最终实际检查

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check src/eels_sim/web/app.js
node --check tests/browser_smoke.mjs
node tests/browser_smoke.mjs /home/agent/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome processed/validation/layout-v1
git diff --check
```

- **24 项 Python 单元/HTTP 测试通过，1.577 s**；两项 Node 语法检查及差异空白检查通过。两份 raw 原件 SHA256 与原始基线一致。
- **Chromium 149.0.7827.55 浏览器回归 PASS**。1920×1080、1600×900、1366×768、1280×660、1280×600 视口中，在练习模式、揭示答案且展开场景/导出设置后，九项完整控件、两幅图和 FWHM 均可见且无覆盖/横向溢出。证据为视口截图，不是整页长截图。
- 在 **1280×600** 实际启用最后一项 D03，鼠标位于光斑上滚动后 D03=0.1，页面滚动量保持 0，九项与图谱仍可见；Esc 恢复本次起点。
- **1024×768、720×720、390×844**：将完整 D03 行滚入视口后两幅图及 FWHM 仍可见，实际滚轮调节与 Esc 回退通过；顶部会话提示不遮挡画布或该行。
- 连续变更视口尺寸及一次 2× 像素密度检查：画布缓冲尺寸跟随显示尺寸，重绘有内容，不新增 `/api/frame` 请求，系数、原始 PNG、谱线和指标不变。
- 原有连续拖动、慢响应、全页滚轮、左键不穿透、Esc 快照/迟到帧、练习答案/精确补偿等检查继续通过。本次额外 80 ms 延迟测试仍在松手前显示 **6 帧**，最大在途模拟请求为 1；基线仍为 **8.002 meV**，无捕获到的 JS 异常或页面对外请求。

实际修改：`src/eels_sim/web/{index.html,style.css,app.js}`、`tests/browser_smoke.mjs`、`README.md`、`docs/requirements.md`、本文件，共 7 个文件。

本轮派生结果目录：`processed/validation/layout-v1/`，包含 `before-layout.txt`、`layout-boundary-check.txt`、`unit-http-tests.txt`、`browser-test.json`、`browser-desktop.png`、`browser-narrow.png`，以及七张 `layout-宽x高.png` 视口截图。已读取检查桌面、小桌面、1024 宽及 390 宽截图；旧版验证目录未覆盖。

测试临时启动的本地服务和 Chromium 结束后停止；没有安装依赖、改动后端/原件、提交或操作用户服务/硬件。若用户服务仍运行，强制刷新页面即可加载新布局，无需重启后端。实际 Windows 浏览器缩放、字体差异及鼠标手感仍待用户试用；上述尺寸是浏览器内容视口的 CSS 像素，不是显示器标称分辨率。

## 四/五阶、参数分页与练习最高阶（2026-09-13）

用户要求加入可选择的四/五阶项、翻页时仍可观察图像，并能选择练习的最高阶。本节是当前扩展记录；前面各轮的九项行为及验证结果保留为历史记录。

### 实现及兼容边界

- `eels-effective-1.1` 按原无阶乘单项式约定扩为 20 项：四阶 `D40,D31,D22,D13,D04`，五阶 `D50,D41,D32,D23,D14,D05`。高阶默认零；不改变 8 meV 有效响应、卷积、采样、计数定义、测宽或 legacy。
- 自由探索三页为一～三阶 9 项、四阶 5 项、五阶 6 项；所有页共同叠加，分页不模拟、不清零，不丢步长或在途帧。全部归零覆盖所有页；滚轮左键确认/Esc 快照扩展到完整系数，点击页签的第一次停止点击不穿透。
- 练习最高 1～5 阶，默认 3；候选数为 2/5/9/14/20，按设定项数抽取。最高阶仅为上限，不保证稀疏题一定有最高阶非零项。选择器在新题时生效，重试/更新仍用当前题阶数；越阶非零补偿在服务端拒绝。答案表显示本题全部候选项，评分分母随本题候选数而非页码变化。
- 原九项输入和别名兼容，但完整系数字典/`TERMS` 已变为 20 项。NPZ 保存规范 `terms`、`powers`、无阶乘约定及练习 `max_order`/`eligible_terms`，供后续数据对齐。此处仅扩展模拟和导出接口，没有训练神经网络；数学扩展不是仪器高阶标定。理由见 `docs/decisions/0002-higher-orders-and-parameter-pages.md`。

### 实际检查

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check src/eels_sim/web/app.js
node --check tests/browser_smoke.mjs
node tests/browser_smoke.mjs /home/agent/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome processed/validation/orders-v1
git diff --check
sha256sum raw/20260912/*
```

- 最终 **30 项 Python 单元/HTTP 测试通过，2.646 s**；两项 Node 语法检查通过。新增 11 个单项式的独立公式及跨阶叠加、每个高阶项实际改变图像、计数守恒、孔径奇偶等价、裁切告警、全阶域出题/补偿/归一化评分、越阶/非法输入、当前题状态保护及完整 NPZ 元数据检查。新 HTTP 元数据、四阶 14 项出题/揭示及既有同源/路径限制通过。
- **修改之前**将当前零像差与默认种子 42 三阶题的计数数组及题目标签保存至 `before-regression.npz`。修改后用 `np.testing.assert_array_equal` 对比两份计数数组，均逐元素完全相同；原九项题目标签不变，仅补上 11 个高阶零值。基线 FWHM 仍为 **8.002032171109645 meV**；对比输出为 `numerical-regression.txt`。两份 raw 原件哈希与此前基线一致。
- **Chromium 149.0.7827.55 实际浏览器 PASS**。默认页仍有九项可见；四阶页/五阶页各显示准确的 5/6 个控件。跨页调节 D01、D40、D22、D04、D05 后，隐藏页数值仍在同一帧；仅翻页不产生 `/api/frame` 请求，图谱、指标和系数不变；高阶帧在途时切页不会回退系数。
- 五阶滚轮：D05=8，步长 0.25，上滚后 8.25，点四阶页签只确认停止，再点才换页；返回五阶后步长保留。下一次滚轮调整后 Esc 精确恢复 8.25 及其他页系数、图像、谱线和指标。全部归零恢复所有 20 项及基线。
- 练习 1/2/3/4/5 阶分别抽取全部 2/5/9/14/20 项，浏览器揭示行数、越阶零值/禁用状态、精确补偿到基线和重试复原通过。最高阶草稿不改变当前五阶题或可用页，重试保持原阶数；新题才应用一阶设置。页签圆点不显示隐藏初始项。
- 默认九项页继续通过 1920×1080、1600×900、1366×768、1280×660、1280×600 的同屏检查及原窄屏/2× 像素密度检查。四/五阶页分别在 **1280×600、1024×768、390×844** 检查所有行、滑块、数值、步长、滚轮按钮及光斑、能谱、FWHM 无遮挡/横向溢出；实际启用 D04/D05 并在图上滚轮调节，画面和参数始终可见，不随滚轮翻页，Esc 恢复通过。已读取检查四阶、五阶桌面及五阶窄屏截图，证据为视口图而非整页长截图。
- 原有拖动/慢响应/模式边界/左键不穿透/Esc 迟到帧/亮度不改谱线检查全部继续通过。本次额外 80 ms 响应延迟下松手前仍显示 **6 帧**，最多一个模拟请求在途；未捕获 JS 异常或页面对外请求。
- 浏览器内模拟缺少新字段的旧版 `/api/meta`，验证明确显示重启 `python3 run.py` 的提示，且不继续发送不兼容的帧请求。这是兼容分支测试，没有操作用户旧服务。
- 本轮实施后的首轮及最终回归均通过，未遇到测试失败。差异空白检查通过。

### 保存路径与未验证项

修改 13 个现有文件：`src/eels_sim/{__init__,model,training,server}.py`、`src/eels_sim/web/{app.js,index.html,style.css}`、`tests/{test_model.py,test_server.py,browser_smoke.mjs}`、`README.md`、`docs/requirements.md`、本文件；新增 `docs/decisions/0002-higher-orders-and-parameter-pages.md`。

派生证据独立保存在 **`processed/validation/orders-v1/`**：修改前 `before-regression.npz`、`numerical-regression.txt`、`unit-http-tests.txt`、首轮 `browser-run.txt`、最终 `browser-test.json`、默认页 `browser-desktop.png` / `browser-narrow.png` / `layout-*.png`，以及 `browser-order-4.png`、`browser-order-5.png`、`order-{4,5}-{1024x768,390x844}.png`。未覆盖旧轮验证目录或原始资料。

本轮确实改动了后端，**需要用户自行在原终端停止并重新运行程序，再 Ctrl+F5**，不能只刷新。需保留当前会话时先导出；重启会重建会话。没有停止/重启用户服务、安装依赖、提交、部署或仪器操作；只临时启动/停止测试自己的本地服务和浏览器。Windows 实体鼠标/触控板、浏览器缩放及仪器准确性仍未验收。上述证据为离线合成模型与 Linux Chromium 检查，不是硬件接受测试。

## 单项难度：取消总位移预算摊薄（2026-09-13）

### 问题、实现及兼容

用户反馈二十项练习偏离很小，要求若难度按总偏移则换方案。检查 `src/eels_sim/training.py` 确认：原算法按各项绝对位移上界之和，给整组系数施加视野预算缩放；默认场景中级总预算为 48，项数越多，每项越小。它是保守上界，不是实际图像总位移或评分。

现在每个抽中项独立保留原始幅度分布：初级绝对系数 7–20、中级 15.75–45、高级 31.5–90，随机正负、两位小数，不按项数/视野/孔径/展宽统一压缩。全部答案仍可在 ±120 内精确补偿。保留原评分公式、前向模型 `eels-effective-1.1` 和裁切判据；前端标注“单项难度”，超出视野时提示手动扩大视野而不改题目。

新增独立 `generator_version=eels-exercise-per-term-1`，进入 `/api/meta`、公开题目、揭示反馈及 NPZ 标签。旧种子的题目数值有意改变（含三阶九项），旧导出应读实际标签，不能仅凭种子用新版还原。前端检查出题版本，拒绝仍用总预算的旧后端并提示重启。实现取舍见 `docs/decisions/0003-per-term-exercise-strength.md`；这取代前文历史记录中的总预算和旧种子兼容承诺。

### 实测对比（离线合成模型，不是实验结果）

固定题目种子 42、默认场景、零补偿，修改前后实际调用出题器和 `simulate`：

| 题目 | 平均绝对系数：前 → 后 | 谱线 RMS / meV：前 → 后 |
|---|---:|---:|
| 九项中级 | 5.3344 → 31.6222 | 6.7296 → 34.6006 |
| 二十项初级 | 1.1995 → 14.0045 | 3.6130 → 14.6945 |
| 二十项中级 | 2.3995 → 31.5085 | 4.1902 → 32.3442 |

二十项中级系数绝对值范围由 1.30–3.19 变为 17.03–41.87，FWHM 为 28.4587 meV，默认视野裁切比例约 2.8×10⁻¹³。二十项高级默认视野裁切约 **9.286%**，正确不报告有效 FWHM；其裁切后的 RMS 不能当完整谱线宽度。窄视野测试使用 4096 光线，±40 meV 时裁切约 48.239%，扩大到 ±240 meV 后该样例裁切为 0、答案不变。不能据此保证任意种子/场景在 ±240 或 ±480 下都无裁切。

零像差完整测量字典与修改前保存值相同，FWHM 仍为 **8.002032171109645 meV**。上述九项/二十项的三档共六题，精确补偿后计数数组均与默认零像差基线逐元素相等。该比较是软件回归，不证明每个高阶项都有相同的可视影响。

### 实际检查

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check src/eels_sim/web/app.js
node --check tests/browser_smoke.mjs
node tests/browser_smoke.mjs /home/agent/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome processed/validation/difficulty-v1
git diff --check
sha256sum raw/20260912/*
```

- 修改前 **30 项 Python 单元/HTTP 测试通过（2.416 s）**；修改后 **33 项通过（3.033 s）**。逐项幅度测试覆盖种子 0…15、最高阶 1…5、每个阶域所有合法项数和三档难度，共 2400 组；验证非零项数、幅度上下限、同题跨难度的支持集/符号保留和幅度递增。
- 额外覆盖：场景与采样改变不缩放标签、创建场景如实记录、二十项中级可见宽度回归、强题窄视野告警/无效 FWHM/扩大视野、答案可达、全阶评分分母及精确补偿、出题版本的 HTTP 与无 pickle NPZ 标签。旧“所有题初始无裁切”断言按新规则替换为系数上界和明确裁切处理测试，不再承诺初始无裁切。
- 两项 Node 语法检查通过；**Chromium 149.0.7827.55 实际浏览器回归 PASS**。新增检查二十项三档的每项幅度、种子 42 中级谱线 RMS >20、裁切扩大视野提示、改变视野不改题目/答案/评分，以及二十项旧总预算后端的重启提示。
- 原九项桌面及窄屏布局、四/五阶分页与跨页叠加、全阶题目/重试/精确补偿、滚轮事务/迟到帧、连续拖动及显示不改数据继续通过；额外响应延迟下松手前显示 6 帧，最多一个模拟请求在途。无捕获 JS 异常或页面对外请求。已读取检查二十项中级截图及带裁切提示的 1280×600 九项截图。
- 本轮首轮单元/HTTP 及首轮、最终浏览器检查均通过，没有测试失败。差异空白检查通过。`raw/`、前向模型和 legacy 未改；原件哈希与先前记录一致。

### 保存路径和未验证项

修改：`src/eels_sim/{training,server}.py`、`src/eels_sim/web/{app.js,index.html}`、`tests/{test_model.py,test_server.py,browser_smoke.mjs}`、`README.md`、`docs/requirements.md`、本文件；两个既有决定文件仅增加后续替代规则的链接。新增：`docs/decisions/0003-per-term-exercise-strength.md`。

证据独立保存在 **`processed/validation/difficulty-v1/`**：`training-before.py`（修改前源码）、`before.json`、`after.json`（实际题目/场景/测量）、`comparison.txt`、`before-tests.txt`、`unit-http-tests.txt`、`browser-run.txt`、`browser-final.json`，以及 `difficulty-medium-20.png`、`browser-*.png`、`layout-*.png`、`order-*.png`。未覆盖旧轮验证目录和原件；未改 `PLAN.md` 或管理日志。

没有安装依赖、导入外部源码、停止用户服务、提交、部署或仪器操作。只临时启动/关闭测试自己的回环服务和浏览器。用户需先按需导出当前会话，再自行停止并重新运行 `python3 run.py`、浏览器 Ctrl+F5 并重新出题。Windows→WSL2、用户主观练习难度及仪器准确性仍未验收；高阶弱可见性和正负抵消仍存在，不保证任意场景的视觉难度。

## 截图风格、显示顺序与键盘滚轮会话（2026-09-14）

### 参考与实施边界

- 实际读取 `raw/20260914/Screenshot 2026-09-14 1641482.png`、`Screenshot 2026-09-14 1642163.png`。观察：粉色 TuneUp 为 D10、D01、D02、D20、D11；另一张表的二阶顺序为 E20、E02、E11，与之不一致。实现取舍：以前者作为低阶排序及全界面视觉主参考，三阶/四阶/五阶接续后者的幂次顺序。此取舍已向用户说明，不声称两图完全同序。
- 参数、键盘遍历和答案表显示顺序统一为 `D10,D01,D02,D20,D11,D30,D21,D12,D03 / D40,D31,D22,D13,D04 / D50,D41,D32,D23,D14,D05`；前五项显示 FX/FY/C/D/SY 标签。保留 9/5/6 分页及所有 20 项，不添加截图中的其他仪器控制量，不更改 meV 单位、范围、前向模型、API/NPZ 规范项序或种子对应系数。按项名映射幂次，避免重排后错配 D02/D20。
- 全部应用面板统一为粉底、黑色分组线、白底蓝字输入/指标及方形灰按钮；行末灰底白色 ↔，黑底白信号图谱不变。桌面仍左控右图，窄屏改为更紧凑的单行控件，图谱吸附于上方。
- 正常 ↑↓ 选择而不改系数；单击行/↔ 只选择；双击 ↔ 或 Enter 开始。活动中 ↑ 步长 ×10、↓ ÷10，限制 0.01～120，按 0.01 精度取整，不改物理量或发起模拟。Enter/左键单击确认，Esc 撤销本次开始时的全系数快照及图谱，步长保留。长按 Enter 和用于确认的双击不能误开新会话；确认点击不穿透。各页记住选择，翻页后焦点回到当前参数，缩减练习阶域不会选择隐藏/禁用项。
- 正常场景/出题输入保持原生键盘操作；活动中暂时拦截 Tab，结束后恢复。保留全页滚轮、单在途请求、迟到帧撤销保护、失焦安全结束及跨页叠加。

### 实际检查

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check src/eels_sim/web/app.js
node --check tests/browser_smoke.mjs
node tests/browser_smoke.mjs /home/agent/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome processed/validation/reference-ui-v1
git diff --check
sha256sum raw/20260914/* raw/20260912/*
```

- **33 项 Python 单元/HTTP 测试全部通过，3.158 s**；两项 Node 语法检查通过。补写本节后空白检查曾发现本文件末尾多余空行，去掉后最终 `git diff --check` 通过。后端未改，既有幂次/别名、固定种子、基线、导出标签及精确补偿回归继续通过。
- **两轮 Chromium 149.0.7827.55 实际浏览器回归均 PASS**，没有测试失败。首轮后代码复查补上翻页后的键盘焦点，并将窄屏断言从“末行可见”加强为“当前页全部参数可见”，再完整复测。测试编辑曾因一处重复文本匹配被工具拒绝，修正定位后完成，未部分改写文件。
- 新增真实 DevTools 键盘/双击检查：九项按显示序遍历；聚焦数值/滑块/步长框时 ↑↓ 不触发原生系数增减；页边界停住；四/五阶翻页后可立即键盘选择，一阶题不能选到禁用项。正常选择及步长变更不发起模拟，系数不变。默认步长 0.1 经 ↑ 到 1、↓ 回 0.1，连续按键分别限制于 0.01/120；Enter 确认后 Esc 不撤销已确认值，新会话 Esc 恢复新起点。场景噪声种子输入保留原生 ↑，其 Enter 不误开会话。
- 自动检查全部 20 个 DOM 参数名顺序、D02/D20/D11 幂次标签、全部面板粉底及白底蓝字输入、灰按钮 ↔；最高 1～5 阶的答案表分别按同一显示序显示 2/5/9/14/20 行。完整主题的细节另通过读取截图检查，不把颜色断言当成逐像素复刻证明。
- **1920×1080、1600×900、1366×768、1280×660、1280×600**：练习、揭示答案及展开场景/导出后，九项完整控件、两幅图、FWHM 仍在同一视口。**1024×768、720×720、390×844**：滚入调节区后，同样断言当前九项全部控件及图谱无遮挡；活动末行时 ↑↓ 只改其步长，滚轮不翻页。四/五阶桌面及窄屏所有当前项也通过同屏检查。截图为视口截图，不是整页长图。
- 既有慢响应拖动、全页滚轮、单击不穿透、Esc 恢复图谱/残差及迟到帧保护、分页不模拟、跨页系数/步长保留、全阶练习及精确补偿继续通过。额外 80 ms 响应延迟测试中松手前显示 **6 帧**，最多 1 个请求在途；基线为 **8.002 meV**。未捕获 JS 异常或应用外部网络请求。
- 已实际读取检查最终桌面九项、五阶及 390 宽九项/五阶截图。两个新截图 SHA256 前后相同：`1641482` 为 `2fef64eef1ba422b5fa2f3d5d8e77142c64208d37facc4dc2085cdef9735ced5`，`1642163` 为 `1376e20b8ba1f2bae82bd1eb14af79c5a0a53d2d03f0ade26352debb91ef8586`；20260912 原件哈希亦与既有基线相同。

### 保存路径、更新与限制

- 修改 7 个文件：`src/eels_sim/web/{app.js,index.html,style.css}`、`tests/browser_smoke.mjs`、`README.md`、`docs/requirements.md`、本文件。
- 证据保存至 `processed/validation/reference-ui-v1/`：`unit-http-tests.txt`、`browser-first.json`、`browser-final.json`、`browser-desktop.png`、`browser-narrow.png`、`browser-order-{4,5}.png`、`layout-*.png`、`order-*.png`、`difficulty-medium-20.png`。未覆盖前几轮验证目录。
- 未改 raw、模型/后端、依赖、PLAN 或原先已有修改的 `logs/project.log`；无安装、外部源码导入、提交、部署或仪器操作。测试临时启动的回环服务/浏览器均已停止，未操作用户服务。
- 已运行当前后端的用户先按需导出会话，再 **Ctrl+F5** 加载新前端，无需重启。只在页面提示旧后端不兼容时需自行重启后端。刷新会重建浏览器会话。
- Windows→WSL2 转发、真实鼠标/触控板手感、字体与缩放、不同系统双击阈值仍待用户实际验收；步长 ×10/÷10 是本轮交互实现选择，不是设备 API 或已验证仪器惯例。不保证任意更小视口全部同屏；没有硬件连接、控制或安全验收。

## 恢复原有深色配色（2026-09-14）

用户明确要求配色继续用原来的方案。本轮以 Git HEAD 中改动前的 CSS 色值为依据，仅恢复深色背景、面板、输入框、浅色文字、灰色按钮及警告/错误颜色；保留新的字号、尺寸、排列、参数顺序和全部键盘/滚轮交互。未改 `app.js`、`index.html` 或模型/后端。

实际修改：`src/eels_sim/web/style.css`、`tests/browser_smoke.mjs`、`README.md`、`docs/requirements.md`、本文件。测试颜色断言改为原有深色方案，覆盖所有面板、页面背景、输入文字/背景及警告/错误色。

实际执行两项 Node 语法检查和完整浏览器回归：

```bash
node --check src/eels_sim/web/app.js
node --check tests/browser_smoke.mjs
node tests/browser_smoke.mjs /home/agent/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome processed/validation/dark-palette-v1
git diff --check
```

均通过，无本轮测试失败。Chromium 149.0.7827.55：原有桌面/窄屏全参数与图谱同屏、参数顺序、上下键选择/步长、Enter/双击启用、确认/撤销、分页及慢响应回归继续 PASS；基线 8.002 meV，额外延迟拖动测试松手前显示 5 帧。未捕获 JS 异常或应用外部请求。本轮没有重新运行 Python 单元测试（未改 Python）。

结果与视口截图独立保存至 `processed/validation/dark-palette-v1/`，汇总为 `browser-test.json`；已读取检查 `browser-desktop.png`、`browser-narrow.png`。未覆盖上一轮粉色截图证据。测试临时服务/浏览器已停止；未操作用户服务、raw、PLAN、原有管理日志、依赖或仪器，也未提交/部署。Windows 实际显示与手感仍待用户验收。先按需导出当前会话，再 Ctrl+F5 加载配色，无需重启后端。

## 滚轮模式左右键单步调整（2026-09-14）

用户新增要求按键左右单步移动；本轮实现为键盘 ← 减少当前步长、→ 增加当前步长，仅在滚轮会话内生效。每个 keydown 一步，支持系统长按重复；修饰键组合不调系数。与滚轮共用 `nudgeCoefficient()`，统一步长校验、整数百分单位累计、±120 限幅和实时帧调度。上下键改步长、Enter/单击确认、Esc 撤销、参数顺序及深色配色不变。

修改：`src/eels_sim/web/{app.js,index.html}`、`tests/browser_smoke.mjs`、`README.md`、`docs/requirements.md`、本文件。未改 CSS、模型/后端、raw、PLAN 或既有管理日志。

实际执行并通过：

```bash
node --check src/eels_sim/web/app.js
node --check tests/browser_smoke.mjs
node tests/browser_smoke.mjs /home/agent/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome processed/validation/arrow-nudge-v1
git diff --check
```

- Chromium 149.0.7827.55 完整浏览器回归 **PASS**，本轮无测试失败。新增真实键盘输入验证：默认 0.1 左右互逆、上下键改变步长后立即采用新步长、自定 0.25 与滚轮混用、仅改变活动项且不滚页、数值/滑块/最终帧同步、正常模式不新增全局单步快捷键。
- 新增 ±120 限幅、0.01 最小步长及重复键事件、四种非法步长、Ctrl/Meta/Alt/Shift 修饰键、Enter 与单击确认、非零起点 Esc 精确恢复图谱，以及按键帧延迟到达不能覆盖撤销的检查。高阶跨页系数保留、练习答案/残差恢复及窄屏末行左右键操作继续通过。
- 既有桌面/窄屏全部当前项与两幅图/FWHM 同屏、深色配色、连续拖动与全页滚轮回归通过；未捕获 JS 异常或应用外部请求。基线 8.002 meV，额外延迟拖动测试松手前 6 帧。未重新运行 Python 单元测试（未改 Python）。
- 结果及视口截图保存至 `processed/validation/arrow-nudge-v1/`，汇总为 `browser-test.json`；已读取检查桌面及 390 宽截图，未覆盖旧验证目录。

测试临时回环服务/浏览器已停止；未操作用户服务、安装依赖、提交、部署或连接仪器。先按需导出当前会话，再 Ctrl+F5 加载，无需重启后端。Windows 实际按键/长按手感与 WSL2 转发仍待用户验收。
