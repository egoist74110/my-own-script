#!/bin/bash
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
WORKDIR="$(pwd)"
MAX_CYCLES="${MAX_CYCLES:-6}"
ENTRY_MODE="${ENTRY_MODE:-auto}"
TASK=""

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME --task "your task" [--cwd DIR] [--max-cycles N]

Options:
  --task         User task to execute through Gemini -> Codex orchestration
  --cwd          Working directory for both CLIs (default: current directory)
  --max-cycles   Maximum internal handoff cycles (default: 6)
  --entry-mode   Routing entry mode: auto | high | low (default: auto)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task)
      TASK="${2:-}"
      shift 2
      ;;
    --cwd)
      WORKDIR="${2:-}"
      shift 2
      ;;
    --max-cycles)
      MAX_CYCLES="${2:-}"
      shift 2
      ;;
    --entry-mode)
      ENTRY_MODE="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$TASK" ]]; then
  if [[ ! -t 0 ]]; then
    TASK="$(cat)"
  else
    echo "--task is required" >&2
    usage >&2
    exit 1
  fi
fi

if [[ ! -d "$WORKDIR" ]]; then
  echo "Working directory does not exist: $WORKDIR" >&2
  exit 1
fi

case "$ENTRY_MODE" in
  auto|high|low)
    ;;
  *)
    echo "Invalid --entry-mode: $ENTRY_MODE (expected: auto, high, or low)" >&2
    exit 1
    ;;
esac

for bin in gemini codex jq python3; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "Missing required command: $bin" >&2
    exit 1
  fi
done

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/gemini-codex-orch.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

log_step() {
  printf '[orch] %s\n' "$*" >&2
}

log_status() {
  local label="$1"
  local file="$2"
  if [[ -f "$file" ]]; then
    local status
    status="$(jq -r '.status // "unknown"' "$file" 2>/dev/null || echo "unknown")"
    printf '[orch] %s -> %s\n' "$label" "$status" >&2
  fi
}

PROGRESS_TOTAL=3
PROGRESS_STEP=0
PROGRESS_LABEL=""
PROGRESS_DETAIL=""
PROGRESS_START_TS=0
EXTERNAL_CLI_IDLE_LIMIT="${EXTERNAL_CLI_IDLE_LIMIT:-25}"
STEP_HARD_TIMEOUT="${STEP_HARD_TIMEOUT:-150}"
MONITOR_FAILURE_REASON=""
MONITOR_FAILURE_DETAIL=""

set_progress_total() {
  PROGRESS_TOTAL="$1"
}

render_progress() {
  local step="$1"
  local total="$2"
  local label="$3"
  local detail="${4:-}"
  local elapsed="${5:-}"
  local percent

  if [[ "$total" -le 0 ]]; then
    total=1
  fi

  percent=$(( step * 100 / total ))
  if [[ "$percent" -gt 99 && "$step" -lt "$total" ]]; then
    percent=99
  fi

  if [[ -n "$detail" && -n "$elapsed" ]]; then
    printf '\r[orch] %3d%% | Step %d/%d | %s | %s | %ss   ' "$percent" "$step" "$total" "$label" "$detail" "$elapsed" >&2
  elif [[ -n "$elapsed" ]]; then
    printf '\r[orch] %3d%% | Step %d/%d | %s | %ss   ' "$percent" "$step" "$total" "$label" "$elapsed" >&2
  elif [[ -n "$detail" ]]; then
    printf '\r[orch] %3d%% | Step %d/%d | %s | %s   ' "$percent" "$step" "$total" "$label" "$detail" >&2
  else
    printf '\r[orch] %3d%% | Step %d/%d | %s   ' "$percent" "$step" "$total" "$label" >&2
  fi
}

start_progress() {
  local step="$1"
  local label="$2"
  local detail="${3:-}"
  PROGRESS_STEP="$step"
  PROGRESS_LABEL="$label"
  PROGRESS_DETAIL="$detail"
  PROGRESS_START_TS="$(date +%s)"
  render_progress "$PROGRESS_STEP" "$PROGRESS_TOTAL" "$PROGRESS_LABEL" "$PROGRESS_DETAIL"
}

tick_progress() {
  local now elapsed
  now="$(date +%s)"
  elapsed=$(( now - PROGRESS_START_TS ))
  render_progress "$PROGRESS_STEP" "$PROGRESS_TOTAL" "$PROGRESS_LABEL" "$PROGRESS_DETAIL" "$elapsed"
}

finish_progress() {
  local note="${1:-done}"
  local now elapsed
  now="$(date +%s)"
  elapsed=$(( now - PROGRESS_START_TS ))
  render_progress "$PROGRESS_STEP" "$PROGRESS_TOTAL" "$PROGRESS_LABEL" "$note" "$elapsed"
  printf '\n' >&2
}

project_alias() {
  python3 - "$WORKDIR" <<'PY'
import json
import pathlib
import sys

workdir = sys.argv[1]
alias_name = pathlib.Path(workdir).name or "project"
projects_path = pathlib.Path("/Users/wesker/.gemini/projects.json")
if projects_path.exists():
    try:
        data = json.loads(projects_path.read_text())
        alias_name = data.get("projects", {}).get(workdir, alias_name)
    except Exception:
        pass
print(alias_name)
PY
}

