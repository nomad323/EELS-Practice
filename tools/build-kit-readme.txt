EELS Windows 打包材料（源码，不是可直接运行的 Windows 成品）

此材料包不含 exe/Python/浏览器，也不含原始资料、截图、Git 历史或开发环境。
用途：在 Windows x64 构建轻量便携软件。推荐已有官方 Python 3.12 x64。

解压到新的本地目录，在此目录打开 PowerShell。
以下包含依赖安装，请确认允许联网安装构建依赖后自行执行；脚本不会自动安装：

py -3.12 -m venv .venv-build-windows
.\.venv-build-windows\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv-build-windows\Scripts\python.exe tools\build_windows.py

不要复用或覆盖已有环境；若没有 py/Python，请先安排可信的 Python 安装。
不要在 WSL/Linux 构建 Windows exe。构建脚本只支持 Windows x64 + 独立 venv。

脚本先运行单元测试，再打包、运行生成 exe 的离线自检、收集许可并压缩。
本材料不含 raw 原件，因此原脚本对照测试会明确跳过；固定数值回归仍运行。
成品在 processed\releases\windows-时间戳\：
  EELS-Practice-windows-x64.zip
  EELS-Practice\EELS-Practice.exe（必须和 _internal 文件夹在一起）
  self-test.json、build-report.json（体积、版本、SHA256）
不覆盖旧输出；构建失败时不要把不完整文件夹作为成品分发。

使用端：解压整个成品 ZIP，双击 EELS-Practice.exe 自动打开默认浏览器；
关闭最后一个程序网页后约 5～10 秒退出。无需 Python、WSL 或 Node。
本软件不携带 Electron/Chromium，不自动安装、不自启、不连接仪器。
完整使用与限制见随包“使用说明.txt”（源文件 tools\portable-readme.txt）。

必须在目标 Windows 电脑人工验收：
- 默认浏览器自动打开，基线 FWHM 约 8 meV，分页与调节、PNG/NPZ 导出可用。
- 普通刷新不误关服务；多开两个程序标签，关一个继续运行，关完才退出进程。
- 不关闭其他浏览器标签；重复双击启动独立实例；程序退出后端口释放。
- 默认浏览器打不开/页面无连接时提示并退出，后台/休眠恢复按实际浏览器试用。
- 中文/空格路径可用，无管理员权限/系统 Python 环境的使用端也能运行。
- 核实签名/安全软件提示和文件来源，不要关闭安全软件来绕过。

本次只进行了 Linux/Chromium 源码验证；没有生成或验收 Windows exe。
离线自检通过不等于 Windows 默认浏览器行为、DLL 分发、杀毒信誉或硬件验收。
