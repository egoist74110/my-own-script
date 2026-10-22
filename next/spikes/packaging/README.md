# S0-D 内置 Python 运行时打包 spike

结果：`results-2026-10-22.json`（机器：Apple M4，macOS 27.0.1 / 26A434，uv 0.13.4，CPython 3.14.8，PyInstaller 6.22.3）。
复核：`independent-check.md`（haiku 只读复核）。

## 步骤
1. `./build_pbs.sh` 方案 A：`uv python install 3.14` 到 `next/.local/spike/python`；复制为 `pbs/runtime`；`uv export --frozen --no-dev --no-emit-project` 的锁定依赖 + 后端 wheel 装入运行时自身 site-packages；裁剪（清单 `prune-list-pbs.txt`）；`compileall --invalidation-mode unchecked-hash` 预编译 pyc（签名后的 .app 只读，pyc 必须随包）。启动：`bin/python3.14 -m toolbox_backend`。
2. `./build_pyinstaller.sh` 方案 B：`pyi-env`（spike 私有 uv 环境，同一 PBS 3.14.8 解释器）装锁定依赖 + pyinstaller；`--onedir`，`--collect-submodules toolbox_backend/uvicorn/websockets` + uvicorn 隐式导入。入口 shim 用 `runpy` 跑 `toolbox_backend.__main__`。
3. `./build_tauri_shell.sh`（无运行时的未签名壳）、`./size_app_estimate.sh`（把运行时拷进 `Contents/Resources/backend` 估算整包，输出 `appest-output.txt`）。
4. `./measure.sh`（写 results JSON；`--startup-only --runs 3` 只打印启动数字）。

## 口径
- 计时 t0=Popen 前；READY=读到 stdout 的 READY 行；health=首次 `GET /health` 200（带正确 Host/Bearer）。环境 `env -i`，cwd=/。
- 热启动：丢弃 1 次预热后连测 5 次，页缓存热。冷启动：每次对**新 `cp -R` 副本**首次运行（新文件首次执行，含代码签名检查）；**未清 page cache**（`sudo purge` 不可用），不是真正的冷磁盘。
- RSS：空闲 10 秒后 `ps -axo rss` 对进程组求和。样本离散大（A 19.5–47 MB，B 23–62 MB，macOS 内存压缩），中位数仅作量级参考。
- 压缩：`ditto -c -k --sequesterRsrc --keepParent`（deflate zip，不是 ULFO DMG，DMG 会更小）。
- 退出：关 stdin，全部样本优雅退出码 0，无残留进程。

## 结果（KiB 为 du -sk）
| 指标 | A pbs（含 pyc） | A pbs（无 pyc） | B PyInstaller |
|---|---|---|---|
| 目录未压缩 | 61692 | 41824 | 31212 |
| ditto zip | 22706 | 14686 | 16997 |
| 热启动到 READY 中位数 | 0.265 s | - | 0.328 s |
| 首次 /health 200（从 spawn）中位数 | 0.268 s | - | 0.331 s |
| 「新副本首跑」中位数 | 0.825 s | 1.546 s（需现编译 pyc） | 1.052 s |
| 空闲 10s RSS 中位数 | 40.6 MB | - | 35.6 MB |
| 可重定位 | 是 | - | 是 |
| 非系统动态库依赖 | 无 | - | 无 |

Tauri 壳：release 二进制 9460 KiB，空 .app 9532 KiB（zip 3529）。估算整包：A 71224 KiB（zip 26551），B 40744 KiB（zip 20531）；运行时未接入 tauri bundle 配置，未签名。

热启动 A/B 样本区间重叠（复核者指出），"A 更快"不显著；新副本首跑 A 稍快。

## 优劣与对 S9 的建议（仅建议）
- A（PBS）：标准解释器布局，可 `-m` 启动、依赖即 wheel 安装、调试/换依赖简单；缺点是体积大（pyc 20 MB，zip 后差距缩小到约 6 MB），隐式导入无风险。
- B（PyInstaller）：解压体积约小一半、单一可执行；缺点是隐式导入需维护（uvicorn/websockets 已靠 collect-submodules 通过）、增加构建期依赖、新依赖易漏收集。
- 建议：体积差在安装包（zip）层面约 6 MB，不决定性；倾向 A（可维护性、后续 AI 子进程/脚本复用同一解释器）；若强调最小体积则 B。S9 需另测签名/公证（PBS 内多个可执行/.so 需逐个签名；PyInstaller 的 `_internal` 同理）与 Gatekeeper 首启开销。
