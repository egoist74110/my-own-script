# 应用核心：运行 / 打包 / 发布 / 更新 / 版本号

## 这个能力做什么
本地一键运行、打 macOS `.app`/`.dmg`、发布到 GitHub Releases、应用内自更新（git + DMG 两条路）、以及 4 段版本号自动管理。

## 关键文件

| 做什么 | 文件 |
| --- | --- |
| 本地一键运行（git pull + 建 venv + 装 mac 依赖 + 启动） | `dev_run.sh` |
| 打包 `.app`（sips 生成 icns，wrapper 指向仓库 venv） | `pack_mac_app.sh` |
| 打包 `.dmg`（hdiutil，`代码工具箱-<版本>-mac.dmg`） | `pack_mac_dmg.sh` |
| 发布到 GitHub Releases（gh CLI，建 tag `v<版本>` 并上传 dmg） | `release_github.sh` |
| 版本号唯一真源（当前 `1.0.3.7`） | `app_version.py` |
| 版本 bump 纯逻辑（4 段十进制进位） | `app_ado/versioning.py` |
| bump 入口（pre-commit 调用） | `scripts/bump_version.py` |
| 每次 commit 自动 +1 第 4 段 | `.githooks/pre-commit` |
| git 自更新（检查/ff-pull/重启） | `app_ado/updater.py` |
| GitHub Releases 更新查询 | `app_ado/release_updater.py` |
| DMG 下载→覆盖安装→重启 | `app_ado/app_installer.py` |
| 设置页「检查更新/更新重安装」UI | `app_ado/ui/ado_tab.py` |

## 怎么用
```bash
bash dev_run.sh                        # 本地开发运行
bash pack_mac_app.sh && bash pack_mac_dmg.sh
VERSION=x.y.z bash release_github.sh   # 发布；也支持 bash release_github.sh x.y.z
```
- 发布版本优先级：`$1` > `$VERSION` > `app_version.py` > 日期兜底；发布时会把 `app_version.py` 同步成发布版本（用 `SKIP_VERSION_BUMP=1` 跳过钩子）。
- 仓库路径不是默认 `~/my-own-script` 时用 `REPO_DIR=/path/... bash pack_mac_app.sh`。
- 应用内更新：设置 Tab 检查更新，走 GitHub Releases（默认仓库 `egoist74110/my-own-script`，可用 `TOOLBOX_GH_OWNER`/`TOOLBOX_GH_REPO` 覆盖）；启动时另有 git 检查（`app_main.py` 尾部）。

## 注意坑
- `.app` 是 wrapper：启动仓库 `.venv` 里的 Python，**不是独立安装包**（见 `BUILD_MAC_APP.md`）；移动仓库后要重打。
- pre-commit 钩子每个普通 commit 都 bump 第 4 段并 `git add app_version.py`；merge commit 自动跳过；`SKIP_VERSION_BUMP=1` 可绕过。
- `.app` 里 `PATH` 极小，git 更新逻辑用绝对路径候选解析 git（`updater.py` 的 `_resolve_git`）。
