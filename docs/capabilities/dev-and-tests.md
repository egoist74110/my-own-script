# 开发 / 测试

## 这个能力做什么
本地开发运行、跑测试、以及「新增一个能力」时的落点约定。

## 关键文件
| 做什么 | 文件 |
| --- | --- |
| 一键运行（git pull + venv + 装 mac 依赖 + 启动） | `dev_run.sh` |
| 入口 | `app_main.py` |
| mac 依赖 | `requirements-mac.txt` |
| 全平台依赖（含 ok 相关） | `requirements.txt` |
| 测试配置（`testpaths = tests integration`） | `pytest.ini` |
| 版本号 + bump + 钩子 | `app_version.py`、`scripts/bump_version.py`、`.githooks/pre-commit`、`app_ado/versioning.py` |
| 手工打包/发布 | `pack_mac_app.sh`、`pack_mac_dmg.sh`、`release_github.sh` |
| 生成 RSA 密钥对（辅助脚本） | `genkey.py` |

## 怎么跑
```bash
bash dev_run.sh   # 本地开发运行（等价 npm install && npm run dev）
pytest            # 跑测试（见 pytest.ini）
```

## 测试覆盖（`tests/`）
- `test_versioning.py`：4 段版本 bump 纯逻辑（参数化，覆盖进位/规范化）。
- `test_task_migrate.py`：老 `flows` → 新 `tasks` 迁移。
- `test_acl_migrate.py`：ACL task_ids 从 legacy flow id → UUID 迁移。
- `test_app.py` / `test_box.py`：ok-script 的 `Box`/`sort_boxes`，依赖 ok 符号，导入失败自动 `skip`。
- `pytest.ini` 还声明了 `integration` testpath（当前仓库未提供该目录，不影响 `tests/` 运行）。

## 新增能力的落点约定（照 `AGENTS.md` 红线）
1. **代码**：应用相关落 `app_ado/`（UI 进 `app_ado/ui/`，网络/纯逻辑进 `app_ado/*.py`）；ok 自动化相关落 `ok/`；Figma/Lark 各自落 `app_figma/`、`app_lark/`。
2. **密钥**：新凭据走 `app_ado/secrets.py`（或对应模块的 `secrets.py`），只进 Keychain，别写 YAML。
3. **配置**：非密项加进 `app_ado/models.py` 的 pydantic model。
4. **索引**：在 `docs/CAPABILITIES.md` 的能力清单表加一行，并在 `docs/capabilities/` 补一页，保持索引可用。
5. **红线**：涉及 ADO/发布操作的改动，先读 `docs/SECURITY.md` 与 `docs/AI_CHANGE_POLICY.md`；forbidden_paths 里的文件 AI 不得自动改。

## 注意坑
- 运行环境 Python 3.14 + `.venv`；`dev_run.sh` 按 `uname` 选 `requirements-mac.txt`（macOS）或 `requirements.txt`。
- pre-commit 每 commit 自动 bump 版本第 4 段，别手工乱改 `app_version.py` 的第 4 段（发布才用 `release_github.sh` 设前三段）。
- 改 `ok/__init__.pyx` 需 Windows 下重编 Cython（见 ok-script.md）。
