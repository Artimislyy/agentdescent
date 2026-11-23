"""The run/reward adapter and final, paired test-set evaluation."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import threading
import uuid
from pathlib import Path

from agentdescent import parse_tree

from .harness import SKILL_KEY, SKILL_NAME, SOLVER_KEY, validate_skill, source_paths, read_text
from .records import sha256_text as digest, harness_sha256
from .runner import PDWeaverInfrastructureError


DEMO_MARKER = "<!-- PDWeaver RSI offline fixture: replay checked -->"

#解析 TrialRunner 返回的 JSON 字符串，检查任务 ID 和成绩是否合法，再返回分数
def reward(task, output):
    """Read the adapter's trusted result, never the agent's claimed PASS."""
    result = json.loads(output)
    if result["task_id"] != task.id:
        raise ValueError("reward/task mismatch")
    score = result.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
        raise ValueError("no valid verifier score (infrastructure failures are not zero)")
    return float(score)


# 接收 Skill 和一道题
# → 创建独立工作区
# → 安装这个版本的 Skill
# → 调用 PDWeaver 做题
# → 正式验收 repair.tcl
# → 保存记录，返回成绩和反馈
class TrialRunner:
    """One fresh workspace and Agent session per rollout, including validation."""

    def __init__(self, records, workspace_root, *, server_url=None, innovus="innovus",
                 timeout=1800.0, verifier_timeout=600.0, concurrency=1,
                 offline=False, source_guard=None, secret_env=()):
        self.records = records
        self.workspace_root = Path(workspace_root)
        self.server_url = server_url #PDWeaver 服务：http://127.0.0.1:8766
        self.innovus = innovus
        self.timeout = timeout
        self.verifier_timeout = verifier_timeout
        self.offline = offline
        self.source_guard = source_guard
        self.secret_env = tuple(secret_env) #子进程通常可以继承父进程的环境变量，但验收 Innovus 不需要模型 API 密钥，因此启动前把这些变量排除。
        self.phase = "search" #test_baseline ， test_candidate
        self.failures = []
        self._verifier_failure = None  # Do not re-solve after verification retries are exhausted.
        self._retry_failures = {}  # Cleaned-up attempts awaiting a valid retry result.
        self.search_results = {}  # (complete harness hash, task id) -> verified trial.
        self.training_results = {}  # Include worker identity so parallel retests cannot overwrite each other.
        self._service = None
        self._lock = threading.Lock()
        self._semaphore = threading.BoundedSemaphore(concurrency)

    def __call__(self, rendered, task, *, purpose="rollout"):
        with self._semaphore:
            if self._verifier_failure is not None:
                raise RuntimeError(self._verifier_failure)
            return self._run(rendered, task, purpose=purpose)

    # TrialRunner.__call__()
    # → TrialRunner._run()
    # → TrialRunner._execute()
    # ├─ 准备题目工作区
    # ├─ 安装当前 Skill
    # ├─ run_pdweaver() → HTTP 调用 PDWeaver 做题
    # └─ verify_submission() → 独立 Innovus 验收
    def _run(self, rendered, task, *, purpose="rollout"):
        # 解析候选的 Skill 和提示词，并检查格式、文件范围和大小。
        state = parse_tree(rendered)
        reason = validate_skill(state)
        if reason:
            raise ValueError(reason)
        # 为本次试跑生成唯一编号，确定记录目录和做题工作区。
        trial_id = uuid.uuid4().hex
        evidence = self.records.root / "trials" / trial_id
        evidence.mkdir(parents=True)
        workspace = self.workspace_root / trial_id
        # 保存任务信息和 Skill 快照；执行前还没有成绩。
        output = {"task_id": task.id, "trial_id": trial_id, "phase": self.phase,
                  "split": task.meta.get("split"), "purpose": purpose,
                  "skill_sha256": digest(state[SKILL_KEY]), "harness_sha256": harness_sha256(state), "score": None,
                  "evidence": str(evidence)}
        output["skill_file"] = self.records.snapshot(state[SKILL_KEY])["file"]
        output["harness_file"] = self.records.snapshot_tree(state)["file"]
        output["agent_trace"] = str(evidence / "agent")
        evaluation = (self.phase, output["harness_sha256"], task.id, purpose, threading.current_thread())
        self.records.write_json("trials/{}/input.json".format(trial_id), output)
        try:
            # 执行前后核对源仓库，确保实验期间基线没有变化。
            if self.source_guard:
                self.source_guard()
            # 准备工作区、安装 Skill、调用 PDWeaver，并将验收结果写入 output。
            self._execute(task, state, workspace, evidence, output)
            if self.source_guard:
                self.source_guard()
            reward(task, json.dumps(output))
        except Exception as exc:
            # 基础设施异常记为无有效成绩，供入口阻止采纳。
            output.update(status="INFRA_ERROR", score=None,
                          feedback="{}: trial infrastructure failed; inspect evidence".format(type(exc).__name__))
            with self._lock:
                self.failures.append(trial_id)
                if isinstance(exc, PDWeaverInfrastructureError) and exc.result.get("cleanup_confirmed") is True:
                    self._retry_failures.setdefault(evaluation, []).append(trial_id)
            raise RuntimeError("trial {} had an infrastructure failure".format(trial_id)) from exc
        else:
            with self._lock:
                recovered = self._retry_failures.pop(evaluation, [])
                if recovered:
                    self.failures[:] = [tid for tid in self.failures if tid not in recovered]
                    output["recovered_trials"] = recovered
        finally:
            # 正常结束或执行异常，都保存本次结果并追加到总记录。
            self.records.write_json("trials/{}/output.json".format(trial_id), output)
            self.records.append("trials.jsonl", output)
        # 按完整候选哈希和题目 ID 保存结果，提示词变化也必须重新评估。
        if self.phase == "search":
            with self._lock:
                self.search_results[(output["harness_sha256"], task.id)] = dict(output)
                if output["split"] == "train":
                    self.training_results[(output["harness_sha256"], task.id, threading.get_ident())] = dict(output)
        # 单独索引成功试跑，便于查找对应的 Skill 和执行轨迹。
        if output["score"] == 1.0:
            self.records.append("successful_trials.jsonl", output)
        # 返回统一的 JSON 文本，供框架提取成绩和生成反思提案。
        return json.dumps(output, ensure_ascii=False)

    def _execute(self, task, state, workspace, evidence, output):
        """Install the candidate, run PDWeaver and obtain the official verdict."""
        from .dataset import fingerprint_workspace, stage_task
        from .runner import run_pdweaver
        from .verifier import verify_submission

        trial_dir = evidence.relative_to(self.records.root)
        if self.offline:
            workspace.mkdir(parents=True)
        else:
            inputs = stage_task(task, workspace)
            self.records.write_json(trial_dir / "public_inputs.json", inputs)
        installed = workspace / ".pdweaver" / "skills" / SKILL_NAME / SKILL_KEY
        installed_files = source_paths(installed, keys=state)
        for key, path in installed_files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(state[key].encode("utf-8"))
        # The task prompt is injected through HTTP; retain its exact bytes.
        if SOLVER_KEY in state:
            self.records.write_text(trial_dir / SOLVER_KEY, state[SOLVER_KEY])
        # /data/workspaces/run-001/trial-001/
        # ├── task.md
        # ├── initial_state/
        # └── .pdweaver/skills/innovus-eco-closure-mcp/SKILL.md
        if self.offline:
            # Deterministic plumbing fixture; explicitly not an EDA evaluator.
            passed = DEMO_MARKER in installed.read_text(encoding="utf-8")
            output.update(status="PASS" if passed else "FAIL", score=float(passed),
                          agent_elapsed_seconds=10.0,  # Fixed fixture time, not a real measurement.
                          skill_read=True, feedback="offline fixture passed; no EDA/model was run" if passed
                          else "offline fixture: missing replay marker")
            return
        #调用 PDWeaver 做题
        # agent = {
        #     "status": "COMPLETED",
        #     "task_id": "task-001",
        #     "session_id": "session-001",
        #     "healthy": True,
        #     "skill_read": True,
        #     "summary": "已生成 repair.tcl，并完成时序检查。",
        #     "elapsed_seconds": 7200.0,
        #     # 还有工具反馈、服务信息和清理记录……
        # }
        agent = run_pdweaver(self.server_url, workspace, evidence / "agent", timeout=self.timeout,
                            user_prompt=state.get(SOLVER_KEY))
        output["agent_elapsed_seconds"] = agent.get("solve_seconds")
        self.records.write_json(trial_dir / "agent_summary.json", agent)
        if agent.get("service") is not None:
            with self._lock:
                if self._service is None:
                    self._service = agent["service"]
                    self.records.write_json("service.json", self._service)
                elif self._service != agent["service"]:
                    raise RuntimeError("PDWeaver service changed between trials")
        # Reflection gets bounded feedback; full model/tool history stays in agent/.
        output.update(agent_status=agent["status"], skill_read=agent["skill_read"],
                      agent_feedback=str(agent.get("feedback", agent.get("summary", "")))[:6000])
        try:
            intact = (fingerprint_workspace(workspace) == inputs
                      and source_paths(installed, keys=state) == installed_files
                      and all(read_text(path) == state[key] for key, path in installed_files.items())
                      and {p for p in installed.parent.parent.rglob("*") if p.is_file() or p.is_symlink()}
                      == set(installed_files.values()))
        except (OSError, ValueError):
            intact = False
        if not intact:
            output.update(status="INVALID_INPUT", score=0.0,
                          feedback="The trial modified its frozen task/checkpoint or installed skill.")
            return
        # After confirmed stop/cleanup, score the submission regardless of Agent status or Skill-read evidence.
        # Retry only verification of this submission, preserving each attempt's evidence.
        for attempt in range(3):
            directory = evidence / ("verifier" if attempt == 0 else "verifier-retry-{}".format(attempt))
            try:
                verdict = verify_submission(task, workspace / "repair.tcl", directory,
                                            innovus=self.innovus, timeout=self.verifier_timeout,
                                            secret_env=self.secret_env)
            except Exception as exc:
                self._verifier_failure = "Verifier raised {}: inspect {} before restarting RSI".format(
                    type(exc).__name__, directory)
                raise
            self.records.write_json(directory.relative_to(self.records.root) / "verdict.json", verdict)
            self.records.write_json(trial_dir / "verdict.json", verdict)
            if verdict["score"] is not None or not verdict.get("retryable", True):
                break
            print("[verifier] trial={} attempt={}/3: {}; evidence={}".format(
                output.get("trial_id"), attempt + 1, verdict["feedback"], directory), flush=True)
        output.update(status=verdict["status"], score=verdict["score"], feedback=verdict["feedback"])
        if verdict["score"] is None:
            self._verifier_failure = "Verifier unavailable: {}; inspect {} before restarting RSI".format(
                verdict["feedback"], evidence)
            raise RuntimeError(self._verifier_failure)


def evaluate_final(runner, strategy, initial, final, tasks, *, concurrency=1):
    """Fresh paired tests using the framework default acceptance policy."""
    if concurrency < 1:
        raise ValueError("test concurrency must be positive")
    tasks = list(tasks)
    measurements = []
    try:
        # 每个版本内并行做题，全部完成后再切换版本，避免并发记录串用 phase。
        for phase, state in (("test_baseline", initial), ("test_candidate", final)):
            runner.phase = phase
            rendered = strategy.render(state)

            def measure(task):
                return json.loads(runner(rendered, task))

            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                measurements.append(list(pool.map(measure, tasks)))
    finally:
        runner.phase = "search"
    rows = [{"task_id": task.id, "baseline": before, "candidate": after}
            for task, before, after in zip(tasks, *measurements)]
    from .selection import compare_default_trials
    comparison = compare_default_trials([r["baseline"] for r in rows], [r["candidate"] for r in rows])
    passed = comparison["passed"] and not runner.failures
    return {**comparison, "rows": rows, "passed": passed,
            "adoption_eligible": passed and not runner.offline and initial != final,
            "offline": runner.offline}
