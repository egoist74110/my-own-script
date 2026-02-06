# Security / 安全说明（代码工具箱）

本工具具备 **触发构建 / 触发发布 / 推进环境** 等能力。
如果凭据（PAT、TG Token、Chat ID）或权限配置不当，可能造成误触发、信息泄露或被他人利用。

本文目标：
- 降低凭据泄漏概率
- 将“泄漏后的影响”限制在可接受范围
- 明确推荐的最小权限与配置

---

## 1. Secrets 存储

- Azure DevOps PAT：存储在 macOS Keychain（通过 `keyring`）
- Telegram Bot Token：存储在 macOS Keychain（通过 `keyring`）
- 配置文件（`~/.config/my-own-script/*.yaml`）**不包含**上述 secrets

**建议**：
- 不要在日志中输出 Authorization / Token / PAT
- 不要把 `~/.config/my-own-script` 或 Keychain 导出给他人

---

## 2. Telegram（信息泄露面）

### 通知策略
- 默认：仅发送 **摘要**（开始/成功/失败），不包含 repo/分支/URL/错误详情
- 可选：在 UI 中开启“通知包含细节”（会增加泄露风险）

### 权限策略
- 使用 Telegram ACL 进行任务授权
- 非 owner 用户：仅能看到/执行其被授权的任务
- 任务执行通知：**仅发送给触发者**（TG 触发时）

---

## 3. 推荐 PAT 最小权限（建议）

以“本机 git 使用 SSH 拉代码（不依赖 PAT 写代码）+ 触发 Build + 触发 Release”为目标：

- **生成（Build）**：读取和执行
- **发布（Release）**：读取、写入和执行
- **代码（Code）**：读取（仅用于列 repo/branch 下拉；如不需要可不勾）

> 不建议给：Code 写入、Release 管理、以及与工作项/测试管理/扩展/代理池/服务连接等无关权限。

---

## 4. ADO 侧权限建议（比 PAT scope 更关键）

即使 PAT scope 很小，ADO 项目级权限仍然是最终控制点。建议：

- Release Pipeline：
  - 允许：创建/执行/部署 release
  - 禁止：编辑/删除 release 定义（definition）
- Build Pipeline：
  - 允许：queue build / run pipeline
  - 禁止：编辑/删除 pipeline 定义
- Repo：
  - 允许：读取
  - 禁止：写入（push）/管理分支策略

目标是：
- “发版/推进环境”可以（可逆）
- “改定义/删资源/写代码”尽量不行（破坏性）

---

## 5. 本机安全建议

- 离开自动锁屏/Touch ID
- 不在不可信机器上运行
- 如果怀疑泄漏：
  1) 立即撤销 PAT
  2) 重新生成 TG Token（必要时）
  3) 检查 ADO 审计/最近 release/build 记录

---

## 6. 风险提示（现实边界）

- 只要具备 Release 写入/执行能力，一旦凭据泄漏，攻击者可能持续触发发布。
- 本文的目标不是“绝对安全”，而是将影响控制在可恢复范围，并尽量禁止不可逆的破坏性操作。
