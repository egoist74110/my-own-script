#!/bin/bash
# Read-only context COLLECTOR powered by Gemini Flash.
#
# Designed to be called BY high-tier models (Claude / Codex) as a "scout":
# Flash reads files / runs greps / extracts raw quotes per the caller's
# explicit request. Flash does NOT decide what is important and does NOT
# propose fixes — the caller (a planner-tier model) reads the collected
# packet and makes judgments.
#
# Usage:
#   ask-flash-read.sh --request "<context request>" [--cwd DIR] [--max-words 1200]
#   echo "<context request>" | ask-flash-read.sh
#
# Good request shape (exact, fact-oriented):
#   "Quote the body of class SessionManager (file path + lines).
#    List every file that imports SessionManager.
#    Quote the type definition of UserToken.
#    Note any TODO/FIXME comments inside src/auth/."
#
# Bad request shape (vague, asks for judgment):
#   "Tell me what auth does."
#   "Summarize the project."
#
# Output:
#   stdout = Chinese structured text packet (file paths, raw quotes,
#            symbol/call relations, explicit unknowns). Capped to --max-words.
#   stderr = error / detection log lines
#
# Defaults: timeout 180s, max-words 1200 (clamped 200..2500). Bump up for
# collection-heavy requests, down for narrow lookups.
#
# Exit 0 on success, non-zero on failure.

set -euo pipefail

CACHE_FILE="${HOME}/.gemini/cache/flash_model"
CACHE_TTL_SECONDS=$((7 * 24 * 3600))

# Probe order: newest first. Add new generations to the top when shipped.
CANDIDATES=(
  "gemini-3-flash-latest"
  "gemini-3-flash"
  "gemini-flash-latest"
  "gemini-2.5-flash-latest"
  "gemini-2.5-flash"
)

REQUEST=""
CWD="$PWD"
MAX_WORDS=1200
PER_ATTEMPT_TIMEOUT="${ASK_FLASH_READ_TIMEOUT:-180}"

usage() {
  sed -n '2,32p' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --request)    REQUEST="${2:-}"; shift 2 ;;
    --cwd)        CWD="${2:-$PWD}"; shift 2 ;;
    --max-words)  MAX_WORDS="${2:-1200}"; shift 2 ;;
    --timeout)    PER_ATTEMPT_TIMEOUT="${2:-$PER_ATTEMPT_TIMEOUT}"; shift 2 ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "ask-flash-read: unknown arg: $1" >&2; usage >&2; exit 1 ;;
  esac
done

if [[ -z "$REQUEST" ]]; then
  if [[ -t 0 ]]; then
    echo "ask-flash-read: no request (use --request or pipe via stdin)" >&2
    exit 1
  fi
  REQUEST="$(cat)"
fi

if [[ -z "${REQUEST// }" ]]; then
  echo "ask-flash-read: empty request" >&2
  exit 1
fi

if [[ ! -d "$CWD" ]]; then
  echo "ask-flash-read: cwd does not exist: $CWD" >&2
  exit 1
fi

# Clamp word cap. Lower bound 200: collection too thin to be useful below this.
# Upper bound 2500: above this we are sending so much raw text back that the
# token-saving rationale starts to evaporate.
if ! [[ "$MAX_WORDS" =~ ^[0-9]+$ ]]; then MAX_WORDS=1200; fi
if (( MAX_WORDS < 200 )); then MAX_WORDS=200; fi
if (( MAX_WORDS > 2500 )); then MAX_WORDS=2500; fi

log() { printf '[ask-flash-read] %s\n' "$*" >&2; }

