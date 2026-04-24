#!/bin/bash
# Ask a high-tier model for guidance, with automatic fallback.
#
# Default chain: claude -> codex -> gemini pro
# Override with --model claude|codex|gemini-pro|gemini (alias of gemini-pro).
# When the chosen model fails with quota / auth / rate / overload signals,
# fall through to the next model in the chain.
#
# Input prompt sources (one of):
#   --prompt "..."         inline prompt string
#   --prompt-file PATH     read prompt from file
#   (no flag)              read prompt from stdin
#
# Other options:
#   --cwd DIR              working directory for the called CLI (default: $PWD)
#   --timeout SECONDS      per-attempt timeout (default: 180)
#
# Output:
#   stdout = the model's textual response (no envelope)
#   stderr = orchestration / fallback log lines, prefixed with [ask-high-model]
#   exit 0 on success, exit 1 if all candidates in the chain failed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DETECT_PRO="${SCRIPT_DIR}/detect-gemini-pro.sh"

MODEL_PREF="auto"
PROMPT=""
PROMPT_FILE=""
CWD="$PWD"
PER_ATTEMPT_TIMEOUT="${ASK_HIGH_MODEL_TIMEOUT:-180}"

usage() {
  sed -n '2,25p' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)
      MODEL_PREF="${2:-auto}"
      shift 2
      ;;
    --prompt)
      PROMPT="${2:-}"
      shift 2
      ;;
    --prompt-file)
      PROMPT_FILE="${2:-}"
      shift 2
      ;;
    --cwd)
      CWD="${2:-$PWD}"
      shift 2
      ;;
    --timeout)
      PER_ATTEMPT_TIMEOUT="${2:-180}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ask-high-model: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$PROMPT" && -z "$PROMPT_FILE" ]]; then
  if [[ -t 0 ]]; then
    echo "ask-high-model: no prompt provided (use --prompt, --prompt-file, or pipe via stdin)" >&2
    exit 1
  fi
  PROMPT="$(cat)"
elif [[ -n "$PROMPT_FILE" ]]; then
  if [[ ! -f "$PROMPT_FILE" ]]; then
    echo "ask-high-model: prompt file not found: $PROMPT_FILE" >&2
    exit 1
  fi
  PROMPT="$(cat "$PROMPT_FILE")"
fi

if [[ -z "$PROMPT" ]]; then
  echo "ask-high-model: empty prompt" >&2
  exit 1
fi

log() {
  printf '[ask-high-model] %s\n' "$*" >&2
}

# Resolve the chain of models to try in order.
case "$MODEL_PREF" in
  auto|"")
    CHAIN=(claude codex gemini-pro)
    ;;
  claude)
    CHAIN=(claude codex gemini-pro)
    ;;
  codex)
    CHAIN=(codex claude gemini-pro)
    ;;
  gemini|gemini-pro|gemini_pro)
    CHAIN=(gemini-pro claude codex)
    ;;
  *)
    echo "ask-high-model: unknown --model: $MODEL_PREF (allowed: auto, claude, codex, gemini-pro)" >&2
    exit 1
    ;;
esac

# Wrap a command with a portable timeout (macOS lacks GNU `timeout`).
run_with_timeout() {
  local secs="$1"
  shift
  python3 - "$secs" "$@" <<'PY'
import os
import subprocess
import sys

secs = float(sys.argv[1])
cmd = sys.argv[2:]
try:
    proc = subprocess.run(cmd, timeout=secs)
    sys.exit(proc.returncode)
except subprocess.TimeoutExpired:
    sys.exit(124)
PY
}

# Heuristic: does this stderr / output look like a recoverable error
# (quota, rate, auth, overload) that justifies falling through to the next model?
is_recoverable_error() {
  local text="$1"
  echo "$text" | grep -iE \
    -e 'quota|rate[- ]?limit|too many requests|overload|capacity|temporarily unavailable' \
    -e 'unauthorized|forbidden|401|403|429|503|invalid api key|expired|auth' \
    -e 'connection refused|connection error|econnrefused|network|timeout|timed out' \
    >/dev/null 2>&1
}

