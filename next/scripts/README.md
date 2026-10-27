# TOOLBOX macOS `.app` 构建、签名与验证脚本（S9-B）

本目录提供将 `TOOLBOX` 打包为可重定位 macOS `.app`、签名、公证及生成分发产物的离线流水线脚本。

---

## 1. 前置准备（需在构建前由人手完成，构建脚本本身绝不联网）

### 1.1 准备 `python-build-standalone` 解释器（`TOOLBOX_PBS_PYTHON_HOME`）

`build_runtime.sh` 不会自行下载解释器。请在首次构建前手动通过 `uv` 安装 Python 3.14 并导出解释器根目录：

```bash
# 1. 下载 python-build-standalone 3.14 到指定目录（仅此一步需联网，由人手执行）
UV_PYTHON_INSTALL_DIR="$HOME/.local/share/toolbox-pbs-python" uv python install 3.14

# 2. 解析出解释器根目录并导出 TOOLBOX_PBS_PYTHON_HOME
PY_BIN="$(UV_PYTHON_INSTALL_DIR="$HOME/.local/share/toolbox-pbs-python" UV_PYTHON_DOWNLOADS=never uv python find --no-project 3.14)"
export TOOLBOX_PBS_PYTHON_HOME="$(cd "$(dirname "$PY_BIN")/.." && pwd -P)"
```

### 1.2 离线依赖缓存要求

所有构建脚本在执行期间均強制离线（`--offline` / `--frozen` / `UV_PYTHON_DOWNLOADS=never` / `CARGO_NET_OFFLINE=true`）：
- **Python 依赖**：需预先在 `next/backend` 下确保 `uv` 缓存已包含 `uv.lock` 锁定的全部 wheel，以及构建后端 wheel 所需的 `uv_build`。
- **前端依赖**：需预先在 `next/desktop` 下完成 `pnpm fetch` 或 `pnpm install --frozen-lockfile`，确保本地 pnpm store 缓存完整。
- **Rust 依赖**：`next/desktop/src-tauri/Cargo.lock` 对应 crate 需已缓存在本地 `~/.cargo` 中。

---

## 2. 脚本清单、用法与退出码