git_preflight() {
  if ! git -C "$CWD" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    log "preflight: not a git work tree"
    return 0
  fi

  local status_count diff_stat
  status_count="$(git -C "$CWD" status --short 2>/dev/null | wc -l | tr -d ' ')"
  diff_stat="$(git -C "$CWD" diff --stat 2>/dev/null | tail -n 1 || true)"

  log "preflight: cwd=$CWD"
  log "preflight: git status --short lines=$status_count"
  if [[ -n "$diff_stat" ]]; then
    log "preflight: git diff --stat tail=$diff_stat"
  else
    log "preflight: git diff --stat empty"
  fi

  if [[ "$status_count" == "0" && "$REQUEST" =~ (工作区|未提交|当前变更) ]]; then
    log "preflight-error: request mentions working tree/uncommitted changes, but working tree is clean"
    log "preflight-error: did you mean HEAD~1..HEAD or 'git show HEAD'? refine the request and retry"
    exit 2
  fi

  if [[ "$REQUEST" =~ (调用点|调用关系|调用链) && "$REQUEST" =~ (逐文件|所有|全部|全仓|diff) ]]; then
    log "preflight-warning: request asks broad diff + call lookup; split it or raise --timeout"
  fi
}

# Recursion guard: if Flash itself is somehow invoking us, refuse.
if [[ "${FLASH_READ_ONLY:-}" == "1" ]]; then
  echo "ask-flash-read: recursion blocked (FLASH_READ_ONLY=1 set by caller)" >&2
  exit 1
fi

detect_flash_model() {
  if [[ -f "$CACHE_FILE" ]]; then
    if [[ "$(uname)" == "Darwin" ]]; then
      mtime=$(stat -f %m "$CACHE_FILE")
    else
      mtime=$(stat -c %Y "$CACHE_FILE")
    fi
    age=$(( $(date +%s) - mtime ))
    if [[ "$age" -lt "$CACHE_TTL_SECONDS" ]]; then
      cat "$CACHE_FILE"
      return 0
    fi
  fi

  mkdir -p "$(dirname "$CACHE_FILE")"
  for m in "${CANDIDATES[@]}"; do
    if BYPASS_AI_ORCH=1 gemini -m "$m" -p "ok" -o json 2>&1 | grep -q '"session_id"'; then
      printf '%s' "$m" >"$CACHE_FILE"
      printf '%s' "$m"
      return 0
    fi
  done
  return 1
}

if ! MODEL="$(detect_flash_model)"; then
  log "no Flash model available from candidates: ${CANDIDATES[*]}"
  exit 1
fi

log "model=$MODEL timeout=${PER_ATTEMPT_TIMEOUT}s max_words=$MAX_WORDS"
git_preflight

# Build the prompt that frames Flash as a strict read-only CONTEXT COLLECTOR.
# Important: Flash is a scout, not a planner. It executes the request literally,
# preserves raw quotes, and does NOT decide what is "important". The high-tier
# caller (Claude / Codex) reads the collected packet and makes judgments.
PROMPT="$(cat <<EOF
你是上下文收集器（context collector），被高级模型（Claude / Codex 等）调用来按其指令去读代码 / 搜符号 / 列调用 / 抓引文。

你**不是**问题解决者，**不是**架构师，**不是**摘要写手。
你是**侦察兵**：照单收集，原样汇报。决策由参谋长（高级模型）来做。

