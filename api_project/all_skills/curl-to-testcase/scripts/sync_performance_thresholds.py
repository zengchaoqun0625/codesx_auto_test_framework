# -*- coding: utf-8 -*-
"""由 case_data_files 接口参数文件同步性能阈值规则。"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_THRESHOLD_SEC = 5.0


def normalize_path(value):
    """提取 URL 路径，兼容完整 URL 和相对路径。"""
    text = str(value or "").strip().strip("'\"")
    if not text:
        return ""
    parsed = urlparse(text)
    path = parsed.path if parsed.scheme or parsed.netloc else text.split("?", 1)[0]
    return path if path.startswith("/") else f"/{path}"


def iter_case_entries(data):
    """递归查找同时包含 url / method 的请求数据，兼容转换器不同 JSON 结构。"""
    if isinstance(data, dict):
        if data.get("url") and data.get("method"):
            yield data
        for value in data.values():
            yield from iter_case_entries(value)
    elif isinstance(data, list):
        for value in data:
            yield from iter_case_entries(value)


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[WARN] 跳过不可解析文件: {path.name} ({exc})")
        return None


def main():
    parser = argparse.ArgumentParser(description="从 case_data_files 同步性能阈值规则")
    parser.add_argument("--case-dir", default="api_project/case_data_files", help="接口参数 JSON 目录")
    parser.add_argument("--output", default="api_project/config/performance_thresholds.json", help="性能阈值配置输出路径")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD_SEC, help="新增接口默认阈值（秒）")
    args = parser.parse_args()

    if args.threshold <= 0:
        raise SystemExit("[ERROR] --threshold 必须大于 0")

    case_dir = Path(args.case_dir)
    output = Path(args.output)
    endpoints = set()
    for path in sorted(case_dir.glob("*.json")):
        data = load_json(path)
        if data is None:
            continue
        for entry in iter_case_entries(data):
            endpoint_path = normalize_path(entry.get("url"))
            method = str(entry.get("method", "")).upper().strip()
            if endpoint_path and method:
                endpoints.add((method, endpoint_path))

    existing = {}
    if output.exists():
        try:
            existing = json.loads(output.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                raise ValueError("根节点必须是对象")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"[WARN] 既有配置无法解析，将重新生成: {exc}")
            existing = {}

    old_rules = existing.get("rules", [])
    old_rules = old_rules if isinstance(old_rules, list) else []
    generated_by_endpoint = {
        str(rule.get("endpoint_contains", "")).strip()
        for rule in old_rules
        if isinstance(rule, dict) and rule.get("generated_by") == "curl-to-testcase"
    }
    manual_rules = [
        rule for rule in old_rules
        if not (isinstance(rule, dict) and rule.get("generated_by") == "curl-to-testcase")
    ]
    generated_rules = [
        {
            "name": f"{method} {endpoint_path}",
            "endpoint_contains": endpoint_path,
            "method": method,
            "threshold_sec": args.threshold,
            "enabled": True,
            "generated_by": "curl-to-testcase",
        }
        for method, endpoint_path in sorted(endpoints)
    ]

    # 将自动生成规则置于手工规则之后：既有手工规则仍可按数组顺序优先覆盖同一接口。
    config = {
        "enabled": True,
        "default_threshold_sec": args.threshold,
        "rules": manual_rules + generated_rules,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] 扫描接口: {len(endpoints)} 个")
    print(f"[OK] 写入规则: {len(generated_rules)} 条（全部 enabled=true，阈值 {args.threshold:g}s）")
    if generated_by_endpoint - {path for _, path in endpoints}:
        print(f"[INFO] 已移除 {len(generated_by_endpoint - {path for _, path in endpoints})} 条不再对应参数文件的自动规则")
    print(f"[OK] 配置文件: {output}")


if __name__ == "__main__":
    main()