| 脚本 | 用法 | 说明 | 退出码 |
| --- | --- | --- | --- |
| `sync_version.py` | `python3 next/scripts/sync_version.py --check`<br>`python3 next/scripts/sync_version.py --write` | 以 `next/desktop/src-tauri/tauri.conf.json` 的 `version` 为唯一来源，校验或同步 `src-tauri/Cargo.toml`、`next/desktop/package.json`、`next/backend/pyproject.toml`（保持其余字节不变）。 | `0`：一致或写入成功<br>`1`：版本不一致、缺文件或格式错误<br>`2`：命令行参数错误 |
| `build_runtime.sh` | `TOOLBOX_PBS_PYTHON_HOME=... bash next/scripts/build_runtime.sh` | 复制 PBS 解释器到 `next/build/app-resources/backend`，离线安装锁定依赖与非 editable 后端包，复制 `resources/mcp`（不含 `node_modules`）到 `lib/python3.14/resources/mcp`，按 `prune-list-pbs.txt` 裁剪，`compileall --invalidation-mode unchecked-hash` 预编译 `.pyc`，并用 `env -i ... python -I` 导入自检。 | `0`：成功<br>`1`：依赖缺失/安装/自检失败<br>`2`：未设置或找不到 `TOOLBOX_PBS_PYTHON_HOME` |
| `verify_app.sh` | `bash next/scripts/verify_app.sh <path-to-.app>` | 校验 `.app` 目录结构、扫描文本文件无 `/Users/` 路径泄露（白名单仅限 `.dist-info/{RECORD,METADATA,WHEEL,direct_url.json}`）、将 `.app` 拷入临时目录以 `env -i` 启动后端验证 `TOOLBOX_READY` 握手 + `GET /health` 200 + 关 `stdin` 10 秒内 0 退出码且无残留进程 + 运行时目录零新增文件；已签名时执行 `codesign --verify --deep --strict --verbose=2`；打印全部 Mach-O 的最大 `minos`（最低系统版本）。 | `0`：全部检查通过<br>`1`：任意检查项失败<br>`2`：参数缺失或路径不存在 |
| `sign_app.sh` | `bash next/scripts/sign_app.sh --adhoc <path-to-.app>`<br>`TOOLBOX_SIGN_IDENTITY="..." bash next/scripts/sign_app.sh --identity <path-to-.app>` | 按从内到外顺序签名：`Resources/backend` 内全部 Mach-O（`.so`/`.dylib`/可执行）→ `bin/python3.14` → `Contents/MacOS/toolbox-desktop` → `.app`（附带 `src-tauri/entitlements.plist`）。`--identity` 启用 `--options runtime --timestamp`；`--adhoc` 不加 `--options runtime`（ad-hoc 无 Team ID，hardened runtime 的库验证会拒绝加载内置 `.so`，已在真实构建中复现）也不加 `--timestamp`，并打印不可分发警告；`--identity` 下是否需要 `disable-library-validation` 例外留待真实签名后实测。 | `0`：签名成功<br>`1`：`codesign` 执行失败<br>`2`：参数错误、缺 `.app` 或未指定身份且未传 `--adhoc` |
| `notarize_app.sh` | `TOOLBOX_NOTARY_PROFILE="..." bash next/scripts/notarize_app.sh <path-to-.app>` | 用 `ditto -c -k --keepParent` 打包临时 zip → `xcrun notarytool submit --keychain-profile "$TOOLBOX_NOTARY_PROFILE" --wait` → `xcrun stapler staple`。**默认不被任何脚本自动调用，需人手执行。** | `0`：公证并装订成功<br>`1`：公证或装订失败<br>`2`：未设置 `TOOLBOX_NOTARY_PROFILE` 或参数错误 |
| `build_app.sh` | `bash next/scripts/build_app.sh [--skip-frontend] [--sign adhoc\|identity] [--updater-config <file>]` | 串联完整流水线：`sync_version.py --check` → 前端离线构建（`--skip-frontend` 可复用已有 `dist/`）→ `build_runtime.sh` → `pnpm tauri build --bundles app`（叠加 `src-tauri/tauri.bundle.conf.json`，若传入 `--updater-config <file>` 则深度合并至构建叠加配置）→ 拷贝至 `next/build/out/TOOLBOX.app` → 可选签名 → `verify_app.sh`。 | `0`：构建并验证通过<br>`1`：任一构建或验证步骤失败<br>`2`：参数错误、更新配置文件不存在或前置环境变量缺失 |
| `make_dmg.sh` | `bash next/scripts/make_dmg.sh <path-to-.app> <outdir>` | 在 `<outdir>` 下生成带 `Applications` 软链的 `TOOLBOX-<版本>-arm64.dmg`（UDZO）与 `TOOLBOX-<版本>-arm64.zip`（`ditto`）。不含签名、公证或发布。 | `0`：生成成功<br>`1`：`hdiutil` / `ditto` 失败<br>`2`：参数错误或 `.app` 不存在 |
| `make_update_manifest.py` | `python3 next/scripts/make_update_manifest.py --version <semver> [--notes-file <file>] --platform darwin-aarch64 --url <https-url> --signature-file <sig-file> --out <latest.json>` | 生成 Tauri updater 静态清单 `latest.json`（含 `version`、`notes`、UTC RFC3339 `pub_date`、`platforms.<platform>.{signature,url}`）。强制校验严格 SemVer、签名文件非空、URL 必须为 `https://`（仅回环地址 `127.0.0.1`/`::1`/`localhost` 可显式加 `--allow-insecure` 用于本地测试）。仅用标准库，不读私钥、不联网。 | `0`：生成成功<br>`1`：版本/URL/签名文件校验失败<br>`2`：命令行参数错误 |

---

## 3. Entitlements 说明（`next/desktop/src-tauri/entitlements.plist`）

当前 `entitlements.plist` 为最小空字典（`<dict/>`）：
- **不预设** JIT（`com.apple.security.cs.allow-jit` / `allow-unsigned-executable-memory`）与 library-validation（`com.apple.security.cs.disable-library-validation`）例外。
- 后续在具备真实 `Developer ID Application` 证书进行真机签名验收时，若实测发现内嵌运行时或扩展库需要特定 entitlement，再逐项最小化添加并在文件中记录明确理由。

---

## 4. 哪些步骤需要人手与授权

1. **解释器准备**：`uv python install 3.14` 需人手在构建前执行一次并设置 `TOOLBOX_PBS_PYTHON_HOME`。
2. **真实 Developer ID 签名**：需用户在钥匙串自行配置 `Developer ID Application` 证书，通过环境变量 `TOOLBOX_SIGN_IDENTITY` 传入证书名称或 SHA-1 指纹；脚本只传引用给 `codesign`，绝不读取私钥或密码。无证书时只能用 `--adhoc` 做本机验证（**不可分发，且每次更新会导致 macOS 屏幕录制/辅助功能 TCC 授权失效**）。
3. **Apple 公证（Notarization）**：属联网外部操作，需用户另行授权后手动执行 `notarize_app.sh`，并预先在钥匙串通过 `xcrun notarytool store-credentials` 创建好 profile（通过 `TOOLBOX_NOTARY_PROFILE` 传入名称）。
4. **发布（GitHub Releases / git push）**：本目录脚本不包含任何发布或上传逻辑。

---

## 5. 产物位置