# System-prompt addon injected into Claude / Codex calls.
#
# Pattern: planner ↔ scout (NOT planner outsourcing thinking to scout).
# - You (Claude/Codex) are the planner. You decide what context you need.
# - Flash is the scout. It executes your request literally and returns raw
#   facts: file paths, line numbers, original quotes, symbol/call lists.
# - You read the packet, judge sufficiency, then plan / decide.
#
# Critical: do NOT ask Flash "summarize X" or "tell me about Y". That hands
# the importance-judgment to Flash, which is exactly what we want to keep
# under planner control. Issue a precise Context Request instead.
FLASH_DELEGATE_INSTRUCTIONS="$(cat <<'EOF'

[Flash 子代理：你的侦察兵]

你是参谋长，不是苦力。在动手读代码之前，先决定"我要什么事实"，再让便宜的 Gemini Flash 子代理去搬。Flash 只负责按你的清单收集原文 + 标注 file:line + 列调用，不做判断、不写方案。最终判断由你做。

# 工作流（按这个顺序）

1. **接到任务先想清楚要什么上下文**——不要立刻 Read/Grep。问自己：
   - 哪几个具体文件 / 函数我必须看到原文？
   - 哪些符号的"被调用方"我需要列清单？
   - 哪些类型 / 接口定义需要逐字？
   - 报错栈、日志原文需要哪段？
   - 哪些事实知道了就够，哪些必须精确？

2. **写一份精确 Context Request 发给 Flash**——不是"看看 X"，而是"引用 file 的 X 函数原文"、"列出 import Y 的所有文件路径"、"抄 src/auth/types.ts 中 UserToken 类型定义"。

3. **调用 Flash**：

   ```
   bash "$HOME/.gemini/bin/ask-flash-read.sh" \
     --request "<你的精确 Context Request>" \
     --cwd "<工作目录>" \
     [--max-words 1200]
   ```

   返回结构化的 Task Packet（文件清单、引文、符号/调用、未知项）。默认 1200 字，引文密的请求可加到 2500。

4. **审视 Packet**：
   - 信息够吗？不够 → 再发一次 Context Request 补漏
   - Flash 标记了 "未知 / 模糊" 吗？影响判断的话自己直接 Read
   - 任何能影响最终方案的关键代码，**自己直接 Read 核对原文**——不要盲信 Packet

5. **planning / 出方案**——基于 Packet + 关键文件原文，输出方案。

# 什么时候根本不用 Flash

下面这些场景**直接自己读**，调 Flash 反而是负优化：

- 单文件、明确 bug、报错很直接
- 你只需要看 2–5 个已知文件
- 任务里已经给了 file:line
- 任何需要逐字精确的事（变量名、错误消息、配置值、注释、版本号、类型签名）
- 任何"这个判断会改方案"的关键文件

# 什么时候用 Flash

下面这些是 Flash 的强项：

- 在不熟悉的项目里找"X 在哪些文件被用到"
- 列出某个目录 / 模块下相关文件
- 跨文件追调用链 / 数据流
- 抓出长配置 / 长日志里特定字段的原文
- 收集"做这个改动需要先看的所有文件清单"

# 写 Context Request 的规矩

- 用动词："引用"、"列出"、"抄"、"标记"。不要用"总结"、"概述"、"分析"。
- 给具体范围：路径、目录、glob 模式、grep 关键字。
- 列要 / 不要：明说"不要做评价"、"不要建议"、"不要重排"。
- 可以一次问多件事，但每件事都要精确。
- 模糊的请求拿回来的 packet 也模糊，钱白花。

# Flash 的限制

- 只读，改不了文件
- 不能再调用高级模型（防止递归）
- 不会问你澄清；模糊请求 → 它会按字面解释 → 可能跑偏。所以请求要写清楚。
- 上限默认 1200 字 / 最大 2500 字。超出会丢次要细节，但保留引文。

记住：Flash 是侦察兵，不是参谋长。你才是参谋长。
EOF
)"

