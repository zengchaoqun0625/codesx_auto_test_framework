# -*- coding: utf-8 -*-
"""按目录容量清理测试运行产生的数据与日志。

规则：目录超过上限后，按文件最后修改时间从旧到新删除，直至降到保留容量。
仅删除目标目录内的普通文件；不删除目录、不跟随符号链接，并保护 scheduler.log。
"""
import argparse
import logging
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_TARGETS = (PROJECT_ROOT / "api_project" / "data", PROJECT_ROOT / "api_project" / "log")
PROTECTED_NAMES = {"scheduler.log"}
MIB = 1024 * 1024


def build_logger():
    logger = logging.getLogger("storage_cleanup")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
    return logger


def get_files(target: Path):
    """返回目录内的普通文件（不递归、不包含受保护文件）。"""
    if not target.is_dir():
        return []
    files = []
    for item in target.iterdir():
        try:
            if item.is_file() and not item.is_symlink() and item.name not in PROTECTED_NAMES:
                files.append(item)
        except OSError:
            continue
    return files


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def cleanup_target(target: Path, max_bytes: int, retain_bytes: int, dry_run: bool, logger):
    files = get_files(target)
    total = sum(file_size(path) for path in files)
    logger.info("目录 [%s] 当前 %.2f MiB，上限 %.2f MiB", target, total / MIB, max_bytes / MIB)
    if total <= max_bytes:
        logger.info("目录 [%s] 未超过上限，无需清理", target)
        return 0, 0

    removed_count = 0
    removed_bytes = 0
    for path in sorted(files, key=lambda item: item.stat().st_mtime if item.exists() else 0):
        if total <= retain_bytes:
            break
        size = file_size(path)
        if dry_run:
            logger.info("[预览] 删除最旧文件: %s (%.2f MiB)", path, size / MIB)
        else:
            try:
                path.unlink()
                logger.info("已删除最旧文件: %s (%.2f MiB)", path, size / MIB)
            except OSError as exc:
                logger.warning("删除失败，跳过 [%s]: %s", path, exc)
                continue
        total -= size
        removed_count += 1
        removed_bytes += size

    action = "计划释放" if dry_run else "已释放"
    logger.info("目录 [%s] %s %.2f MiB，共 %d 个文件；预计剩余 %.2f MiB",
                target, action, removed_bytes / MIB, removed_count, total / MIB)
    return removed_count, removed_bytes


def main():
    parser = argparse.ArgumentParser(description="按容量清理 api_project/data 与 api_project/log")
    parser.add_argument("--max-mb", type=float, default=100, help="触发清理的容量上限，默认 100 MiB")
    parser.add_argument("--retain-mb", type=float, default=80, help="清理后的保留容量，默认 80 MiB")
    parser.add_argument("--dry-run", action="store_true", help="仅预览待删除文件，不实际删除")
    parser.add_argument("--target", action="append", help="指定清理目录，可重复传入；默认 data 和 log")
    args = parser.parse_args()

    logger = build_logger()
    if args.max_mb <= 0 or args.retain_mb < 0 or args.retain_mb >= args.max_mb:
        parser.error("必须满足：max-mb > retain-mb >= 0")

    targets = [Path(value).resolve() for value in args.target] if args.target else DEFAULT_TARGETS
    max_bytes = int(args.max_mb * MIB)
    retain_bytes = int(args.retain_mb * MIB)
    logger.info("存储清理开始：模式=%s，超过 %.2f MiB 后清至 %.2f MiB",
                "预览" if args.dry_run else "执行", args.max_mb, args.retain_mb)
    for target in targets:
        cleanup_target(target, max_bytes, retain_bytes, args.dry_run, logger)
    logger.info("存储清理结束")


if __name__ == "__main__":
    main()
