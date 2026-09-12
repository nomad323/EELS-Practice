# 离线软件验证记录

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
