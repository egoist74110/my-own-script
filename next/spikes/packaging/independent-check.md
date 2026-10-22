# S0-D 打包 spike 独立复核（只读）

复核对象：`results-2026-10-22.json`，以及 `measure.py`、`build_pbs.sh`、`build_pyinstaller.sh`、`build_tauri_shell.sh`、`size_app_estimate.sh`。
复核方式：只读，不改脚本、JSON、构建产物；未联网、未安装。仓库内无 README（`ls spikes/packaging/README*` 无匹配），`size_app_estimate.sh` 注释里提到的 "README step" 不存在。

## 1. 启动/health 重测

运行命令（两轮，每轮 3 次；`--startup-only` 只打印、不写文件）：

```
/usr/bin/python3 <repo>/next/spikes/packaging/measure.py --startup-only --runs 3
```

两轮退出码均为 0，所有样本 `ok: true`、`exit_code: 0`、无 `leftover_pids`。

| 来源 | A_pbs ready_s 样本 | B_pyinstaller ready_s 样本 |
|---|---|---|
| 复核第 1 轮 | 0.606, 0.402, 0.212 | 0.332, 0.248, 0.268 |
| 复核第 2 轮 | 0.170, 0.214, 0.209 | 0.257, 0.210, 0.210 |
| 复核 6 样本中位数 | 约 0.213 | 约 0.253 |
| JSON warm.ready_s_median | 0.265 | 0.328 |

health_from_spawn 的中位数与 ready 基本相同（差约 0.002 到 0.003 s）。

结论：复核中位数与 JSON 同一数量级，A/B 比值约 1.2（JSON 为 1.24），方向一致。但两边的样本区间大幅重叠（A 0.17 到 0.61 s，B 0.21 到 0.33 s），"A 启动更快" 不具统计显著性。复核的 `--startup-only` 不做 warm-up 丢弃，A 的第一个 0.606 s 可能是首次执行效应。

## 2. results JSON 每个数字的来源核对

图例：已复核 = 本次实际运行命令得到相同值；有源 = 能在脚本/日志里找到生成方法，但本次未重算；无源 = 找不到可追溯来源。

### machine
| 字段 | 值 | 来源 | 状态 |
|---|---|---|---|
| date | 2026-10-22 | `measure.py` 里的字面量 `info["date"] = "2026-10-22"` | **无源**（硬编码，不是测量值） |
| macos / macos_build | 27.0.1 / 26A434 | `sw_vers`（measure.py） | 已复核（`sw_vers -productVersion` 27.0.1，`-buildVersion` 26A434） |
| chip / arch | Apple M4 / arm64 | `sysctl -n machdep.cpu.brand_string`、`platform.machine()` | 已复核（`Apple M4`，`arm64`） |
| uv | uv 0.13.4 (Homebrew 2026-10-20 aarch64) | `uv --version` | 已复核 |
| pbs_python | Python 3.14.8 | PBS 解释器 `--version` | 已复核 |
| pyinstaller / build interpreter | 6.22.3 / 3.14.8 | `pyi-env/bin/python -m PyInstaller --version` | 已复核 |
| harness_python | 3.9.6 | `sys.version`（/usr/bin/python3） | 已复核 |
| runs_per_metric | 5 | measure.py `--runs` 默认值 | 有源 |

### A_pbs（pbs/runtime）
| 字段 | 值 | 来源 | 状态 |
|---|---|---|---|
| size_uncompressed_kib | 61692 | `du -sk`；`prune.log` 的 "after compileall" 行 | 已复核（du 当前为 61692） |
| size_compressed_kib | 22706 | `ditto -c -k --sequesterRsrc --keepParent`，再取文件大小 | 已复核（管道方式 `ditto ... /dev/stdout \| wc -c` = 23250851 字节，按 `(n+1023)/1024` 取整为 22706。注意：管道输出与落盘 zip 理论上可能略有差异，此为近似复核） |
| warm.* | 见下 | measure.py 完整运行（非 `--startup-only`） | 有源但未重算（完整运行的原始日志未保留，见第 3 节） |
| cold.* | 见下 | measure.py（fresh `cp -R` 副本） | 有源但未重算；定义已如实写明"非真正冷盘" |
| relocatable | ok | measure.py（mv 走后运行一次） | 有源但未重算 |
| linkage.* | 4 个 Mach-O；无非系统绝对路径 | measure.py `macho_deps` | 已复核（见第 4 节；计数未逐项复算） |
| build.size_kib_raw_copy 82352 / after_prune 41824 / after_compileall 61692 | | `build_pbs.sh` 写入的 `prune.log` | 已复核（prune.log 三行数值完全一致） |