descendant_pids() {
  local root_pid="$1"
  python3 - "$root_pid" <<'PY'
import subprocess
import sys

root = int(sys.argv[1])
seen = set()
queue = [root]
children = []

while queue:
    pid = queue.pop(0)
    try:
        out = subprocess.check_output(
            ["pgrep", "-P", str(pid)],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        out = ""
    for line in out.splitlines():
        try:
            child = int(line.strip())
        except ValueError:
            continue
        if child in seen:
            continue
        seen.add(child)
        children.append(child)
        queue.append(child)

if children:
    print(" ".join(str(pid) for pid in children))
PY
}

kill_process_tree() {
  local root_pid="$1"
  local descendants
  descendants="$(descendant_pids "$root_pid")"

  if [[ -n "$descendants" ]]; then
    kill $descendants >/dev/null 2>&1 || true
  fi
  kill "$root_pid" >/dev/null 2>&1 || true
  sleep 1
  if [[ -n "$descendants" ]]; then
    kill -9 $descendants >/dev/null 2>&1 || true
  fi
  kill -9 "$root_pid" >/dev/null 2>&1 || true
}

is_high_risk_command() {
  local command="$1"
  case "$command" in
    *claude*|*gemini*|*ssh*|*vim*|*less*|*"tail -f"*|*watch*|*"npm run dev"*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

latest_claude_debug_failure() {
  python3 - <<'PY'
from pathlib import Path
import re

paths = []
tmp_log = Path("/tmp/claude-debug-now.log")
if tmp_log.exists():
    paths.append(tmp_log)

debug_dir = Path("/Users/wesker/.claude/debug")
if debug_dir.exists():
    paths.extend(sorted(debug_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:3])

patterns = (
    r"Connection refused",
    r"Connection error",
    r"ECONNREFUSED",
    r"timed out",
    r"timeout",
    r"auth",
    r"unauthorized",
    r"forbidden",
)

for path in paths:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except Exception:
        continue
    for line in reversed(lines[-200:]):
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in patterns):
            print(" ".join(line.split())[:240])
            raise SystemExit
PY
}

active_subprocess_activity() {
  local root_pid="$1"
  local pids
  pids="$(descendant_pids "$root_pid")"
  if [[ -z "$pids" ]]; then
    return
  fi

  python3 - "$root_pid" $pids <<'PY'
import subprocess
import sys

root_pid = int(sys.argv[1])
pids = [int(x) for x in sys.argv[2:]]
if not pids:
    raise SystemExit

try:
    out = subprocess.check_output(
        ["ps", "-o", "pid=,ppid=,command="] + sum([["-p", str(pid)] for pid in [root_pid] + pids], []),
        text=True,
        stderr=subprocess.DEVNULL,
    )
except subprocess.CalledProcessError:
    raise SystemExit

rows = []
for line in out.splitlines():
    line = line.strip()
    if not line:
        continue
    parts = line.split(None, 2)
    if len(parts) < 3:
        continue
    pid, ppid, command = parts
    try:
        rows.append((int(pid), int(ppid), command.strip()))
    except ValueError:
        continue

if not rows:
    raise SystemExit

ignored_fragments = (
    "gemini --approval-mode",
    "/bin/bash /Users/wesker/.gemini/gemini_codex_orchestrator.sh",
    "/Users/wesker/.nvm/versions/node",
)

preferred = []
fallback = []

for pid, ppid, command in rows:
    if pid == root_pid:
        continue
    if any(fragment in command for fragment in ignored_fragments):
        continue
    if "claude" in command:
        preferred.append(("shell", command))
        continue
    if "python3 -c " in command or "python3 - <<'PY'" in command:
        preferred.append(("shell", command))
        continue
    if command.startswith("/bin/bash -c"):
        fallback.append(("shell", command))
        continue
    fallback.append(("proc", command))

def shorten(text, limit=80):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."

for label, command in preferred + fallback:
    print(f"{label}: {shorten(command)}")
    break
PY
}

latest_session_file() {
  local alias_name="$1"
  local chat_dir="/Users/wesker/.gemini/tmp/${alias_name}/chats"
  if [[ ! -d "$chat_dir" ]]; then
    return
  fi
  ls -t "$chat_dir"/session-*.jsonl 2>/dev/null | head -n 1
}

latest_activity() {
  local alias_name="$1"
  local session_file
  session_file="$(latest_session_file "$alias_name")"
  if [[ -z "$session_file" || ! -f "$session_file" ]]; then
    return
  fi

  python3 - "$session_file" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
try:
    lines = [line for line in path.read_text().splitlines() if line.strip()]
except Exception:
    print("")
    raise SystemExit

def shorten(text, limit=60):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."

for raw in reversed(lines):
    try:
        item = json.loads(raw)
    except Exception:
        continue
    if item.get("type") != "gemini":
        continue

    tool_calls = item.get("toolCalls") or []
    if tool_calls:
        call = tool_calls[-1]
        name = call.get("name", "tool")
        args = call.get("args", {})
        if name == "run_shell_command":
          print(f"shell: {shorten(args.get('command', ''))}")
          raise SystemExit
        if name == "grep_search":
          print(f"search: {shorten(args.get('pattern', ''))}")
          raise SystemExit
        if name == "read_file":
          print(f"read: {shorten(args.get('file_path', ''))}")
          raise SystemExit
        if name == "write_file":
          print(f"write: {shorten(args.get('file_path', ''))}")
          raise SystemExit
        print(f"tool: {name}")
        raise SystemExit

    thoughts = item.get("thoughts") or []
    if thoughts:
        subject = thoughts[-1].get("subject", "")
        if subject:
            print(f"thinking: {shorten(subject)}")
            raise SystemExit

print("")
PY
}

wait_with_progress() {
  local pid="$1"
  local activity_alias="${2:-}"
  local interval="${3:-2}"
  local last_activity=""
  local last_change_ts
  last_change_ts="$(date +%s)"

  while kill -0 "$pid" >/dev/null 2>&1; do
    local activity=""
    activity="$(active_subprocess_activity "$pid")"
    if [[ -n "$activity" ]]; then
      PROGRESS_DETAIL="$activity"
    elif [[ -n "$activity_alias" ]]; then
      local activity
      activity="$(latest_activity "$activity_alias")"
      if [[ -n "$activity" ]]; then
        PROGRESS_DETAIL="$activity"
      fi
    fi

    if [[ -n "$PROGRESS_DETAIL" && "$PROGRESS_DETAIL" != "$last_activity" ]]; then
      last_activity="$PROGRESS_DETAIL"
      last_change_ts="$(date +%s)"
    fi

    tick_progress

    local now idle total_elapsed command debug_reason
    now="$(date +%s)"
    idle=$(( now - last_change_ts ))
    total_elapsed=$(( now - PROGRESS_START_TS ))

    if [[ "$PROGRESS_DETAIL" == shell:* || "$PROGRESS_DETAIL" == proc:* ]]; then
      command="${PROGRESS_DETAIL#*: }"
      if is_high_risk_command "$command"; then
        if [[ "$command" == *claude* ]]; then
          debug_reason="$(latest_claude_debug_failure)"
          if [[ -n "$debug_reason" ]]; then
            MONITOR_FAILURE_REASON="external CLI connection failure"
            MONITOR_FAILURE_DETAIL="$command | $debug_reason"
            kill_process_tree "$pid"
            return 124
          fi
        fi

        if (( idle >= EXTERNAL_CLI_IDLE_LIMIT )); then
          MONITOR_FAILURE_REASON="external CLI hung"
          MONITOR_FAILURE_DETAIL="$command exceeded ${EXTERNAL_CLI_IDLE_LIMIT}s without new activity"
          kill_process_tree "$pid"
          return 124
        fi
      fi
    fi

    if (( total_elapsed >= STEP_HARD_TIMEOUT )); then
      MONITOR_FAILURE_REASON="orchestrator step timeout"
      MONITOR_FAILURE_DETAIL="${PROGRESS_LABEL} exceeded ${STEP_HARD_TIMEOUT}s"
      kill_process_tree "$pid"
      return 124
    fi

    sleep "$interval"
  done
}

print_plan_steps() {
  local plan_file="$1"
  if [[ ! -f "$plan_file" ]]; then
    return
  fi

  local count
  count="$(jq '(.steps // []) | length' "$plan_file" 2>/dev/null || echo 0)"
  printf '[orch] Plan ready | %s steps\n' "$count" >&2
  jq -r '.steps // [] | to_entries[] | "[orch]   \(.key + 1). \(.value)"' "$plan_file" 2>/dev/null >&2 || true
}

step_title() {
  local payload_file="$1"
  jq -r '
    if (.plan.steps // [] | length) > 0 then
      .plan.steps[(.current_step_index // 0)]
    else
      ""
    end
  ' "$payload_file" 2>/dev/null
}

json_field() {
  local file="$1"
  local expr="$2"
  jq -r "$expr" "$file"
}

# Render a final-result JSON envelope as human-readable Chinese text.
# Inputs:
#   $1 = "success" | "failure" | "takeover" | "exceeded"
#   $2 = path to a JSON file with fields: task, result/error, notes,
#        validation_results[], known_risks[], review_summary?
render_human_result() {
  local kind="$1"
  local file="$2"
  python3 - "$kind" "$file" <<'PY'
import json
import pathlib
import sys

kind = sys.argv[1]
data = json.loads(pathlib.Path(sys.argv[2]).read_text())

def section(title, body):
    if not body:
        return
    print(title)
    if isinstance(body, list):
        for item in body:
            text = str(item).strip()
            if text:
                print(f"  - {text}")
    else:
        for line in str(body).splitlines():
            line = line.rstrip()
            if line:
                print(f"  {line}")
    print()

task = (data.get("task") or "").strip()
result = (data.get("result") or data.get("summary") or "").strip()
notes = (data.get("notes") or "").strip()
validation = data.get("validation_results") or []
risks = data.get("known_risks") or []
review = (data.get("review_summary") or "").strip()
error = (data.get("error") or "").strip()
context = (data.get("context") or "").strip()

if kind == "success":
    print("【结果】")
    print(result if result else "(无具体结论)")
    print()
elif kind == "takeover":
    print("【高级模型已接管完成】")
    print(result if result else "(高级模型未给出文本结论)")
    print()
elif kind == "failure":
    print("【任务失败】")
    print(error if error else "(未提供错误描述)")
    print()
    if context:
        section("背景：", context)
elif kind == "exceeded":
    print("【超出最大编排循环次数，未完成】")
    print(error or "请检查日志或重试")
    print()

if notes:
    section("备注：", notes)
if validation:
    section("已执行验证：", validation)
if risks:
    section("已知风险：", risks)
if review:
    section("高级模型复检：", review)

if task and kind != "success":
    section("原始任务：", task)
PY
}

ensure_json_file() {
  local raw_file="$1"
  local out_file="$2"
  python3 - "$raw_file" "$out_file" <<'PY'
import json, sys, pathlib
raw = pathlib.Path(sys.argv[1]).read_text()
candidate = raw.strip()
if candidate.startswith("```"):
    lines = candidate.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    candidate = "\n".join(lines).strip()
try:
    parsed = json.loads(candidate)
except json.JSONDecodeError as exc:
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(candidate[start:end + 1])
        except json.JSONDecodeError:
            sys.stderr.write(f"Invalid JSON output:\n{raw}\nJSON error: {exc}\n")
            sys.exit(1)
    else:
        sys.stderr.write(f"Invalid JSON output:\n{raw}\nJSON error: {exc}\n")
        sys.exit(1)
pathlib.Path(sys.argv[2]).write_text(json.dumps(parsed, ensure_ascii=False, indent=2))
PY
}

collect_git_diff() {
  local diff_file="$1"
  if git -C "$WORKDIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    {
      echo "# git diff --stat"
      git -C "$WORKDIR" diff --stat --no-ext-diff || true
      echo
      echo "# git diff"
      git -C "$WORKDIR" diff --no-ext-diff || true
    } >"$diff_file"
  else
    echo "git diff unavailable: $WORKDIR is not a git repository" >"$diff_file"
  fi
}

run_gemini_json() {
  local mode="$1"
  local payload_file="$2"
  local out_file="$3"
  local prompt_file="$TMP_DIR/gemini_${mode}_prompt.txt"

  cat >"$prompt_file" <<EOF
You are running inside a local Gemini -> Codex orchestrator (headless mode).
Working directory: $WORKDIR
Mode: $mode

Follow these local rules before acting:
- \$HOME/.gemini/GEMINI.md
- \$HOME/.gemini/ORCHESTRATION.md
- \$HOME/.gemini/WORKFLOW.md
- \$HOME/.gemini/RULES.md
- \$HOME/.gemini/STYLE.md

You may inspect files, edit files, and run validation in the working directory as needed.
Do not ask the user to switch models.
Prefer built-in file tools first. If a shell-command tool is unavailable, do not retry the same missing tool; switch to available file or search tools.

External CLI rule:
- Never launch a bare interactive CLI that can take over the terminal indefinitely.
- For long-running or interactive commands (claude, gemini, ssh, vim, less, tail -f, watch, npm run dev, etc.) use a non-interactive form and apply a timeout.
- If a command times out, hangs, or produces partial output, stop and report the actual situation; do not blindly retry.

Task routing rule:
- Respect the payload field "entry_mode".
- "low" / "auto": you are the default executor. Run the task yourself for anything you can finish independently. Only return "need_plan" when truly blocked (architecture decision, ambiguity that cannot be resolved by reading code, repeated same-class failures, verification persistently failing, or scope expansion beyond original task).
- "high": you are the context reader. Read only the minimum context, compress it, return "need_plan" so the high model can plan.
- The compressed summary sent upstream should focus on: modules, dependencies, relevant files, key functions, problem area, constraints, attempts, blockers, and what you specifically need from the high model.
- If you already tried execution and got blocked, still send the compressed summary together with attempts, error, and diff.

Self-check rule:
- After completing work, run task-scoped validation that is actually executable in this workspace (type check, lint, build, relevant unit tests).
- If validation cannot run due to environment / permission limits, report that honestly — do not fabricate results.
- Self-check is the default terminal state. Set "review_required" to false unless the user's task explicitly asked for high-model review, or you genuinely cannot self-verify a behavior change.

Initial mode choice:
- "success" for tasks you completed directly + self-checked.
- "need_plan" only for genuinely complex / blocked work after summarizing context.
- Do not return "need_plan" for trivially simple work, even when entry_mode is "high".

Output exactly one JSON object and nothing else.

Allowed output shapes:
1. Success
{
  "status": "success",
  "result": "...",
  "notes": "...",
  "validation_results": ["..."],
  "known_risks": ["..."],
  "review_flags": {
    "changed_files": ["..."],
    "changed_modules": ["..."],
    "behavior_changed": false,
    "architecture_changed": false,
    "verification_mechanical": true,
    "uncertainty": false,
    "review_required": false,
    "review_reason": "..."
  }
}

2. Need Codex plan
{
  "status": "need_plan",
  "task": "...",
  "context": "...",
  "context_summary": {
    "modules": [
      {
        "name": "...",
        "depends_on": ["..."],
        "key_functions": ["..."]
      }
    ],
    "relevant_files": ["..."],
    "problem_area": "...",
    "notes": ["..."],
    "work_done": ["..."],
    "current_state": ["..."],
    "problem": "...",
    "need_from_high_model": ["..."]
  },
  "constraints": ["..."],
  "attempts": [...],
  "error": "...",
  "diff": "..."
}

3. Failure
{
  "status": "failure",
  "error": "...",
  "context": "...",
  "attempts": [...]
}

4. Final review payload
{
  "status": "final_review",
  "task": "...",
  "summary": "...",
  "diff": "...",
  "validation_results": ["..."],
  "known_risks": ["..."]
}

5. Step progress during execute_plan
{
  "status": "in_progress",
  "task": "...",
  "step_index": 1,
  "total_steps": 3,
  "step_title": "...",
  "step_result": "...",
  "notes": "...",
  "validation_results": ["..."],
  "known_risks": ["..."]
}

If mode is "execute_plan", you must continue execution using the provided plan unless blocked by reality.
If mode is "execute_plan", execute exactly one plan step per call:
- Read payload.plan.steps and payload.current_step_index
- Execute only the current indexed step
- Do not execute later plan steps in the same call
- Return step_index as the 1-based number of the step just completed
- If more steps remain, return "in_progress"
- If the current step is the last remaining step, return "success" or "final_review"
- Keep validation_results and known_risks truthful and scoped to work actually completed so far
If the same class of error repeats twice, return "need_plan" instead of guessing.
In "initial" mode, prefer returning "need_plan" for genuinely complex tasks after summarizing context, rather than prematurely implementing without a plan.

Payload JSON:
$(cat "$payload_file")
EOF

  BYPASS_AI_ORCH=1 gemini --approval-mode yolo -p "$(cat "$prompt_file")" -o json >"$TMP_DIR/gemini_envelope.json" &
  local gemini_pid=$!
  MONITOR_FAILURE_REASON=""
  MONITOR_FAILURE_DETAIL=""
  if ! wait_with_progress "$gemini_pid" "$PROJECT_ALIAS" 2; then
    local monitor_rc=$?
    if [[ "$monitor_rc" -eq 124 ]]; then
      wait "$gemini_pid" 2>/dev/null || true
      jq -n \
        --arg error "$MONITOR_FAILURE_REASON" \
        --arg context "$MONITOR_FAILURE_DETAIL" \
        '{
          status: "failure",
          error: $error,
          context: $context,
          attempts: []
        }' >"$out_file"
      return 0
    fi
  fi
  wait "$gemini_pid"
  local gemini_rc=$?
  if [[ "$gemini_rc" -ne 0 ]]; then
    log_step "Gemini exited with code $gemini_rc"
    return "$gemini_rc"
  fi
  jq -r '.response' "$TMP_DIR/gemini_envelope.json" >"$TMP_DIR/gemini_raw.json"
  ensure_json_file "$TMP_DIR/gemini_raw.json" "$out_file"
}

run_codex_json() {
  local mode="$1"
  local payload_file="$2"
  local out_file="$3"
  local prompt_file="$TMP_DIR/codex_${mode}_prompt.txt"

  if [[ "$mode" == "plan" ]]; then
    cat >"$prompt_file" <<EOF
You are Codex running inside a local Gemini -> Codex orchestrator.
Working directory: $WORKDIR
Mode: planner

Follow these local rules before acting:
- \$HOME/.codex/AGENTS.md
- \$HOME/.gemini/ORCHESTRATION.md
- \$HOME/.codex/WORKFLOW.md
- \$HOME/.codex/RULES.md
- \$HOME/.codex/STYLE.md

You are not user-facing in this run. Produce a machine-readable plan only.
Do not execute the task directly unless takeover is strictly necessary.
Prefer planning from the worker's compressed context summary instead of asking for broad additional context.
If payload includes "context_summary", treat it as the primary planning input and only rely on raw context/error/diff as supporting detail.
Output exactly one JSON object and nothing else.

Allowed output:
1. Plan
{
  "status": "plan",
  "task": "...",
  "reason": "...",
  "steps": ["..."],
  "constraints": ["..."],
  "validation": ["..."]
}

2. Takeover
{
  "status": "takeover",
  "reason": "...",
  "instructions": "...",
  "validation": ["..."]
}

Payload JSON:
$(cat "$payload_file")
EOF
  elif [[ "$mode" == "review" ]]; then
    cat >"$prompt_file" <<EOF
You are Codex running inside a local Gemini -> Codex orchestrator.
Working directory: $WORKDIR
Mode: final reviewer

Follow these local rules before acting:
- \$HOME/.codex/AGENTS.md
- \$HOME/.gemini/ORCHESTRATION.md
- \$HOME/.codex/WORKFLOW.md
- \$HOME/.codex/RULES.md
- \$HOME/.codex/STYLE.md

Output exactly one JSON object and nothing else.

Required output:
{
  "status": "accept" | "revise",
  "summary": "...",
  "required_changes": ["..."],
  "validation_review": ["..."],
  "risks": ["..."]
}

Payload JSON:
$(cat "$payload_file")
EOF
  else
    cat >"$prompt_file" <<EOF
You are Codex running inside a local Gemini -> Codex orchestrator.
Working directory: $WORKDIR
Mode: direct takeover execution

Follow these local rules before acting:
- \$HOME/.codex/AGENTS.md
- \$HOME/.gemini/ORCHESTRATION.md
- \$HOME/.codex/WORKFLOW.md
- \$HOME/.codex/RULES.md
- \$HOME/.codex/STYLE.md

Directly execute the task because the worker is stuck.
Output exactly one JSON object and nothing else.

Required output:
{
  "status": "success" | "failure",
  "result": "...",
  "notes": "...",
  "validation_results": ["..."],
  "known_risks": ["..."]
}

Payload JSON:
$(cat "$payload_file")
EOF
  fi

  BYPASS_AI_ORCH=1 codex exec -C "$WORKDIR" --sandbox workspace-write --skip-git-repo-check -o "$TMP_DIR/codex_raw.json" "$(cat "$prompt_file")" >/dev/null &
  local codex_pid=$!
  wait_with_progress "$codex_pid" "" 2 &
  local monitor_pid=$!
  wait "$codex_pid"
  local codex_rc=$?
  kill "$monitor_pid" >/dev/null 2>&1 || true
  wait "$monitor_pid" 2>/dev/null || true
  if [[ "$codex_rc" -ne 0 ]]; then
    log_step "Codex exited with code $codex_rc"
    return "$codex_rc"
  fi
  ensure_json_file "$TMP_DIR/codex_raw.json" "$out_file"
}

build_review_payload() {
  local gemini_success_file="$1"
  local review_file="$2"
  local diff_file="$TMP_DIR/review_diff.txt"
  collect_git_diff "$diff_file"

  python3 - "$gemini_success_file" "$diff_file" "$review_file" <<'PY'
import json, pathlib, sys
success = json.loads(pathlib.Path(sys.argv[1]).read_text())
diff_text = pathlib.Path(sys.argv[2]).read_text()
payload = {
    "status": "final_review",
    "task": success.get("task") or "",
    "summary": success.get("result", ""),
    "diff": diff_text[:12000],
    "validation_results": success.get("validation_results", []),
    "known_risks": success.get("known_risks", []),
}
pathlib.Path(sys.argv[3]).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
PY
}

build_takeover_payload() {
  local source_file="$1"
  local takeover_file="$2"
  python3 - "$source_file" "$takeover_file" <<'PY'
import json, pathlib, sys
src = json.loads(pathlib.Path(sys.argv[1]).read_text())
payload = {
    "task": src.get("task", ""),
    "context": src.get("context", ""),
    "context_summary": src.get("context_summary", {}),
    "constraints": src.get("constraints", []),
    "attempts": src.get("attempts", []),
    "error": src.get("error", ""),
    "diff": src.get("diff", ""),
}
pathlib.Path(sys.argv[2]).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
PY
}

build_execute_plan_payload() {
  local task="$1"
  local entry_mode="$2"
  local plan_file="$3"
  local current_step_index="$4"
  local step_reports_file="$5"
  local out_file="$6"

  python3 - "$task" "$entry_mode" "$plan_file" "$current_step_index" "$step_reports_file" "$out_file" <<'PY'
import json, pathlib, sys

task = sys.argv[1]
entry_mode = sys.argv[2]
plan = json.loads(pathlib.Path(sys.argv[3]).read_text())
current_step_index = int(sys.argv[4])
step_reports_path = pathlib.Path(sys.argv[5])
step_reports = json.loads(step_reports_path.read_text()) if step_reports_path.exists() else []

payload = {
    "task": task,
    "entry_mode": entry_mode,
    "attempt": current_step_index + 1,
    "current_step_index": current_step_index,
    "plan": plan,
    "step_reports": step_reports,
}
pathlib.Path(sys.argv[6]).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
PY
}

append_step_report() {
  local reports_file="$1"
  local progress_file="$2"
  python3 - "$reports_file" "$progress_file" <<'PY'
import json, pathlib, sys

reports_path = pathlib.Path(sys.argv[1])
progress = json.loads(pathlib.Path(sys.argv[2]).read_text())
reports = json.loads(reports_path.read_text()) if reports_path.exists() else []
reports.append({
    "step_index": progress.get("step_index"),
    "step_title": progress.get("step_title", ""),
    "step_result": progress.get("step_result", ""),
    "notes": progress.get("notes", ""),
    "validation_results": progress.get("validation_results", []),
    "known_risks": progress.get("known_risks", []),
})
reports_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2))
PY
}

