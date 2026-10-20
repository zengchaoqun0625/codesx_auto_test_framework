# -*- coding: utf-8 -*-
"""报告年度/手动归档脚本（半自动，默认只复制不删除）

把当前所有报告产物（HTML 快照 + jsonl 明细 + 最新 Allure 压缩包）
复制到归档目录 archive/YYYY-MM-DD/，用于年度存档。

用法：
    python api_project/config/archive_reports.py --dry-run   # 仅预览将归档哪些文件
    python api_project/config/archive_reports.py             # 归档（不删除任何源文件）
    python api_project/config/archive_reports.py --clean     # 归档成功后删除 jsonl（重置历史）
    python api_project/config/archive_reports.py --dest my_archive   # 自定义归档根目录
    python api_project/config/archive_reports.py --no-allure        # 不归档 Allure 压缩包

安全原则：
    - 默认只复制，绝不删除任何源文件；
    - --clean 仅在全部文件复制成功后才删除 jsonl（performance_history.jsonl / run_history.jsonl）；
    - 任一文件复制失败即中止，且不会删除任何源文件。
"""
import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 待归档文件：源路径（相对项目根）→ 归档后的文件名（None 表示保持原名）
ARCHIVE_FILES = {
    "api_project/history/summary_report.html": None,
    "api_project/history/performance_report.html": None,
    "api_project/history/trend_report.html": None,
    "api_project/history/run_history.jsonl": None,
    "api_project/history/performance_history.jsonl": None,
}

# 复制成功后允许删除的数据源文件（仅 --clean 时）
CLEANABLE_FILES = [
    "api_project/history/run_history.jsonl",
    "api_project/history/performance_history.jsonl",
]

# 最新 Allure 压缩包匹配模式（取最新的一个）
ALLURE_ZIP_GLOB = "api_project/report/allure_report_*.zip"


def _find_latest_allure_zip():
    """返回最新一个 Allure 压缩包路径；不存在则返回 None。"""
    zips = sorted(PROJECT_ROOT.glob(ALLURE_ZIP_GLOB))
    return zips[-1] if zips else None


def _next_archive_dir(dest_root: Path, stamp: str) -> Path:
    """目标目录：archive/YYYY-MM-DD，同日多次归档自动追加序号。"""
    base = dest_root / stamp
    if not base.exists():
        return base
    for i in range(1, 1000):
        candidate = dest_root / f"{stamp}_{i:02d}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("归档目录序号已用尽，请清理后重试")


def main():
    parser = argparse.ArgumentParser(description="报告归档脚本（默认只复制不删除）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际复制")
    parser.add_argument("--clean", action="store_true", help="归档成功后删除 jsonl 数据源（重置历史）")
    parser.add_argument("--dest", default="archive", help="归档根目录（相对项目根，默认 archive）")
    parser.add_argument("--no-allure", action="store_true", help="不归档 Allure 压缩包")
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y-%m-%d")
    dest_root = PROJECT_ROOT / args.dest
    dest_dir = _next_archive_dir(dest_root, stamp)

    # ---- 收集待归档文件 ----
    plan = []
    for rel_src, rename in ARCHIVE_FILES.items():
        src = PROJECT_ROOT / rel_src
        if not src.exists():
            print(f"  ⚠️ 跳过（不存在）: {rel_src}")
            continue
        plan.append((src, src.name if rename is None else rename))
    allure_zip = None if args.no_allure else _find_latest_allure_zip()
    if allure_zip:
        plan.append((allure_zip, allure_zip.name))

    if not plan:
        print("❌ 没有可归档的文件，退出")
        return 1

    print("=" * 56)
    print(f"📦 报告归档预览" if args.dry_run else f"📦 报告归档")
    print("=" * 56)
    total_size = 0
    for src, name in plan:
        size = src.stat().st_size
        total_size += size
        print(f"  → {name}  ({size / 1024 / 1024:.2f} MiB)")
    print(f"目标目录: {dest_dir.relative_to(PROJECT_ROOT)}")
    print(f"合计: {len(plan)} 个文件, {total_size / 1024 / 1024:.2f} MiB")

    if args.dry_run:
        print("\n[dry-run] 未执行任何复制/删除。")
        return 0

    # ---- 复制 ----
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"❌ 创建归档目录失败: {exc}")
        return 1

    copied = []
    for src, name in plan:
        try:
            shutil.copy2(src, dest_dir / name)
            copied.append(src)
            print(f"  ✅ {name}")
        except OSError as exc:
            print(f"  ❌ 复制失败 {src.name}: {exc}")
            print("  已中止，未删除任何源文件。")
            return 1

    print(f"\n✅ 归档完成: {dest_dir.relative_to(PROJECT_ROOT)} ({len(copied)} 个文件)")

    # ---- 可选清理 ----
    if args.clean:
        removed = []
        for rel in CLEANABLE_FILES:
            src = PROJECT_ROOT / rel
            if src.exists():
                src.unlink()
                removed.append(rel)
        if removed:
            print("🧹 已删除 jsonl 数据源（历史归零，下一轮执行自动重建）:")
            for rel in removed:
                print(f"  - {rel}")
        else:
            print("🧹 没有需要删除的 jsonl 数据源。")
    else:
        print("\n💡 提示: 如需归档后重置历史，加 --clean 参数（会删除 jsonl 数据源）。")
        print("   HTML 报告不会被删除，可自行决定是否保留。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