### A_pbs_without_pyc
| 字段 | 值 | 来源 | 状态 |
|---|---|---|---|
| size_uncompressed_kib | 41824 | measure.py 的 `cp -R` + `strip_pyc`；与 `prune.log` 的 "after prune, no pyc" 数值一致 | 已复核（数值与 prune.log 一致；JSON 的 "cp -R then delete __pycache__" 方法与 measure.py 一致） |
| size_compressed_kib | 14686 | measure.py `zip_size` | 无复核（未重算） |
| first_run_no_pyc.* | 见下 | measure.py | 有源但未重算 |

### B_pyinstaller（pyinstaller/toolbox-backend）
| 字段 | 值 | 来源 | 状态 |
|---|---|---|---|
| size_uncompressed_kib | 31212 | `du -sk`；`build_pyinstaller.sh` 也会打印同一命令的结果，但未保留日志 | 已复核（du 当前为 31212） |
| size_compressed_kib | 16997 | `ditto` 管道方式 = 17404678 字节，按 `(n+1023)/1024` 取整 = 16997 | 已复核（同 A 的近似说明） |
| warm.* / cold.* / relocatable | | measure.py 完整运行 | 有源但未重算 |
| linkage.* | libSystem 4、libz 2 等；@rpath libpython3.14.dylib 与 pydantic .so | measure.py | 已复核 toolbox-backend 主可执行文件（仅 libSystem、libz，均为 /usr/lib）；其余 Mach-O 文件的计数未逐项复算 |

### tauri_shell_and_full_app
| 字段 | 值 | 来源 | 状态 |
|---|---|---|---|
| shell_release_binary_kib | 9460 | `build_tauri_shell.sh`；`tauri-build.log` 的 "binary KiB: 9460"；`appest.txt` | 已复核（日志与 appest.txt 一致，du 未重算） |
| shell_empty_app_kib | 9532 | `du -sk` TOOLBOX.app；`appest.txt` | 已复核（du 当前为 9532） |
| shell_empty_app_zip_kib | 3529 | `appest.txt`（`stat -f %z` 换算） | 有源（仅手工捕获的 stdout），未重算 |
| app_with_A_pbs_kib | 71224 | `appest.txt`；数值 = 9532 + 61692（精确相等） | 算术自洽，已复核 |
| app_with_A_pbs_zip_kib | 26551 | `appest.txt` | 有源（手工捕获），未重算 |
| app_with_B_pyinstaller_kib | 40744 | `appest.txt`；数值 = 9532 + 31212（精确相等） | 算术自洽，已复核 |
| app_with_B_pyinstaller_zip_kib | 20531 | `appest.txt` | 有源（手工捕获），未重算 |
| build_time_s_cargo_release | 74 | `tauri-build.log`："Finished `release` profile ... in 1m 14s" | 已复核（日志在 `next/.local/spike/tauri-build.log`） |