- **运行时暂存目录**：`next/build/app-resources/backend/`（含预编译 `.pyc` 与 `lib/python3.14/resources/mcp/`）
- **应用包产物**：`next/build/out/TOOLBOX.app`
- **分发归档产物**（由 `make_dmg.sh` 生成到指定 `<outdir>`，如 `next/build/out/`）：
  - `TOOLBOX-<version>-arm64.dmg`
  - `TOOLBOX-<version>-arm64.zip`
- **更新包产物**（`make_update_artifact.sh`）：`next/build/dist/TOOLBOX.app.tar.gz`、`.sig`、`latest.json`

---

## 6. 应用内更新构建与真实发布步骤清单（S9-C，需用户提供凭据与授权，本仓库不自动执行）

默认构建不启用更新器（应用内显示 `disabled` / `update_not_configured`）。正式发布启用应用内更新时，需由用户在仓库外准备以下信息并按序执行：

1. **生成 Tauri 更新签名密钥对**（仅首次）：
   - 执行 `pnpm tauri signer generate -w ~/.tauri/toolbox-updater.key`，妥善保管私钥与密码（**严禁入库**）。
2. **准备构建时更新器叠加配置文件**（不提交真实地址或根据需要仅在发布环境生成）：
   - 复制 `next/desktop/src-tauri/tauri.updater.conf.example.json` 为本地文件（如 `/tmp/tauri.updater.conf.json`），将 `plugins.updater.pubkey` 替换为上一步生成的公钥文本，`endpoints` 替换为真实 GitHub Releases 静态清单地址：`["https://github.com/<OWNER>/<REPO>/releases/latest/download/latest.json"]`。
3. **构建 `.app`（启用更新器配置）**：
   - `--updater-config` 会先校验：禁止 `dangerousInsecureTransportProtocol`、`endpoints` 必须 `https://`、`pubkey` 非空且不得是示例占位值；不通过 exit 2。
   - 在环境中注入更新私钥（`createUpdaterArtifacts` 构建期需要；仅从环境变量读取，不进 argv/日志/磁盘）：
     ```bash
     export TAURI_SIGNING_PRIVATE_KEY="$(cat ~/.tauri/toolbox-updater.key)"
     export TAURI_SIGNING_PRIVATE_KEY_PASSWORD="<你的密钥密码>"
     bash next/scripts/build_app.sh --sign identity --updater-config /tmp/tauri.updater.conf.json
     ```
   - **注意**：`$CARGO_TARGET_DIR/release/bundle/macos/` 下 Tauri 自带的 `.app.tar.gz/.sig` 来自**未签名**的 bundle，**不得上传或用于 `latest.json`**。
   - 资源映射：`build_app.sh` 会按实际 `TOOLBOX_RUNTIME_OUT`（默认 `$TOOLBOX_BUILD_DIR/app-resources/backend`）改写叠加配置里的 `backend` 资源路径；`build_runtime.sh` 要求 `TOOLBOX_RUNTIME_OUT` 为绝对路径且严格位于 `TOOLBOX_BUILD_DIR` 之内（且不是 `/`、`$HOME`、仓库根），否则 exit 2，不执行 `rm -rf`。
4. **Apple 公证与分发归档**：
   - 执行 `notarize_app.sh` 对 `next/build/out/TOOLBOX.app` 公证并装订；
   - 执行 `make_dmg.sh next/build/out/TOOLBOX.app next/build/out` 生成 DMG 与 zip。
5. **从最终（已签名/公证/装订）的 `.app` 重新生成更新包与签名，再生成 `latest.json`**：
   - ```bash
     bash next/scripts/make_update_artifact.sh next/build/out/TOOLBOX.app    # 产物在 next/build/dist/
     ```
     产出 `next/build/dist/TOOLBOX.app.tar.gz`（`COPYFILE_DISABLE=1 tar` 重打）与 `TOOLBOX.app.tar.gz.sig`（`pnpm tauri signer sign`，私钥只读环境变量 `TAURI_SIGNING_PRIVATE_KEY[_PASSWORD]`）。缺私钥时仅提示并跳过 `.sig`（不失败，但该 tar.gz 不可发布）。
   - **ad-hoc / 未签名的 `.app` 不产出可分发更新包**：脚本会拒绝（exit 2；`--allow-unsigned` 仅供本地测试，产物不可发布）。
   - ```bash
     python3 next/scripts/make_update_manifest.py \
       --version 1.0.0 \
       --notes-file /path/to/release-notes.txt \
       --platform darwin-aarch64 \
       --url "https://github.com/<OWNER>/<REPO>/releases/download/v1.0.0/TOOLBOX.app.tar.gz" \
       --signature-file next/build/dist/TOOLBOX.app.tar.gz.sig \
       --out next/build/dist/latest.json
     ```
6. **上传至 GitHub Releases**（需人手或另行授权后使用 `gh release`）：
   - 将 `TOOLBOX-<version>-arm64.dmg`，以及 `next/build/dist/` 下的 `TOOLBOX.app.tar.gz` 与 `latest.json` 一并上传至对应 GitHub Release（`v<version>`）。
