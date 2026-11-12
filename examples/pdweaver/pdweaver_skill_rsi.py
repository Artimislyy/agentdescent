"""Evolve exactly one native PDWeaver SKILL.md, with durable change evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agentdescent import AggregatorConfig, Task, evolve, tree_reflector
from agentdescent.agents import Usage, openai_compatible
from agentdescent.policies import Policies

from .experiment import DEMO_MARKER, TrialRunner, digest, evaluate_final, reward
from .harness import MAX_SKILL_BYTES, SKILL_KEY, SKILL_NAME, LoggedFileTree, load_initial
from .records import RunRecords
from .selection import SuccessThenSpeed


EDA_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_REPO = EDA_ROOT / "PDWeaver"


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def build_parser():
    """定义命令行参数；例如 --rounds 6 会被解析为 args.rounds == 6。"""
    parser = argparse.ArgumentParser(description=__doc__)

    # 路径与服务配置。
    # PDWeaver 源仓库：用于读取原始 Skill、检查代码版本，以及最终写回。
    parser.add_argument("--pdweaver-repo", type=Path, default=DEFAULT_REPO)
    # 初始 Skill 文件；省略时从仓库路径推导。
    # 真实模式必须指向选定仓库的原生 Skill，离线模式可指定其他合法 Skill。
    parser.add_argument("--skill", type=Path, help="default: PDWeaver/skills/innovus-eco-closure-mcp/SKILL.md")
    # 任务清单 JSON：声明任务目录及 train / val / test 划分；真实模式必填。
    parser.add_argument("--manifest", type=Path, help="explicit train/val/test tasks JSON")
    # 私有实验记录目录，保存基线、提案、diff、评分、日志和候选；必须是新目录。
    # 省略时自动使用 agentdescent/pdweaver-runs/<run-id>。
    parser.add_argument("--output", type=Path, help="new private experiment directory")
    # Agent 执行任务的公开工作区根目录，每次试跑创建独立子目录。
    # 真实模式必填，且必须与私有 output 分属互不包含的目录树。
    parser.add_argument("--workspace-root", type=Path, help="public trial directory shared with PDWeaver")
    # 已启动的 PDWeaver Agent HTTP 服务地址；真实模式必填。
    parser.add_argument("--server", help="PDWeaver Agent HTTP URL, e.g. http://127.0.0.1:8766")

    # 改进模型配置；执行 EDA 任务的推理模型由 PDWeaver 自身配置。
    # 负责根据训练反馈提出 Skill 修改的模型名称；真实模式必填。
    parser.add_argument("--reflect-model", help="OpenAI-compatible model used only to improve the skill")
    # 读取改进模型 API 密钥的环境变量名；这里传变量名，不传密钥本身。
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    # 读取改进模型 API 服务地址的环境变量名。
    parser.add_argument("--base-url-env", default="OPENAI_BASE_URL")
    # 改进模型单次请求的输出 token 上限；不是整个实验的总 token 预算。
    parser.add_argument("--reflect-max-tokens", type=int, default=24000)

    # EDA 正式验收与时间限制。
    # 独立验收进程使用的 Innovus 命令或完整路径；Agent 内部工具由 Runtime 配置。
    parser.add_argument("--innovus", default="innovus")
    # 一次 PDWeaver 任务试跑的超时秒数，默认 1800 秒（30 分钟）。
    parser.add_argument("--trial-timeout", type=float, default=1800.0)
    # 随后独立 Innovus 正式验收的超时秒数，默认 600 秒（10 分钟）。
    parser.add_argument("--verifier-timeout", type=float, default=600.0)

    # 演化与最终评测配置。
    # 最多搜索多少轮；每轮分配训练题并处理候选，不代表完整遍历数据集。
    parser.add_argument("--rounds", type=int, default=2)
    # 每轮参与训练执行和提出修改的逻辑 worker 数量。
    parser.add_argument("--workers", type=int, default=1)
    # worker 同时执行的上限；本例也用它设置验证评估并发和实际试跑并发上限。
    parser.add_argument("--max-concurrency", type=int, default=1)
    # 搜索阶段任务执行预算；None 表示不设该上限。在轮边界检查，可能超出一轮。
    # 不包含搜索结束后，原版和最终版在 test 上的配对重跑。
    parser.add_argument("--max-rollouts", type=int, default=None)
    # 框架随机种子，用于帮助复现；不能保证远端模型输出完全一致。
    parser.add_argument("--seed", type=int, default=0)
    # 最终 test 不允许已通过的题退步；默认先比通过率，持平时选成功题总耗时更短的。
    # 大于 0 时强制要求通过率提升超过此值，不能仅凭提速采纳。
    parser.add_argument("--min-test-gain", type=float, default=0.0)

    # 模式开关：store_true 表示默认 False，命令行写上该开关后变为 True。
    # 仅打印计划后退出，不读取 Skill / 任务数据，不调用模型或 EDA 服务。
    parser.add_argument("--dry-run", action="store_true", help="print plan; no file reads, model or EDA calls")
    # 用模拟任务、固定修改和模拟成绩检查演化、合并、记录流程。
    # 不调用真实模型、PDWeaver 或 Innovus，且不能与 --apply 同时使用。
    parser.add_argument("--offline-demo", action="store_true", help="synthetic scoring; exercise logging without PDWeaver/EDA")
    # 真实最终测试通过且来源与证据核验通过后，写回 Skill，创建 Git 提交和采纳记录。
    # 省略时只交付实验记录和候选；开启后也不会自动更新已有 PDWeaver 会话。
    parser.add_argument("--apply", action="store_true", help="after real test improvement, write skill and Git adoption commits")
    return parser


def _load_inputs(args, source):
    """Validate configuration and freeze the skill, task splits and source repo."""
    #1. 检查轮数、worker 数等是否大于零
    for name in ("rounds", "workers", "max_concurrency", "reflect_max_tokens"):
        if getattr(args, name) < 1:
            raise ValueError("{} must be positive".format(name))
    #2. 检查超时和最低提升要求
    if (not all(math.isfinite(v) for v in (args.trial_timeout, args.verifier_timeout, args.min_test_gain))
            or args.trial_timeout <= 0 or args.verifier_timeout <= 0 or args.min_test_gain < 0):
        raise ValueError("timeouts must be positive and min-test-gain nonnegative")
    #3. 禁止用模拟实验结果写回仓库
    if args.offline_demo and args.apply:
        raise ValueError("offline fixture results can never be applied to PDWeaver")
    #4. 检查真实模式的必要配置是否齐全
    if not args.offline_demo and not all((args.manifest, args.server, args.reflect_model, args.workspace_root)):
        raise ValueError("real mode requires --manifest, --server, --reflect-model and --workspace-root")
    #5. 读取原始 Skill
    initial = load_initial(source)
    #6. 准备训练集、验证集、测试集
    if args.offline_demo:
        splits = {split: [Task(id="{}-{}".format(split, i), prompt="Check the offline replay marker.",
                              meta={"split": split}) for i in range(count)]
                  for split, count in (("train", 4), ("val", 8), ("test", 2))}
    else:
        from .dataset import load_manifest
        splits = load_manifest(args.manifest)
        if not os.environ.get(args.api_key_env):
            raise ValueError("set the reflector credential environment variable {} before a real run".format(args.api_key_env))
    #8. 记录原始 Skill 的身份，可以判断原始 Skill 是否发生变化
    source_info = {"path": str(source), "sha256": digest(initial[SKILL_KEY]), "git_head": None}
    if not args.offline_demo:
        expected = (args.pdweaver_repo / "skills" / SKILL_NAME / SKILL_KEY).resolve()
        if source != expected:
            raise ValueError("real mode must start from the selected PDWeaver repository's native skill")
        #10. 记录 PDWeaver 当前 Git 状态
        source_info["git_head"] = git(args.pdweaver_repo, "rev-parse", "HEAD")
        source_info["git_status"] = git(args.pdweaver_repo, "status", "--porcelain", "--untracked-files=all")
        # Freeze engine code; the native seed may itself be new/uncommitted.
        changed = git(args.pdweaver_repo, "diff", "HEAD", "--name-only").splitlines()
        untracked = git(args.pdweaver_repo, "ls-files", "--others", "--exclude-standard").splitlines()
        if any(path != "skills/{}/{}".format(SKILL_NAME, SKILL_KEY) for path in changed + untracked):
            raise ValueError("PDWeaver has changes outside the native skill; freeze the intended code baseline before evaluation")
    #检查rsi前后pDWeaver源代码是否发生变化，若发生变化则抛出异常
    def source_guard():
        if (git(args.pdweaver_repo, "rev-parse", "HEAD") != source_info["git_head"]
                or git(args.pdweaver_repo, "status", "--porcelain", "--untracked-files=all") != source_info["git_status"]
                or hashlib.sha256(source.read_bytes()).hexdigest() != source_info["sha256"]):
            raise RuntimeError("PDWeaver source baseline changed during the experiment")

    return initial, splits, source_info, None if args.offline_demo else source_guard


def _start_run(args, plan, initial, splits, source_info):
    """Create fresh output/workspace paths and save the reproducible baseline."""
    #1. 生成本次实验的唯一编号
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    #2. 确定实验记录目录
    root = (args.output or EDA_ROOT / "agentdescent" / "pdweaver-runs" / run_id).resolve()
    #3. 确定做题工作区的根目录
    workspace_root = (args.workspace_root or root / "demo-workspaces").resolve()
    #4. 检查记录目录和做题目录是否分开
    if not args.offline_demo and (root == workspace_root or workspace_root in root.parents or root in workspace_root.parents):
        raise ValueError("private experiment output and public workspace-root must be separate directory trees")
    #5. 创建实验记录目录
    root.mkdir(parents=True, exist_ok=False)
    #6. 创建记录器
    records = RunRecords(root)
    #7. 保存原始 Skill，作为实验基线
    records.write_text(f"baseline/{SKILL_KEY}", initial[SKILL_KEY])
    #8. 组装本次实验的说明信息
    manifest = {"schema_version": 1, "run_id": run_id, "plan": plan, "source": source_info,
                "pdweaver_repo": str(args.pdweaver_repo.resolve()),
                "split": {k: [t.id for t in v] for k, v in splits.items()},
                "tasks": {t.id: {"prompt_sha256": digest(t.prompt), "meta": t.meta}
                          for tasks in splits.values() for t in tasks},
                "config": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                "agentdescent_commit": git(Path(__file__).resolve().parents[2], "rev-parse", "HEAD")}
    if args.manifest and not args.offline_demo:
        manifest["manifest_sha256"] = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    #10. 保存实验档案
    records.write_json("manifest.json", manifest)
    # /data/rsi-records/run-001/
    # ├── baseline/
    # │   └── SKILL.md
    # └── manifest.json
    #11. 返回编号、记录器和本次工作区路径
    return run_id, records, workspace_root / run_id


def _build_proposer(args, strategy, usage):
    """Use deterministic edits in the demo, or the native tree reflector."""
    if args.offline_demo:
        def propose(rendered, task, output, score):
            return "<EDITS>" + json.dumps({"rationale": "offline fixture: add deterministic replay marker",
                "edits": [{"path": SKILL_KEY, "content": strategy.initial()[SKILL_KEY] + "\n" + DEMO_MARKER + "\n"}]}) + "</EDITS>"
        return propose
    complete = openai_compatible(args.reflect_model, api_key_env=args.api_key_env,
                                base_url_env=args.base_url_env, max_tokens=args.reflect_max_tokens,
                                usage=usage)
    #reply = complete(prompt)把提示词发到配置的模型服务，返回模型回复
    # 修改 Skill 时，先保证验收通过，再优化耗时。
    template = """Improve the Skill using the verified result and trajectory (reward {reward:.2f}/1.00).
