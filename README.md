# my-own-script

这个仓库目前包含两部分：

1) **代码工具箱（macOS）**：面向日常研发/运维的桌面工具（当前主要是 Azure DevOps Server 的“同步/构建/发布”一键执行器），支持 UI 配置、任务日志、Telegram 通知与指令控制、以及从 GitHub `main` 拉取更新后自动重启。
2) **ok-script**：基于图像识别的纯 Python 自动化测试框架（Windows/模拟器/ADB）。

---

# 代码工具箱（macOS）

## 功能概览

- Azure DevOps Server：
  - PAT（Keychain/keyring）安全存储
  - 支持项目/代码库配置
  - 任务：
    - 动态任务（支持新增/编辑/删除）
    - GitFlow 可配置：更新分支 / 合并规则 / 推送分支
    - 发布目标 targets：支持多目标串行执行，失败即停
  - Build：兼容 Pipelines 与 Build Definitions
  - Release：创建 Release、自动启动 notStarted 环境、监控选定 stages
  - PySide6 + Fluent 风格，任务卡片、实时日志、停止按钮（非回滚）
  - 任务配置状态锁定机制（防误触发：任务运行时会锁定编辑操作、置灰按钮并自动忽略页面刷新请求以保证任务可见度与日志正常记录）
  - 错误统一弹窗（可滚动详情）
- Telegram：
  - 通知：默认仅 **摘要**（开始/最终结果），可选开启“包含细节”（有泄露风险）
  - 控制：/help、/stop、/status、以及动态任务命令（含 ACL；通过 TG 触发时通知反馈给该触发者，通过程序界面触发时通知推送给 Owner）
- 更新：
  - 配置页提供 **检查更新** / **更新/重新安装**（基于 GitHub Releases：下载 DMG → 覆盖安装 → 重启）

## 技术栈

- Python 3.14（本机 venv）
- UI：PySide6、PySide6-Fluent-Widgets（qfluentwidgets）
- 网络：httpx
- 配置/模型：PyYAML、pydantic
- Secrets：keyring（macOS Keychain）
- 打包：wrapper `.app` + `.dmg`
  - 可发布到 GitHub Releases（用于应用内更新）

## 快速开始（本地开发）

对于习惯前端开发的工程师，你可以将 `bash dev_run.sh` 类比为 `npm install && npm run dev` 的组合体。它会自动处理虚拟环境创建、依赖安装和应用启动。

### 1. 环境准备

- **操作系统**: macOS
- **Python 环境**: 推荐使用 **Python 3.14** (本项目基于该版本开发，利用了最新的性能优化)。
- **Git**: 用于自动更新同步。

### 2. 一键运行指令

在终端中执行以下指令即可启动桌面端 UI 界面：

```bash
# 进入项目根目录
cd ~/my-own-script

# 执行启动脚本（自动完成依赖安装 + 运行）
bash dev_run.sh
```

### 3. 指令说明

- `dev_run.sh`: **核心启动脚本**。
  - 自动执行 `git pull` 同步最新代码。
  - 检查并创建 `.venv` Python 隔离环境（类似 `node_modules`）。
  - 根据系统类型（macOS/Windows）自动安装对应的依赖包（`requirements-mac.txt`）。
  - 最终启动 `app_main.py` 入口程序。
- `app_main.py`: 该项目的 **入口文件**。如果你已经手动调用过环境初始化，可以直接运行它。

### 4. 核心架构与逻辑

项目采用 **Python + PySide6** 构建，结合了 Telegram 远程控制。

- **UI 界面**:
  - **任务选项卡 (Tasks)**: 动态管理 (CRUD) 各种同步/发布流水线。
  - **配置选项卡 (Ado/Settings)**: 配置 ADO 组织 URL、项目名称、以及 Telegram Bot Token 等。
- **存储管理**:
  - **YAML 配置**: 所有的任务定义存储在 `tasks.yaml` 中。
  - **Keychain**: 敏感的 ADO PAT (Personal Access Token) 通过 macOS 系统级 Keychain 安全存储（不存明文）。