should_run_codex_review() {
  local success_file="$1"
  local gemini_status="$2"

  # Low model self-checks by default. Codex review only runs when:
  #   - the worker explicitly tagged review_required=true (user asked for review), OR
  #   - the worker returned a final_review payload directly (worker asked for review).
  # Multi-file / behavior-change / etc. no longer auto-trigger review — the user
  # decides when to bring in the high model.
  if [[ "$gemini_status" == "final_review" ]]; then
    return 0
  fi

  if jq -e '.review_flags.review_required == true' "$success_file" >/dev/null 2>&1; then
    return 0
  fi

  return 1
}

TASK_FILE="$TMP_DIR/task.json"
python3 - "$TASK" "$ENTRY_MODE" "$TASK_FILE" <<'PY'
import json, pathlib, sys
payload = {"task": sys.argv[1], "entry_mode": sys.argv[2]}
pathlib.Path(sys.argv[3]).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
PY

CURRENT_MODE="initial"
CURRENT_PAYLOAD="$TASK_FILE"
LAST_SUCCESS=""
ACTIVE_ENTRY_MODE="$ENTRY_MODE"
ESCALATED_TO_CODEX=0
STEP_REPORTS_FILE="$TMP_DIR/step_reports.json"
CURRENT_PLAN_FILE=""
PROJECT_ALIAS="$(project_alias)"

