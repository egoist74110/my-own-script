# ok-script 图像识别自动化框架（vendored）

## 这个能力做什么
`ok/` 是独立 vendored 的 ok-script：基于图像识别的纯 Python 自动化测试框架（Windows 窗口/安卓模拟器/ADB），含 UI、截图、输入、设备控制、OCR、模板匹配、框框 Debug 浮层、GitHub Action 构建、打包、升级/降级、i18n。**与「代码工具箱」是两部分，不是同一个应用**——工具箱只是借了它的 UI 组件。

## 模块布局（`ok/`）
| 目录 | 作用 |
| --- | --- |
| `ok/capture/` | 截图 |
| `ok/device/` | 设备控制（窗口/ADB/模拟器） |
| `ok/feature/` | 模板匹配（`Box.pyx`、`FeatureSet.pyx`、`Feature.py`、`CompressCoco.py`） |
| `ok/ocr/` | OCR |
| `ok/gui/` | QFluent UI（`MainWindow.py`、`Tab.py`、`overlay/` Debug 浮层、`i18n/`、`qss/`） |
| `ok/task/` `ok/test/` | 任务/测试 |
| `ok/update/` `ok/util/` `ok/rotypes/` | 升级/工具/类型 |
| `ok/alas/` `ok/third_party/` | 第三方 |

入口：`ok/__init__.py`（Cython `.pyx`/`.pyi` 并存，`__init__.pyx` 需编译）。

## 文档（都在 `docs/` 下）
- `docs/quick_start/README.md` 快速开始
- `docs/after_quick_start/README.md` 进阶（模板匹配/i18n/自动化测试/GitHub Action）
- `docs/api_doc/README.md` API
- `docs/intro_to_automation/README.md` 游戏自动化入门（原理/图色算法/NN 推理）

## 怎么用
- pip：`pip install ok-script`
- 本地源码：`pip install -r requirements.txt` → Windows 下 `mklink /d` 软链 `ok/` 进项目 → 改了 `.pyx` 跑 `in_place_build.bat` 重编 Cython。
- 编译 i18n：`cd ok/gui/i18n && release.cmd`，再 `cd ok/gui && qrc.cmd`。

## 注意坑
- **上游目标 Python 3.12 / Windows**（`setup.py` 写死 `python_requires='==3.12.*'`），而代码工具箱跑 3.14——macOS 上只跑它的 UI 层（`ok/gui/widget/Tab.py` 等），自动化功能（capture/device/feature 的 Cython）在 mac/3.14 不保证（见 `RUN_MAC.md`）。
- 测试 `tests/test_app.py`/`test_box.py` 依赖 ok 符号，导入失败自动 skip。
- 改 `ok/__init__.pyx` 后必须重新编译 Cython（`in_place_build.bat`，Windows）。
- coco 素材管理：只需一个分辨率的截图即可自适应多分辨率。
