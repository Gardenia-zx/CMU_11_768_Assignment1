"""Recompute saved experiment metrics and README figures without API calls.

python scripts/analyze_results.py --artifacts /path/to/saved/artifacts
python scripts/analyze_results.py  # redraw from the published numeric summary
Only figure rendering needs matplotlib; aggregation uses the standard library.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics

ROOT = Path(__file__).resolve().parents[1]
RUNS = {
    "part1": ("part1-trajectory.json", None),
    "part2_baseline": ("django__django-15368-baseline-trajectory.json", None),
    "part2_compact": ("django__django-15368-trajectory.json", None),
    "part3_no_legal": ("part3-no-legal-moves-deepseek.json", "part3-no-legal-moves-deepseek-result.json"),
    "part3_legal": ("part3-legal-moves-deepseek.json", "part3-legal-moves-deepseek-result.json"),
    "part3_original": ("part3-trajectory.json", "game-result.json"),
    "part3_v2": ("part3-v2-trajectory.json", "game-result-v2.json"),
    "part3_activity": ("part3-v2-activity-trajectory.json", "game-result-v2-activity.json"),
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def source(path):
    return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def usage(response):
    u = response["usage"]
    row = {k: u[v] for k, v in {
        "input": "prompt_tokens", "output": "completion_tokens",
        "total": "total_tokens", "cached": "prompt_cache_hit_tokens",
        "miss": "prompt_cache_miss_tokens",
    }.items()}
    row["reasoning"] = u["completion_tokens_details"]["reasoning_tokens"]
    if any(type(v) is not int or v < 0 for v in row.values()):
        raise ValueError("Missing or invalid token usage; unknown is not zero")
    if (row["input"] != row["cached"] + row["miss"]
            or row["total"] != row["input"] + row["output"]
            or row["reasoning"] > row["output"]
            or u["prompt_tokens_details"]["cached_tokens"] != row["cached"]):
        raise ValueError("Inconsistent usage fields")
    return row


def aggregate(rows):
    result = {key: sum(r[key] for r in rows)
              for key in ("input", "output", "total", "cached", "miss", "reasoning")}
    result.update(requests=len(rows),
                  cache_rate=result["cached"] / result["input"] if result["input"] else None,
                  mean_input=result["input"] / len(rows) if rows else None,
                  peak_input=max((r["input"] for r in rows), default=None))
    return result


def analyze(path, result_path=None):
    data = read_json(path)
    responses = data["responses"]
    if not responses or len(data["prompts"]) != len(responses):
        raise ValueError(f"Unaligned trajectory: {path.name}")
    actions = [usage(r) for r in responses]
    summaries = [usage(e["compaction_response"]) for e in data["compactions"]]
    calls = [t for r in responses for t in (r["choices"][0]["message"].get("tool_calls") or [])]
    # Prompts contain repeated history. Count each linked observation once.
    observations = {}
    for prompt in data["prompts"]:
        for message in prompt:
            if message["role"] == "tool":
                key = message["tool_call_id"]
                if key in observations and observations[key] != message["content"]:
                    raise ValueError(f"Conflicting observation: {key}")
                observations[key] = message["content"]
    events = [{"completed_action": e["step"],
               "rough_before": e["estimated_tokens_before"],
               "rough_after": e["estimated_tokens_after"]} for e in data["compactions"]]
    if any(not 0 < e["rough_after"] < e["rough_before"] for e in events):
        raise ValueError("Compaction failed to reduce the rough context estimate")
    post_steps = {e["completed_action"] + 1 for e in events}
    if len(post_steps) != len(events):
        raise ValueError("Duplicate compaction boundaries")
    tz = timezone(timedelta(hours=8))
    result = {
        "source": source(path), "models": sorted({r["model"] for r in responses}),
        "first_response_shanghai": datetime.fromtimestamp(responses[0]["created"], tz).isoformat(),
        "last_response_shanghai": datetime.fromtimestamp(responses[-1]["created"], tz).isoformat(),
        "response_created_span_seconds": responses[-1]["created"] - responses[0]["created"],
        "action": aggregate(actions), "summary": aggregate(summaries),
        "total": aggregate(actions + summaries),
        "tool_calls": dict(Counter(t["function"]["name"] for t in calls)),
        "finish_reasons": dict(Counter(r["choices"][0]["finish_reason"] for r in responses)),
        "observed_tool_returns": len(observations),
        "observed_chess_error_returns": sum("<chess_error>" in c for c in observations.values()),
        "compaction_events": events,
        "after_compaction": aggregate([r for i, r in enumerate(actions, 1) if i in post_steps]),
        "other_actions": aggregate([r for i, r in enumerate(actions, 1) if i not in post_steps]),
        "max_output": max(r["output"] for r in actions),
    }
    if events:
        reductions = [1 - e["rough_after"] / e["rough_before"] for e in events]
        result["rough_compaction_reduction"] = {
            "mean": statistics.mean(reductions), "median": statistics.median(reductions),
            "min": min(reductions), "max": max(reductions),
        }
    if result_path:
        state = read_json(result_path)
        white = [m for m in state["history"] if m["color"] == "white"]
        direct = [json.loads(t["function"]["arguments"])["move"]
                  for t in calls if t["function"]["name"] == "play_move"]
        if direct and all(t["function"]["name"] == "play_move" for t in calls):
            if direct != [m["uci"] for m in white]:
                raise ValueError("Submitted moves do not match the saved game history")
            result["direct_moves_match_history"] = True
        result["game"] = {
            "source": source(result_path), "game_over": state["game_over"],
            "status": state["status"], "plies": len(state["history"]),
            "white_moves": len(white), "last_white_san": white[-1]["san"],
            "last_white_uci": white[-1]["uci"],
        }
    if path.name == "part1-trajectory.json":
        outputs = "\n".join(observations.values())
        matches = re.findall(r"(\d+) passed, (\d+) warning", outputs)
        if "500 Internal Server Error" not in outputs or not matches:
            raise ValueError("Expected Part 1 reproduction or test evidence is missing")
        result["repair_evidence"] = {
            "before_http_status": 500, "after_http_status": 200,
            "sandbox_tests_passed": int(matches[-1][0]), "warnings": int(matches[-1][1]),
            "scope": "Saved in-agent sandbox output; separate check-part1 log unavailable",
        }
        if not re.search(r"<stdout>200\s+\{", outputs):
            raise ValueError("Part 1 HTTP 200 evidence missing")
    return result


def render(runs, directory):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    for path in (Path("C:/Windows/Fonts/msyh.ttc"), Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")):
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=path).get_name()
            break
    plt.rcParams.update({"font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
                         "text.color": "#182B45", "axes.labelcolor": "#51627A",
                         "xtick.color": "#51627A", "ytick.color": "#51627A",
                         "axes.unicode_minus": False, "figure.facecolor": "#F4F7FC",
                         "savefig.facecolor": "#F4F7FC"})
    navy, blue, teal, amber, pale = "#263D63", "#537CE7", "#15A99B", "#E6A34B", "#D7E0EE"
    directory.mkdir(parents=True, exist_ok=True)

    def figure(title, subtitle, nrows=1, ncols=2, height=5.5):
        fig, axes = plt.subplots(nrows, ncols, figsize=(14, height), squeeze=False)
        fig.suptitle(title, x=.055, y=.98, ha="left", fontsize=19, weight="bold")
        fig.text(.055, .875 if nrows == 1 else .915, subtitle, fontsize=10, color="#51627A")
        for ax in axes.flat:
            ax.set_facecolor("white")
            ax.spines[["top", "right", "left"]].set_visible(False)
            ax.spines["bottom"].set_color(pale)
            ax.tick_params(axis="both", length=0, pad=9)
            ax.grid(axis="y", color="#E6EBF3", linewidth=.7)
            ax.set_axisbelow(True)
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        fig.subplots_adjust(top=.77 if nrows == 1 else .82, bottom=.19 if nrows == 1 else .15,
                            left=.10, right=.97, wspace=.30, hspace=.70)
        return fig, list(axes.flat)

    def bars(ax, labels, values, title, unit="", colors=None, fmt=None):
        items = ax.bar(labels, values, width=.5, color=colors or [blue, teal], zorder=3)
        ax.set_title(title, loc="left", pad=17)
        ax.set_ylabel(unit)
        ax.set_ylim(0, max(values, default=1) * 1.22 or 1)
        ax.bar_label(items, labels=[fmt(v) if fmt else f"{v:,.0f}" for v in values],
                     padding=7, fontsize=10, weight="bold", color=navy)

    def save(fig, name, footnote):
        fig.text(.055, .035, footnote, fontsize=9, color="#6E7F94")
        fig.savefig(directory / name, dpi=190)
        plt.close(fig)

    p = runs["part1"]
    fig, ax = figure("01 / Part 1 · Coding agent", "单次修复轨迹 · 请求预算与工具使用")
    bars(ax[0], ["execute", "invoke_skill", "send_message"], [p["tool_calls"][k] for k in ("execute", "invoke_skill", "send_message")], "工具调用次数", "calls", [blue, teal, amber])
    labels = ["缓存输入", "未缓存输入", "输出"]
    bars(ax[1], labels, [p["total"][k] for k in ("cached", "miss", "output")], "Token 构成", "tokens", [blue, teal, amber])
    save(fig, "part1-overview.png", f"来源：part1-trajectory.json · HTTP 500 → 200；保存的沙箱测试输出：{p['repair_evidence']['sandbox_tests_passed']} passed · 不代表独立评测日志")

    b, c = runs["part2_baseline"], runs["part2_compact"]
    token_reduction = 100 * (1 - c['total']['total'] / b['total']['total'])
    fig, ax = figure("02 / Part 2 · Context budget", f"计入全部摘要调用后，总 tokens 减少 {token_reduction:.2f}% · 每种条件各一次运行", 2, 2, 8.5)
    bars(ax[0], ["Full context", "Compaction"], [b["total"]["total"], c["total"]["total"]], "累计总 tokens（含摘要）", "tokens")
    bars(ax[1], ["Full context", "Compaction"], [b["action"]["mean_input"], c["action"]["mean_input"]], "Action 平均输入", "tokens / request", fmt=lambda v:f"{v:,.2f}")
    bars(ax[2], ["Full context", "Compaction"], [b["action"]["peak_input"], c["action"]["peak_input"]], "Action 峰值输入", "tokens")
    for key, color, label, bottom in [("action", blue, "Action", [0, 0]), ("summary", teal, "Summary", [b["action"]["requests"], c["action"]["requests"]])]:
        values = [b[key]["requests"], c[key]["requests"]]
        items = ax[3].bar(["Full context", "Compaction"], values, bottom=bottom, color=color, width=.5, label=label, zorder=3)
        ax[3].bar_label(items, labels=[str(v) if v else "" for v in values], label_type="center", color="white", weight="bold")
    ax[3].set_title("模型请求次数：Action + Summary", loc="left", pad=17)
    ax[3].set_ylabel("requests")
    ax[3].set_ylim(0, 115)
    ax[3].legend(frameon=False, loc="upper left")
    save(fig, "part2-budget.png", "usage = 输入 + 输出；reasoning 已包含在输出中 · 阈值是触发条件，不是单次输入的硬上限")

    fig, ax = figure("03 / Part 2 · Cache & summary overhead", "压缩缩短上下文，同时改变可复用的输入前缀 · Token 数量与缓存率分别绘制", 2, 2, 8.5)
    bars(ax[0], ["Full context", "Compaction"], [100*b["total"]["cache_rate"], 100*c["total"]["cache_rate"]], "全部请求的加权缓存命中率", "%", fmt=lambda v:f"{v:.2f}%")
    ax[0].set_ylim(0, 115)
    bars(ax[1], ["Full context", "Compaction"], [b["total"]["miss"], c["total"]["miss"]], "未缓存输入", "tokens")
    bars(ax[2], ["摘要请求", "压缩后首个 Action", "其它 Action"], [100*c[k]["cache_rate"] for k in ("summary", "after_compaction", "other_actions")], "压缩版内部：加权缓存命中率", "%", [amber, blue, teal], lambda v:f"{v:.2f}%")
    ax[2].set_ylim(0, 100)
    bars(ax[3], ["Action", "Summary"], [c[k]["total"] for k in ("action", "summary")], "压缩版全部 tokens 的组成", "tokens", [blue, teal])
    summary_share = 100 * c['summary']['total'] / c['total']['total']
    save(fig, "part2-cache.png", f"缓存率 = Σ缓存输入 / Σ输入 · 摘要占压缩版总 tokens 的 {summary_share:.2f}% · 总 tokens 降低不能直接推出实际费用降低")

    fig, axes = figure("04 / Part 2 · Compaction events", f"{len(c['compaction_events'])} 次压缩都缩短活动上下文的本地 rough 估算 · 平均降幅 {100*c['rough_compaction_reduction']['mean']:.2f}%", ncols=1, height=5.8)
    ax = axes[0]
    ev = c["compaction_events"]
    xs = list(range(len(ev)))
    ax.bar([x-.19 for x in xs], [e["rough_before"] for e in ev], .38, color=blue, label="Before", zorder=3)
    ax.bar([x+.19 for x in xs], [e["rough_after"] for e in ev], .38, color=teal, label="After", zorder=3)
    ax.set_xticks(xs, [str(e["completed_action"]) for e in ev])
    ax.set_xlabel("压缩发生时已完成的 Action 编号")
    ax.set_ylabel("rough estimated tokens")
    ax.set_ylim(0, max(e["rough_before"] for e in ev)*1.2)
    ax.legend(frameon=False, loc="upper right", ncols=2)
    save(fig, "part2-events.png", "Before / After 与服务端 usage 口径不同；不将重复历史的逐次差值相加为账单节省")

    n, l = runs["part3_no_legal"], runs["part3_legal"]
    fig, ax = figure("05 / Part 3 · Legal-move observation A/B", "两局均为白方将死获胜；两组直接走法都与保存棋谱逐项一致 · n = 1 / condition", 2, 2, 8.5)
    labels = ["无合法走法列表", "有合法走法列表"]
    bars(ax[0], labels, [n["game"]["white_moves"], l["game"]["white_moves"]], "实际白棋步数", "moves")
    bars(ax[1], labels, [n["action"]["requests"], l["action"]["requests"]], "模型 Action 请求", "requests")
    bars(ax[2], labels, [n["total"]["input"], l["total"]["input"]], "累计输入（含重复历史）", "tokens")
    bars(ax[3], labels, [n["total"]["output"], l["total"]["output"]], "累计输出（含推理）", "tokens")
    input_reduction = 100 * (1 - l['total']['input'] / n['total']['input'])
    move_reduction = 100 * (1 - l['game']['white_moves'] / n['game']['white_moves'])
    save(fig, "part3-observation.png", f"有列表组输入减少 {input_reduction:.2f}%，白棋步数减少 {move_reduction:.2f}% · 两组均未压缩上下文 · 单局差异不等于稳定棋力提升")

    a, v, f = [runs[k] for k in ("part3_original", "part3_v2", "part3_activity")]
    fig, ax = figure("06 / Part 3 · Programmatic strategy iterations", "原始策略：和棋 · v2：保存时未终局 · 最终 activity 版：12 步白棋将死", 2, 2, 8.5)
    labels = ["Original\n和棋", "v2\n未终局", "v2 + activity\n白方获胜"]
    bars(ax[0], labels, [r["action"]["requests"] for r in (a,v,f)], "模型 Action 请求", "requests", [blue, amber, teal])
    bars(ax[1], labels, [r["game"]["white_moves"] for r in (a,v,f)], "保存棋谱中的白棋步数", "moves", [blue, amber, teal])
    bars(ax[2], labels, [r["total"]["total"] for r in (a,v,f)], "累计总 tokens", "tokens", [blue, amber, teal])
    bars(ax[3], labels, [r["total"]["total"]/r["game"]["white_moves"] for r in (a,v,f)], "总 tokens / 实际白棋步", "tokens / move", [blue, amber, teal])
    save(fig, "part3-strategies.png", "策略、tie-break 与轨迹长度同时变化；v2 在 200 次请求时尚未终局 · 此图比较单次记录，不表示胜率或受控因果效应")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, help="Directory containing the original saved experiment files")
    parser.add_argument("--summary", type=Path, default=ROOT / "reports/experiment-summary.json")
    parser.add_argument("--figures", type=Path, default=ROOT / "assets/figures")
    args = parser.parse_args()
    if args.artifacts:
        runs = {key: analyze(args.artifacts / trajectory, args.artifacts / state if state else None)
                for key, (trajectory, state) in RUNS.items()}
        payload = {"methodology": {
            "sample_size": "One saved run per condition; observational comparisons",
            "cache_rate": "sum(cached input tokens) / sum(input tokens)",
            "reasoning": "Included in output tokens; never add twice",
            "time": "First/last response-created timestamps; not complete runtime",
            "observations": "Deduplicated by tool_call_id; the final tool return may be absent",
            "part2_evaluation": "Previously reported passing by the user; separate evaluation logs unavailable",
            "part3_v2": "Nonterminal saved state; not a draw or a completed loss",
        }, "runs": runs}
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        runs = read_json(args.summary)["runs"]
    render(runs, args.figures)
    status = "Validated saved trajectories" if args.artifacts else "Loaded numeric summary"
    print(f"{status}: {len(runs)} runs. Summary: {args.summary}")
    print(f"Rendered 6 figures: {args.figures}")


if __name__ == "__main__":
    main()