printf '[orch] Task received\n' >&2
printf '[orch] cwd=%s\n' "$WORKDIR" >&2
printf '[orch] entry_mode=%s\n' "$ENTRY_MODE" >&2
set_progress_total 3

for ((cycle=1; cycle<=MAX_CYCLES; cycle++)); do
  GEMINI_OUT="$TMP_DIR/gemini_cycle_${cycle}.json"
  if [[ "$CURRENT_MODE" == "initial" || "$CURRENT_MODE" == "execute_plan" ]]; then
    if [[ "$CURRENT_MODE" == "initial" ]]; then
      start_progress 1 "Gemini analyze" "reading task and deciding route"
    else
      local current_step_index step_num total_steps title
      current_step_index="$(json_field "$CURRENT_PAYLOAD" '.current_step_index // 0')"
      total_steps="$(json_field "$CURRENT_PAYLOAD" '(.plan.steps // []) | length')"
      step_num=$(( current_step_index + 1 ))
      title="$(step_title "$CURRENT_PAYLOAD")"
      start_progress 3 "Gemini execute" "plan step ${step_num}/${total_steps}: ${title}"
    fi
    run_gemini_json "$CURRENT_MODE" "$CURRENT_PAYLOAD" "$GEMINI_OUT"
    GEMINI_STATUS="$(json_field "$GEMINI_OUT" '.status')"
    finish_progress "$GEMINI_STATUS"

    if [[ "$GEMINI_STATUS" == "in_progress" ]]; then
      append_step_report "$STEP_REPORTS_FILE" "$GEMINI_OUT"
      local next_step_index total_steps
      next_step_index="$(json_field "$GEMINI_OUT" '.step_index')"
      total_steps="$(json_field "$GEMINI_OUT" '.total_steps')"
      printf '[orch] Step %s/%s done | %s\n' \
        "$next_step_index" \
        "$total_steps" \
        "$(json_field "$GEMINI_OUT" '.step_title')" >&2
      PLAN_PAYLOAD="$TMP_DIR/execute_plan_${cycle}.json"
      build_execute_plan_payload \
        "$TASK" \
        "$ACTIVE_ENTRY_MODE" \
        "$CURRENT_PLAN_FILE" \
        "$next_step_index" \
        "$STEP_REPORTS_FILE" \
        "$PLAN_PAYLOAD"
      CURRENT_MODE="execute_plan"
      CURRENT_PAYLOAD="$PLAN_PAYLOAD"
      continue
    fi

    if [[ "$GEMINI_STATUS" == "success" || "$GEMINI_STATUS" == "final_review" ]]; then
      LAST_SUCCESS="$GEMINI_OUT"
      if ! should_run_codex_review "$GEMINI_OUT" "$GEMINI_STATUS"; then
        set_progress_total 2
        start_progress 2 "Return result" "formatting final result"
        finish_progress "done"
        FINAL_PAYLOAD="$TMP_DIR/final_${cycle}.json"
        jq -n \
          --arg task "$TASK" \
          --arg result "$(json_field "$GEMINI_OUT" '.result')" \
          --arg notes "$(json_field "$GEMINI_OUT" '.notes')" \
          --argjson validation_results "$(jq '.validation_results // []' "$GEMINI_OUT")" \
          --argjson known_risks "$(jq '.known_risks // []' "$GEMINI_OUT")" \
          '{
            task: $task,
            result: $result,
            notes: $notes,
            validation_results: $validation_results,
            known_risks: $known_risks
          }' >"$FINAL_PAYLOAD"
        render_human_result success "$FINAL_PAYLOAD"
        exit 0
      fi

      REVIEW_PAYLOAD="$TMP_DIR/review_payload_${cycle}.json"
      if [[ "$GEMINI_STATUS" == "final_review" ]]; then
        cp "$GEMINI_OUT" "$REVIEW_PAYLOAD"
      else
        build_review_payload "$GEMINI_OUT" "$REVIEW_PAYLOAD"
      fi
      if [[ "$ESCALATED_TO_CODEX" == "1" ]]; then
        set_progress_total 4
        start_progress 4 "Codex review" "checking final result"
      else
        set_progress_total 3
        start_progress 2 "Codex review" "checking final result"
      fi
      CODEX_REVIEW="$TMP_DIR/codex_review_${cycle}.json"
      run_codex_json "review" "$REVIEW_PAYLOAD" "$CODEX_REVIEW"
      REVIEW_STATUS="$(json_field "$CODEX_REVIEW" '.status')"
      if [[ "$REVIEW_STATUS" == "accept" ]]; then
        finish_progress "accept"
        if [[ "$ESCALATED_TO_CODEX" == "1" ]]; then
          set_progress_total 5
          start_progress 5 "Return result" "formatting final result"
        else
          set_progress_total 3
          start_progress 3 "Return result" "formatting final result"
        fi
        finish_progress "done"
        FINAL_PAYLOAD="$TMP_DIR/final_${cycle}.json"
        jq -n \
          --arg task "$TASK" \
          --arg result "$(json_field "$REVIEW_PAYLOAD" '.summary')" \
          --arg notes "$([[ "$GEMINI_STATUS" == "success" ]] && json_field "$GEMINI_OUT" '.notes' || echo "已提交高级模型复检")" \
          --arg review_summary "$(json_field "$CODEX_REVIEW" '.summary')" \
          --argjson validation_results "$(jq '.validation_results' "$REVIEW_PAYLOAD")" \
          --argjson known_risks "$(jq '.known_risks' "$REVIEW_PAYLOAD")" \
          '{
            task: $task,
            result: $result,
            notes: $notes,
            review_summary: $review_summary,
            validation_results: $validation_results,
            known_risks: $known_risks
          }' >"$FINAL_PAYLOAD"
        render_human_result success "$FINAL_PAYLOAD"
        exit 0
      fi

      finish_progress "revise"
      printf '[orch] Review result: revise\n' >&2
      PLAN_PAYLOAD="$TMP_DIR/revise_plan_${cycle}.json"
      jq -n \
        --arg task "$TASK" \
        --arg reason "$(json_field "$CODEX_REVIEW" '.summary')" \
        --argjson steps "$(jq '.required_changes' "$CODEX_REVIEW")" \
        --argjson constraints "$(jq '.risks' "$CODEX_REVIEW")" \
        --argjson validation "$(jq '.validation_review' "$CODEX_REVIEW")" \
        '{
          task: $task,
          plan: {
            task: $task,
            reason: $reason,
            steps: $steps,
            constraints: $constraints,
            validation: $validation
          }
        }' >"$PLAN_PAYLOAD"
      CURRENT_MODE="execute_plan"
      CURRENT_PAYLOAD="$PLAN_PAYLOAD"
      continue
    fi

    if [[ "$GEMINI_STATUS" == "need_plan" ]]; then
      set_progress_total 4
      start_progress 2 "Codex plan" "creating execution plan"
      CODEX_PLAN="$TMP_DIR/codex_plan_${cycle}.json"
      run_codex_json "plan" "$GEMINI_OUT" "$CODEX_PLAN"
      PLAN_STATUS="$(json_field "$CODEX_PLAN" '.status')"
      if [[ "$PLAN_STATUS" == "plan" ]]; then
        ESCALATED_TO_CODEX=1
        ACTIVE_ENTRY_MODE="high"
        CURRENT_PLAN_FILE="$CODEX_PLAN"
        finish_progress "plan ready"
        print_plan_steps "$CODEX_PLAN"
        printf '[]' >"$STEP_REPORTS_FILE"
        PLAN_PAYLOAD="$TMP_DIR/execute_plan_${cycle}.json"
        build_execute_plan_payload \
          "$TASK" \
          "$ACTIVE_ENTRY_MODE" \
          "$CODEX_PLAN" \
          0 \
          "$STEP_REPORTS_FILE" \
          "$PLAN_PAYLOAD"
        CURRENT_MODE="execute_plan"
        CURRENT_PAYLOAD="$PLAN_PAYLOAD"
        continue
      fi

      finish_progress "takeover"
      printf '[orch] Codex takeover\n' >&2
      TAKEOVER_PAYLOAD="$TMP_DIR/takeover_${cycle}.json"
      build_takeover_payload "$GEMINI_OUT" "$TAKEOVER_PAYLOAD"
      CODEX_TAKEOVER="$TMP_DIR/codex_takeover_${cycle}.json"
      run_codex_json "takeover" "$TAKEOVER_PAYLOAD" "$CODEX_TAKEOVER"
      FINAL_PAYLOAD="$TMP_DIR/final_takeover_${cycle}.json"
      jq -n \
        --arg task "$TASK" \
        --arg result "$(json_field "$CODEX_TAKEOVER" '.result // ""')" \
        --arg notes "$(json_field "$CODEX_TAKEOVER" '.notes // ""')" \
        --argjson validation_results "$(jq '.validation_results // []' "$CODEX_TAKEOVER")" \
        --argjson known_risks "$(jq '.known_risks // []' "$CODEX_TAKEOVER")" \
        '{
          task: $task,
          result: $result,
          notes: $notes,
          validation_results: $validation_results,
          known_risks: $known_risks
        }' >"$FINAL_PAYLOAD"
      render_human_result takeover "$FINAL_PAYLOAD"
      exit 0
    fi

    FINAL_PAYLOAD="$TMP_DIR/final_failure_${cycle}.json"
    jq -n \
      --arg task "$TASK" \
      --arg error "$(json_field "$GEMINI_OUT" '.error // "未知错误"')" \
      --arg context "$(json_field "$GEMINI_OUT" '.context // ""')" \
      '{
        task: $task,
        error: $error,
        context: $context
      }' >"$FINAL_PAYLOAD"
    render_human_result failure "$FINAL_PAYLOAD"
    exit 1
  fi
done

printf '[orch] Failed: exceeded max orchestration cycles\n' >&2
EXCEEDED_PAYLOAD="$TMP_DIR/final_exceeded.json"
jq -n \
  --arg task "$TASK" \
  --arg error "已达到最大编排循环次数" \
  '{
    task: $task,
    error: $error
  }' >"$EXCEEDED_PAYLOAD"
render_human_result exceeded "$EXCEEDED_PAYLOAD"
exit 1