【硬性约束】
- 只读不改：禁止 Edit、Write、任何修改文件的 shell 命令
- 禁止再次外包：禁止调用 ask-high-model.sh / claude / codex 或其它高级模型 CLI
- 禁止反过来问用户：你直接面向的是高级模型不是人，不要输出"请你确认"
- 禁止给修复建议、设计方案、优化想法——除非请求里**显式**要你给
- 禁止主观判断"哪个文件可能更重要"——按请求字面执行；如果请求模糊到无法执行，在输出末尾的 "未知 / 模糊点" 一节里明确指出
- 不知道就如实说"未找到 / 不确定"，不要编、不要猜
- 输出必须纯中文文本，不要 JSON、不要协议字段、不要"已为您"套话
- 输出长度上限：${MAX_WORDS} 字。超出请舍弃**次要**细节，但**保留所有原文引文**——不要截断引文中间
- 范围预算（硬约束，先自检再行动）：开始正式采集前，**先用轻量命令估算规模**——\`git ls-files | wc -l\`、\`git diff --stat\`、\`grep -rc <关键字> <目录>\`、\`wc -l <文件>\` 这类秒级操作。如果预估满足以下任一条：读取文件数 > 12、搜索次数 > 20、任一单文件 > 1500 行需要全文、diff 总量 > 800 行——**立刻停止采集**，在输出最前面开一节 "## 范围预警" 返回：预估的文件数 / 搜索次数 / diff 行数 + 2–3 个可执行拆分请求（每条拆分写清具体路径 / 符号 / 行范围 / 子请求措辞）。宁可返回拆分建议，也不要硬跑到超时。只有预估在预算内才继续按"输出格式"采集

【工作目录】
$CWD

【请求】
$REQUEST

【输出格式】
按需采用以下结构（请求里没要求的小节可省，不要硬凑）：

## 命中文件
- 路径 + 一句话事实（不是评价），标注大致行数 / 函数数

## 引文（保留原文）
对每个相关代码段：
\`\`\`<语言> <绝对路径>:<起始行>-<结束行>
<原文，不要改写>
\`\`\`

## 符号与调用关系
- \`SymbolName\` (file:line) — 一句话事实描述
- 调用方：file:line, file:line ...
- 被调用：file:line ...

## 数据流 / 依赖（如请求要）
- 输入：... → ... → 输出：...
- 依赖：... 来自 ...

## 未知 / 模糊点
- 请求里 "X" 不明确，可能指 ... 或 ...
- 找不到 ... 关键字
- 这个分支需要运行时数据，无法静态判断

【行为准则】
- 引文请尽量保留原文，包括注释和空行；不要"美化"
- 看到错误信息 / 异常 / 报错栈，**逐字抄下**，不要重述
- 文件 > 1000 行时只贴请求相关的片段，但**标明剩余范围**（"还有 800 行未引用"）
- 看不懂的代码就照抄，不要解释
- 不要前置寒暄、不要复述请求
EOF
)"

cd "$CWD"

python3 - "$PER_ATTEMPT_TIMEOUT" "$MODEL" "$PROMPT" <<'PY'
import json
import os
import subprocess
import sys
import time

secs = float(sys.argv[1])
model = sys.argv[2]
prompt = sys.argv[3]

env = os.environ.copy()
env["BYPASS_AI_ORCH"] = "1"
# Marker so any nested invocation of ask-flash-read.sh refuses to recurse,
# and so a future Flash-side hook could detect this mode if needed.
env["FLASH_READ_ONLY"] = "1"

started = time.monotonic()
try:
    result = subprocess.run(
        ["gemini", "-m", model, "--approval-mode", "yolo",
         "-p", prompt, "-o", "json"],
        capture_output=True, text=True, timeout=secs, env=env,
    )
except subprocess.TimeoutExpired as e:
    elapsed = time.monotonic() - started
    print(f"ask-flash-read: gemini timed out after {elapsed:.1f}s", file=sys.stderr)
    print(f"ask-flash-read: model={model}", file=sys.stderr)
    print("ask-flash-read: prompt prefix:", file=sys.stderr)
    print(prompt[:1200], file=sys.stderr)
    if e.stdout:
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else e.stdout
        print("ask-flash-read: partial stdout:", file=sys.stderr)
        print(out[:2000], file=sys.stderr)
    if e.stderr:
        err = e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr
        print("ask-flash-read: partial stderr:", file=sys.stderr)
        print(err[:2000], file=sys.stderr)
    sys.exit(124)

if result.returncode != 0:
    print(f"ask-flash-read: gemini exited {result.returncode}", file=sys.stderr)
    print(result.stderr[:2000], file=sys.stderr)
    sys.exit(result.returncode)

# Extract .response from the JSON envelope; fall back to raw stdout if parse fails.
text = ""
try:
    obj = json.loads(result.stdout)
    text = obj.get("response", "") or ""
except json.JSONDecodeError:
    text = result.stdout

text = text.rstrip()
if not text:
    print("ask-flash-read: empty response from Flash", file=sys.stderr)
    sys.exit(1)
print(text)
PY