### 无源或来源不可追溯的数字
1. `machine.date`：字面量，不是测量。
2. `tauri_shell_and_full_app` 的 zip 大小与整体 app 尺寸：`size_app_estimate.sh` 只把结果打印到 stdout，脚本末尾 `rm -rf "$W"` 删除工作目录；`appest.txt` 看起来是人工从 stdout 捕获的，注释里说的 "merged by hand-run python in README step" 对应的 README 不存在。这些数字只能靠 `appest.txt` 追溯，无法从仓库脚本复现。
3. `notes` 中 "RSS = ... (PyInstaller bootloader + python child)" 与数据矛盾：B 的所有 warm 样本 `group_proc_count` 均为 1，即 onedir 模式下测到的只有 1 个进程，并没有单独的 child。该说明应改为 "单进程"。
4. `tauri_shell` 的 `notes` 写着 "see tauri_shell block if present"，但这段说明与 `notes` 数组的第一条放在一起，JSON 本身无问题，仅属文字冗余。

## 3. 无法复核的部分（如实记录）
warm/cold/relocatable/first_run_no_pyc 的 RSS、中位数与 min/max 都只能由 `measure.py` 完整运行产生。完整运行会覆盖 results JSON，并且会把 app 目录 mv 走再 mv 回来，所以本次没有运行。已有的 `--startup-only` 只覆盖 warm ready/health，不覆盖 RSS、cold、relocatable。

RSS 的离散度很大：A warm 为 19568 到 47328 KiB，B warm 为 23264 到 61984 KiB（5 个样本）。JSON 只给中位数，容易误读为稳定值，应只作量级参考。

## 4. otool 抽查
命令与结果：

```
otool -L <runtime>/bin/python3.14
```
依赖：CoreFoundation（/System/Library）、SystemConfiguration（/System/Library）、/usr/lib/libSystem.B.dylib、/usr/lib/libz.1.dylib、/usr/lib/libedit.3.dylib、/usr/lib/libncurses.5.4.dylib、/usr/lib/libpanel.5.4.dylib。无非系统绝对路径。

```
otool -L <pyinstaller>/toolbox-backend/toolbox-backend
```
依赖：/usr/lib/libSystem.B.dylib、/usr/lib/libz.1.dylib。无非系统绝对路径。

对 A 和 B 目录内全部 Mach-O 文件（A 与 B 各 4 个，`file -b` 判定）检查：除 `/usr/lib/`、`/System/Library/`、`@rpath`、`@loader_path`、`@executable_path` 之外的绝对路径依赖为空。JSON 中的 `non_system_absolute_libs: {}` 因此成立。

## 5. 残留进程与 scratch 目录
- 复核前后执行 `ps -axo pid,ppid,pgid,etime,command | grep -E 'toolbox_backend|toolbox-backend' | grep -v grep`：均无输出，无残留进程。本次未 kill 任何进程。
- `next/.local/spike/measure-scratch`：复核前不存在。`--startup-only` 运行会在该目录下写入 `stderr.log`，并且不会删除目录（只有完整运行结束时才 `rmtree`）。复核结束后已删除 `stderr.log` 与该目录。
- results JSON 在复核前后未被修改（mtime 16:08:03，20450 字节）。

## 6. 疑点汇总
1. `machine.date` 为硬编码字段，不是测量值。
2. 完整测量的原始运行日志未保留，warm/cold/RSS/relocatable 无法独立复算，且完整运行会覆盖 JSON，本次不运行。
3. RSS 的离散度大，中位数不稳定。
4. B 的 RSS 说明（"bootloader + child"）与 `group_proc_count=1` 矛盾。
5. app 级尺寸与 zip 来自 `appest.txt` 的手工捕获，没有可复现的脚本输出，README 也不存在。
6. A 与 B 的启动快慢差异在样本噪声内，不能据此下结论。
7. 冷启动为 "fresh copy 首次执行"，不是真冷盘（JSON 已如实说明）。

## 结论
JSON 中的尺寸（A 61692、B 31212 KiB，以及 prune 三阶段）、linkage、tauri 外壳与整包尺寸的算术、构建耗时均能追溯到脚本或日志，并与复核数值一致。启动数字与 JSON 同量级，方向一致，但 A/B 差异不显著。需修正：`machine.date` 硬编码；B 的 RSS 说明与数据矛盾；app 级 zip 数字的来源仅为手工捕获，应补上可复现的记录或注明来源。