- **Telegram 控制 (tg_control.py)**:
  - 后台线程轮询：实时响应 `/help`, `/status`, `/stop` 命令。
  - 权限控制 (ACL): 仅限绑定的 Owner 或 ACL 组内的用户触发敏感任务。

### 5. 安全说明

本工具涉及 Azure DevOps 敏感 Token，相关安全建议请参考：`docs/SECURITY.md`

## 构建 macOS App / DMG

```bash
cd ~/my-own-script
bash pack_mac_app.sh
bash pack_mac_dmg.sh
```

输出：

- `dist/代码工具箱.app`
- `dist/代码工具箱-<version>-mac.dmg`

入口：`app_main.py`

## 发布到 GitHub Releases（用于应用内更新）

依赖：安装并登录 `gh` CLI。

```bash
cd ~/my-own-script
VERSION=0.1.2 bash release_github.sh
```

---

# ok-script
* ok-script 是基于图像识别技术, 纯Python实现的, 支持Windows窗口和模拟器的自动化测试框架。
* 框架包含UI, 截图, 输入, 设备控制, OCR, 模板匹配, 框框Debug浮层, 基于Github Action的测试, 打包, 升级/降级。
* 基于开发一个工业级的自动化软件仅需几百行代码。

## 优势

1. 纯Python实现, 免费开源, 依赖库均为开源方案
2. 支持pip install任何第三方库, 可以方便整合yolo等框架
3. 一套代码即可支持Windows安卓模拟器/ADB连接的虚拟机, Windows客户端游戏
4. 自适应分辨率
5. 使用coco管理图片匹配素材, 仅需一个分辨率下的截图就, 支持不同分辨率自适应
6. 可打包离线/在线安装setup.exe, 支持通过Pip/Git国内镜像在线增量更新. 在线安装包仅3M
7. 支持Github Action一键构建
8. 支持多语言国际化

### 使用 目前仅支持Python 3.12

* 在你的项目中通过pip依赖使用
```commandline
pip install ok-script
```
* 本地编译源码使用
```commandline
pip install -r requirements.txt # 安装编译ok-script所需的的依赖
mklink /d "C:\path\to\your-project\ok" "C:\path\to\ok-script\ok" #Windows CMD 创建软链接到你的项目中
in_place_build.bat #如修改__init__.pyx 需要编译Cython代码
```

* 编译国际化文件
```commandline
cd ok\gui\i18n
.\release.cmd
cd ok\gui
.\qrc.cmd
```

## 文档和示例代码

* [游戏自动化入门](docs/intro_to_automation/README.md)
  - [1、基本原理：计算机如何“玩”游戏](docs/intro_to_automation/README.md#一基本原理计算机如何玩游戏)
    - [核心循环：三步走](docs/intro_to_automation/README.md#核心循环三步走)
    - [图像分析：从像素到决策](docs/intro_to_automation/README.md#图像分析从像素到决策)
        - [传统图色算法 (OpenCV 库)](docs/intro_to_automation/README.md#1-传统图色算法-opencv-库)
        - [神经网络推理 (Inference)](docs/intro_to_automation/README.md#2-神经网络推理-inference)
    - [2、编程语言选择](docs/intro_to_automation/README.md#二编程语言选择)
        - [常用库概览](docs/intro_to_automation/README.md#常用库概览)
    - [3、开发工具](docs/intro_to_automation/README.md#三开发工具)
* [快速开始](docs/quick_start/README.md)
* [进阶使用](docs/after_quick_start/README.md)
  - [1. 模板匹配 (Template Matching)](docs/after_quick_start/README.md#1-模板匹配-template-matching)
  - [2. 多语言国际化 (i18n)](docs/after_quick_start/README.md#2-多语言国际化-i18n)
  - [3. 自动化测试](docs/after_quick_start/README.md#3-自动化测试)
  - [4. 使用 GitHub Action 自动化打包与发布](docs/after_quick_start/README.md#4-使用-github-action-自动化打包与发布)
* [API文档](docs/api_doc/README.md)
* 开发者群: 938132715
* pip [https://pypi.org/project/ok-script](https://pypi.org/project/ok-script)