Primary goal: complete the task and pass official verification (reward=1).
Secondary goal: reduce solving time while preserving reward=1.
If reward<1, fix correctness first. Optimise speed only after success.
Generalise; do not hard-code this task, skip required checks or weaken acceptance criteria.
FILES:
{listing}
{contents}
TASK:
{prompt}
RESULT AND TRAJECTORY:
{output}
{expected}
{protocol}"""
    reflect = tree_reflector(complete, strategy=strategy,
                             max_context_chars=MAX_SKILL_BYTES, max_output_chars=24000,
                             template=template)

    def propose(rendered, task, output, score):
        from .trajectory import reflection_input
        return reflect(rendered, task, reflection_input(output, strategy.records), score)

    return propose


def run_experiment(args):
    """Prepare → evolve on train/val → test → seal records → optionally apply."""
    source = (args.skill or args.pdweaver_repo / "skills" / SKILL_NAME / SKILL_KEY).resolve()
    plan = {"source": str(source), "editable": [SKILL_KEY], "rounds": args.rounds,
            "workers": args.workers, "max_concurrency": args.max_concurrency,
            "offline": args.offline_demo, "apply": args.apply,
            "selection": "success_then_speed",
            "flow": "run -> reward -> tree_reflector -> Aggregator -> Ledger -> paired test -> optional Git adoption"}
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return plan
    # 1. 检查配置，读取原始 Skill、任务划分和源仓库信息
    initial, splits, source_info, source_guard = _load_inputs(args, source)
    #4. 创建实验目录，保存原始版本
    run_id, records, workspace = _start_run(args, plan, initial, splits, source_info)
    #从记录器里取出实验目录
    root = records.root
    #5. 创建 Skill 修改策略，限制每次修改的文件大小
    strategy = LoggedFileTree(initial, records, max_file_bytes=MAX_SKILL_BYTES)
    #6. 创建任务执行器和用量统计器
    runner = TrialRunner(records, workspace, server_url=args.server,
                         innovus=args.innovus, timeout=args.trial_timeout,
                         verifier_timeout=args.verifier_timeout, concurrency=args.max_concurrency,
                         offline=args.offline_demo, source_guard=source_guard,
                         secret_env=(args.api_key_env,))
    #统计修改 Skill 的模型调用，模型调用用量统计器
    usage = Usage()
    try:
        #7. 创建“怎样提出改进”的函数
        propose = _build_proposer(args, strategy, usage)
        selection = SuccessThenSpeed(runner, splits["val"], records)
        # Test tasks stay outside evolve; only train and val guide the search.
        #调用 evolve()，开始真正的多轮演化
        result = evolve(
            splits["train"] + splits["val"], reward, run=runner,
            propose=records.wrap_propose(propose), strategy=strategy,
            artifact_id="pdweaver-skill", repo_path=str(root / "ledger"),
            rounds=args.rounds, n_workers=args.workers, max_concurrency=args.max_concurrency,
            eval_concurrency=args.max_concurrency, self_verify=False, shuffle=False,
            # PASS 仍保留为 1；阈值高于 1，使成功任务也能提出提速修改。
            solved_threshold=1.1,
            policies=Policies(conflict=selection, acceptance=selection),
            held_out_frac=len(splits["val"]) / (len(splits["train"]) + len(splits["val"])),
            # 所有候选用同一完整验证集比较，避免不同题目/抽样影响速度排序。
            cheap_eval_tasks=len(splits["val"]), max_rollouts=args.max_rollouts,
            max_worker_errors=1, seed=args.seed, usage=usage,
            agg_config=AggregatorConfig(batch_trigger=1, max_wait_rounds=1,
                                        trust_region_ops=1, trust_region_chars=MAX_SKILL_BYTES,
                                        fusion_tournament=False, bounded_gate=False),
            record_trajectories=True, on_reports=records.on_reports, on_round=records.on_round,
            stop_when=lambda info: bool(runner.failures), verbose=False,
        )
        #9. 保存搜索结果，并关联实际 Git 历史
        result.save(str(root / "evolution.json"))
        records.link_ledger(root / "ledger", "pdweaver-skill")
        records.assert_healthy()
        #10. 检查实验是否完整，再保存最终候选
        if result.error or runner.failures:
            raise RuntimeError("incomplete evolution: {} / infra trials {}".format(result.error, runner.failures))
        records.write_text(f"candidate/{SKILL_KEY}", result.state[SKILL_KEY])
        #11. 用测试集比较“最初原版”和“最终版”
        assessment = evaluate_final(runner, strategy, initial, result.state, splits["test"],
                                    min_gain=args.min_test_gain)
        assessment.update(candidate_sha256=digest(result.state[SKILL_KEY]), baseline_sha256=source_info["sha256"])
        records.write_json("final_evaluation.json", assessment)
        records.assert_healthy()
        #12. 保存实验摘要，固定证据文件
        summary = {"run_id": run_id, "output": str(root), "offline": args.offline_demo,
                   "final_reward": result.final_reward, "test_passed": assessment["passed"],
                   "test_speed_improved": assessment["speed_improved"],
                   "adoption_eligible": assessment["adoption_eligible"], "status": "evaluated"}
        records.write_json("summary.json", summary)
        from .release import seal_evidence
        seal_evidence(root)
        #13. 根据 --apply 决定是否写回
        if args.apply:
            from .release import apply_run
            summary["adoption"] = apply_run(root)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary
    #14. 中途出错时，保存失败记录
    except Exception as exc:
        records.write_json("failure.json", {"type": type(exc).__name__,
                           "message": "experiment incomplete; inspect recorded trials, proposals and stderr",
                           "infra_trials": runner.failures})
        raise


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        run_experiment(args)
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print("PDWeaver RSI: {}".format(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
