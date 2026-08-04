#!/usr/bin/env python3
"""
读取最新的 scroll-diagnostics-*.jsonl 文件并分析 macOS 滚动抖动原因。

用法：
    python analyze_scroll_diag.py [diagnostics_file.jsonl]

    不传参数时自动选择 ~/Library/Application Support/DocMask/diagnostics/ 下最新的文件。
"""
from __future__ import annotations

import json
import sys
import os
from pathlib import Path
from collections import defaultdict
from typing import Any


def find_latest() -> Path | None:
    """定位最新的诊断文件。"""
    candidates = [
        Path.home() / "Library" / "Application Support" / "DocMask" / "diagnostics",
        Path(os.environ.get("LOCALAPPDATA", "")) / "DocMask" / "diagnostics"
        if sys.platform == "win32" else None,
        Path.home() / ".local" / "share" / "docmask" / "diagnostics",
    ]
    for d in candidates:
        if not d or not d.is_dir():
            continue
        files = sorted(d.glob("scroll-diagnostics-*.jsonl"))
        if files:
            return files[-1]
    return None


def load(path: Path) -> list[dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    # ── 基本统计 ──
    by_source = defaultdict(int)
    by_widget = defaultdict(int)
    by_frame = defaultdict(int)
    frame_events: dict[int, list[dict]] = defaultdict(list)

    for r in rows:
        by_source[r.get("source", "?")] += 1
        by_widget[r.get("widget_class", "?")] += 1
        fid = r.get("frame_id", 0)
        by_frame[fid] += 1
        frame_events[fid].append(r)

    # ── 分析 applied 事件的 yview 序列（按 frame） ──
    yview_issues: list[dict] = []
    boundary_oscillations: list[dict] = []

    for fid, events in frame_events.items():
        applied_events = [e for e in events if e.get("source") == "applied"]
        boundary_events = [e for e in events if e.get("source") == "boundary"]

        # 检查 yview 是否单调（同方向）
        prev_y = None
        prev_dir = None
        reversals = 0
        for e in applied_events:
            y = e.get("y_after", [0, 1])
            y0 = y[0] if isinstance(y, list) and len(y) == 2 else 0
            direction = "down" if e.get("applied_units", 0) > 0 else "up"

            if prev_y is not None and prev_dir != direction:
                # 方向反转，且不是从底部回弹的正常情况
                if not (prev_dir == "down" and prev_y >= 0.98 and direction == "up"):
                    if not (prev_dir == "up" and prev_y <= 0.001 and direction == "down"):
                        reversals += 1
                        yview_issues.append({
                            "frame_id": fid,
                            "type": "direction_reversal",
                            "prev_yview": prev_y,
                            "prev_dir": prev_dir,
                            "curr_yview": y0,
                            "curr_dir": direction,
                            "applied_units": e.get("applied_units"),
                        })
            prev_y = y0
            prev_dir = direction

        # 检查边界震荡（同一 frame 短时间内多次到达同一边界）
        boundary_times = []
        for e in boundary_events:
            boundary_times.append((e.get("ts", 0), e.get("boundary"), e.get("y_view", (0, 1))))

        # 检测 1 秒内同一边界方向出现 > 3 次
        boundary_times.sort(key=lambda x: x[0])
        for i in range(len(boundary_times) - 3):
            window = boundary_times[i:i + 4]
            # 纳秒 → 秒，检查时间窗口
            if (window[-1][0] - window[0][0]) < 1_000_000_000:  # 1 second
                boundaries = [b[1] for b in window]
                if len(boundaries) >= 3:
                    boundary_oscillations.append({
                        "frame_id": fid,
                        "count": len(window),
                        "boundaries": boundaries,
                        "y_views": [b[2] for b in window],
                    })
                    break  # 只报告一次

    # ── 检查是否有多个 frame 同时活跃 ──
    # 按时间线合并所有 applied 事件
    all_applied = []
    for r in rows:
        if r.get("source") == "applied":
            all_applied.append((r.get("ts", 0), r.get("frame_id", 0)))
    all_applied.sort(key=lambda x: x[0])

    multi_frame_issues = []
    for i in range(1, len(all_applied)):
        ts_diff = all_applied[i][0] - all_applied[i - 1][0]
        if ts_diff < 50_000_000 and all_applied[i][1] != all_applied[i - 1][1]:
            multi_frame_issues.append({
                "frame_a": all_applied[i - 1][1],
                "frame_b": all_applied[i][1],
                "interval_ns": ts_diff,
            })
    # 去重
    seen = set()
    unique_multi = []
    for issue in multi_frame_issues:
        key = (issue["frame_a"], issue["frame_b"])
        if key not in seen:
            seen.add(key)
            unique_multi.append(issue)

    # ── 摘要 ──
    total = len(rows)
    mouse_wheel_count = by_source.get("mouse_wheel", 0)
    applied_count = by_source.get("applied", 0)
    boundary_count = by_source.get("boundary", 0)
    merge_ratio = applied_count / max(mouse_wheel_count, 1)  # 合并效率

    return {
        "file": None,
        "total_events": total,
        "by_source": dict(by_source),
        "by_widget_class": dict(by_widget),
        "by_frame": {str(k): v for k, v in by_frame.items()},
        "mouse_wheel_events": mouse_wheel_count,
        "applied_scrolls": applied_count,
        "boundary_hits": boundary_count,
        "merge_ratio": merge_ratio,
        "yview_direction_reversals": yview_issues,
        "boundary_oscillations": boundary_oscillations,
        "multi_frame_conflicts": unique_multi,
    }


def print_report(result: dict[str, Any]) -> None:
    print("=" * 60)
    print(f"滚动诊断分析报告")
    print(f"文件: {result.get('file', 'N/A')}")
    print(f"总事件数: {result['total_events']}")
    print()

    print("── 事件来源分布 ──")
    for src, count in sorted(result["by_source"].items(), key=lambda x: -x[1]):
        print(f"  {src:20s} {count:>6d}")

    print()
    print(f"  mouse_wheel     {result['mouse_wheel_events']:>6d}  (原始触摸板事件)")
    print(f"  applied         {result['applied_scrolls']:>6d}  (实际执行的滚动)")
    print(f"  合并比          {result['merge_ratio']:.2f}x  (原始事件数 / 实际滚动数)")

    print()
    print("── 控件类型（触摸板事件时鼠标下的控件） ──")
    for cls, count in sorted(result["by_widget_class"].items(), key=lambda x: -x[1])[:10]:
        print(f"  {cls:30s} {count:>6d}")

    print()
    print("── 滚动容器分布（frame_id）──")
    for fid, count in sorted(result["by_frame"].items(), key=lambda x: -int(x[1])):
        print(f"  {fid:18s} {count:>6d} 次")

    # ── 关键发现 ──
    reversals = result["yview_direction_reversals"]
    oscillations = result["boundary_oscillations"]
    multi_frame = result["multi_frame_conflicts"]

    print()
    print("=" * 60)
    print("关键发现")

    if reversals:
        print(f"\n  [!!] Y 方向反转: {len(reversals)} 次")
        print(f"       滚动过程中 yview 值非单调变化（前后方向不一致）")
        for rev in reversals[:5]:
            print(f"       frame={rev['frame_id']}  {rev['prev_dir']}→{rev['curr_dir']}  "
                  f"yview: {rev['prev_yview']:.4f} → {rev['curr_yview']:.4f}  "
                  f"units={rev['applied_units']}")
        if len(reversals) > 5:
            print(f"       ... 还有 {len(reversals) - 5} 次")
    else:
        print(f"\n  [OK] Y 方向反转: 0 次 — yview 值始终单调")

    if oscillations:
        print(f"\n  [!!] 边界震荡: {len(oscillations)} 组（持续打底/打顶）")
        for osc in oscillations[:3]:
            print(f"       frame={osc['frame_id']}  {osc['count']} 次连续 {osc['boundaries']}")
    else:
        print(f"\n  [OK] 边界震荡: 0 组")

    if multi_frame:
        print(f"\n  [!!] 多容器同时响应同一次鼠标事件: {len(multi_frame)} 种冲突")
        for mf in multi_frame[:5]:
            print(f"       frame {mf['frame_a']} ↔ {mf['frame_b']}  间隔 {mf['interval_ns'] / 1e6:.1f}ms")
    else:
        print(f"\n  [OK] 多容器冲突: 0 — 每次事件只路由到一个滚动容器")

    # ── 诊断结论 ──
    print()
    print("=" * 60)
    print("诊断结论")

    if reversals:
        print("  1. 存在 yview 方向反转 — 滚动画面出现前后跳动。")
        print("     可能原因: pending_delta 取整丢失方向信息；")
        print("     scrollregion 在滚动期间发生变化。")
    if oscillations:
        print("  2. 存在边界震荡 — 底部/顶部反复切换。")
        print("     可能原因: yview bottom 值在 0.98~1.0 之间来回；")
        print("     边界判断阈值不够宽；触摸板惯性末端的微小区间。")
    if multi_frame:
        print("  3. 存在多容器冲突 — 多个 PageScrollFrame 同时响应滚轮。")
        print("     可能原因: 当前可见的两个页面的 pack_forget 未生效；")
        print("     或祖先链查找返回了错误容器。")
    if not reversals and not oscillations and not multi_frame:
        print("  未发现明显抖动特征。如果仍感到卡顿，可能原因：")
        print("  - Canvas 重绘性能瓶颈（大量子控件的 Configure 回调）")
        print("  - Tk 主线程被其他操作阻塞（大文件扫描、图标渲染等）")
        print("  - 建议延长使用时间、扩大样本量后重新分析")


def main():
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if not path.exists():
            print(f"文件不存在: {path}", file=sys.stderr)
            sys.exit(1)
    else:
        path = find_latest()
        if path is None:
            print("未找到诊断文件。请先启动 UI 并执行滚动操作。", file=sys.stderr)
            print(f"预期位置: {Path.home()}/Library/Application Support/DocMask/diagnostics/", file=sys.stderr)
            sys.exit(1)

    print(f"加载: {path}")
    rows = load(path)
    if not rows:
        print("文件为空。", file=sys.stderr)
        sys.exit(1)

    result = analyze(rows)
    result["file"] = str(path)
    print_report(result)


if __name__ == "__main__":
    main()