call_claude() {
  local err_file="$1"
  local out_file="$2"
  # claude -p: non-interactive mode. --add-dir grants workspace read access.
  # --append-system-prompt injects the Flash-delegate instructions.
  # --allowedTools "Bash" allows shell tool use so Claude can run the Flash
  # helper without an interactive permission prompt. Broad Bash access is
  # acceptable here — Claude is already trusted with the workspace via --add-dir.
  if run_with_timeout "$PER_ATTEMPT_TIMEOUT" \
      claude -p "$PROMPT" \
        --add-dir "$CWD" \
        --append-system-prompt "$FLASH_DELEGATE_INSTRUCTIONS" \
        --allowedTools "Bash" \
      >"$out_file" 2>"$err_file"; then
    return 0
  fi
  return 1
}

call_codex() {
  local err_file="$1"
  local out_file="$2"
  # Codex has no --append-system-prompt flag, so prepend the Flash-delegate
  # instructions to the prompt itself. --full-auto is the low-friction
  # sandboxed automatic mode that lets Codex run the helper without
  # per-command approval.
  local codex_prompt="${FLASH_DELEGATE_INSTRUCTIONS}

---

${PROMPT}"
  if BYPASS_AI_ORCH=1 run_with_timeout "$PER_ATTEMPT_TIMEOUT" \
      codex exec -C "$CWD" --skip-git-repo-check --full-auto "$codex_prompt" \
      >"$out_file" 2>"$err_file"; then
    return 0
  fi
  return 1
}

call_gemini_pro() {
  local err_file="$1"
  local out_file="$2"
  local model
  if ! model="$("$DETECT_PRO" 2>/dev/null)"; then
    echo "gemini-pro: detect-gemini-pro failed" >"$err_file"
    return 1
  fi
  local raw_out
  raw_out="$(mktemp)"
  if BYPASS_AI_ORCH=1 run_with_timeout "$PER_ATTEMPT_TIMEOUT" \
      gemini -m "$model" -p "$PROMPT" -o json \
      >"$raw_out" 2>"$err_file"; then
    # Extract .response from the JSON envelope; fall back to raw text on parse failure.
    if jq -e -r '.response' "$raw_out" >"$out_file" 2>/dev/null; then
      rm -f "$raw_out"
      return 0
    fi
    cp "$raw_out" "$out_file"
    rm -f "$raw_out"
    return 0
  fi
  rm -f "$raw_out"
  return 1
}

attempt() {
  local name="$1"
  local err_file out_file
  err_file="$(mktemp)"
  out_file="$(mktemp)"
  log "trying: $name"

  case "$name" in
    claude)     call_claude "$err_file" "$out_file" ;;
    codex)      call_codex "$err_file" "$out_file" ;;
    gemini-pro) call_gemini_pro "$err_file" "$out_file" ;;
  esac
  local rc=$?

  if [[ "$rc" -eq 0 ]]; then
    if [[ ! -s "$out_file" ]]; then
      log "$name returned empty output, treating as failure"
      rm -f "$err_file" "$out_file"
      return 2
    fi
    cat "$out_file"
    rm -f "$err_file" "$out_file"
    log "success: $name"
    return 0
  fi

  local err_text
  err_text="$(head -c 4000 "$err_file" 2>/dev/null || true)"
  rm -f "$err_file" "$out_file"

  if is_recoverable_error "$err_text"; then
    log "$name failed with recoverable error, falling through"
    log "  detail: $(printf '%s' "$err_text" | tr '\n' ' ' | head -c 200)"
    return 2
  fi

  log "$name failed with non-recoverable error"
  log "  detail: $(printf '%s' "$err_text" | tr '\n' ' ' | head -c 200)"
  # Even non-recoverable failures should fall through — better to try the next
  # tier than to surface an opaque error to the caller.
  return 2
}

for model in "${CHAIN[@]}"; do
  if attempt "$model"; then
    exit 0
  fi
done

log "all candidates exhausted: ${CHAIN[*]}"
exit 1
