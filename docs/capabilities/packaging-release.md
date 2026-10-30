# 打包 / 发布 / 更新 / 版本号

## 这个能力做什么
把 `next/` 构建成 macOS `代码工具箱.app`、签名（本项目仅 ad-hoc）、校验、打 DMG/zip、本机安装，并发布到 GitHub Releases。另含应用内更新器（Tauri updater，默认关闭）。详细参数与退出码见 `next/scripts/README.md`。

## 关键文件

| 做什么 | 文件 |
| --- | --- |
| 版本号唯一来源 | `next/desktop/src-tauri/tauri.conf.json` 的 `version`（当前 `1.1.0`） |
| 版本校验/同步（到 `Cargo.toml`、`desktop/package.json`、`backend/pyproject.toml`） | `next/scripts/sync_version.py`（`--check` / `--write`） |
| 完整构建流水线 | `next/scripts/build_app.sh` |
| 后端运行时（PBS Python + 依赖 + MCP 资源，离线） | `next/scripts/build_runtime.sh`、`next/build/app-resources/backend/` |
| 签名（`--adhoc` / `--identity`） | `next/scripts/sign_app.sh`、`next/desktop/src-tauri/entitlements.plist` |
| 校验 `.app`（结构/路径泄露/真启动握手/codesign） | `next/scripts/verify_app.sh` |
| DMG + zip | `next/scripts/make_dmg.sh` |
| 本机一键安装 | `next/scripts/install_local.sh` |
| 公证（本项目不用） | `next/scripts/notarize_app.sh` |
| 更新包/清单（本项目暂不用） | `next/scripts/make_update_artifact.sh`、`make_update_manifest.py`、`validate_updater_config.py` |
| Tauri 配置 | `next/desktop/src-tauri/tauri.conf.json`、`tauri.bundle.conf.json`、`tauri.updater.conf.example.json` |
| 更新器状态机（Rust） | `next/desktop/src-tauri/src/updater.rs`（测试 `src-tauri/tests/updater.rs`） |

## 构建 / 校验 / 签名
前置（人手一次）：装 python-build-standalone 3.14 并导出 `TOOLBOX_PBS_PYTHON_HOME`（命令见 `next/scripts/README.md` §1.1）；构建全程离线，需预先缓存 uv / pnpm / cargo 依赖。

```bash
python3 next/scripts/sync_version.py --check          # 版本一致性（build_app.sh 内也会跑）
bash next/scripts/build_app.sh --sign adhoc           # 产出 next/build/out/代码工具箱.app 并自动 verify_app.sh
bash next/scripts/verify_app.sh next/build/out/代码工具箱.app   # 单独复验
```
- `build_app.sh` 步骤：版本检查 → 前端构建（`--skip-frontend` 复用 `dist/`）→ `build_runtime.sh` → `pnpm tauri build --bundles app` → 拷到 `next/build/out/` → 可选签名 → 校验。
- ad-hoc 签名**不加** hardened runtime（否则内置 `.so` 库验证失败）；产物仅私有使用，**无公证**，他机首次打开需右键打开/放行。
- Cargo 产物目录默认 `.local/cargo-target`（`CARGO_TARGET_DIR` 可改）。

## 本机安装
```bash
bash next/scripts/install_local.sh --open   # 完整构建(ad-hoc) → 优雅退出旧进程 → 覆盖 /Applications/代码工具箱.app → 打开
```
`--skip-build` 复用 `next/build/out/` 已有产物，`--dest <dir>` 换安装目录。按精确 PID 发 SIGTERM（走应用协调关闭），不会按名字 `pkill`。

## 发布到 GitHub Release
1. 改版本：编辑 `tauri.conf.json` 的 `version`，再 `python3 next/scripts/sync_version.py --write`，`--check` 确认。
2. 构建：`bash next/scripts/build_app.sh --sign adhoc`。
3. 打包：`bash next/scripts/make_dmg.sh next/build/out/代码工具箱.app next/build/out` → `TOOLBOX-<ver>-arm64.dmg` 与 `.zip`。
4. 提交版本改动并打 tag、推送，然后发布（需 `gh` 已登录；对外动作，执行前确认）：
   ```bash
   gh release create vX.Y.Z next/build/out/TOOLBOX-X.Y.Z-arm64.dmg next/build/out/TOOLBOX-X.Y.Z-arm64.zip --latest
   ```
   可加 `--title` / `--notes-file`。

## 应用内更新器（Tauri updater）
- 代码已内置（`tauri-plugin-updater` + `updater.rs`），但**默认构建未配置 `plugins.updater`，界面显示 `disabled` / `update_not_configured`**，当前发布流程不依赖它；用户靠下载新 DMG/zip 手动更新。
- 启用需：`pnpm tauri signer generate -w ~/.tauri/toolbox-updater.key` 生成密钥（私钥严禁入库）→ 复制 `tauri.updater.conf.example.json` 为仓库外文件，填 `pubkey` 与 `https://` 的 `latest.json` 地址 → `TAURI_SIGNING_PRIVATE_KEY[_PASSWORD]` 放环境变量 → `build_app.sh --sign identity --updater-config <file>`（先过 `validate_updater_config.py`）→ `make_update_artifact.sh <app>` → `make_update_manifest.py` 生成 `latest.json` → 把 `TOOLBOX.app.tar.gz`、`latest.json` 与 DMG 一并上传 Release。
- **限制**：`make_update_artifact.sh` 拒绝 ad-hoc/未签名 app（exit 2；`--allow-unsigned` 仅本地测试，产物不可发布）。即在无 Developer ID 证书的现状下，应用内更新无法真正发布。Tauri 自带 `target/.../bundle/macos/*.app.tar.gz` 来自未签名包，禁止上传。

## 注意坑
- `.app` 名是 `代码工具箱.app`，但 DMG/zip/更新包文件名仍是 `TOOLBOX-…` / `TOOLBOX.app.tar.gz`（脚本里写死）。
- `build_runtime.sh` 的 `TOOLBOX_RUNTIME_OUT` 必须是 `TOOLBOX_BUILD_DIR` 内的绝对路径，否则 exit 2（防误 `rm -rf`）。
- 重签名会令 macOS 屏幕录制/辅助功能 TCC 授权失效（ad-hoc 每次构建都变）。
- 脚本参数/签名顺序有测试：`cd next && python3 -m unittest scripts.tests.test_scripts`。
