#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_doc.py - 从规范化的 apis.json 生成单文件 HTML 接口文档

用法:
    # 单次生成
    python generate_doc.py <apis.json> [-o output.html] [--title "标题"] [--source "来源"] [--theme dark|light]

    # 增量合并(多个输入按顺序合并去重, 后者非空字段覆盖前者)
    python generate_doc.py master.json batch2.json -o doc.html --save-master master.json

    # 从已有 HTML 反提取接口作为合并基线(master json 丢失时恢复用)
    python generate_doc.py batch2.json --from-html old-doc.html -o doc.html

apis.json 结构 (数组，每个元素为一个接口):
[
  {
    "name": "用户登录",                    # 必填，接口名称
    "method": "POST",                     # 必填，HTTP 方法
    "url": "https://api.example.com/login?from=app",  # 必填，完整 URL(可含 query)
    "description": "账号密码登录，返回 token",        # 可选，AI 根据路径/语义推断
    "tag": "用户模块",                     # 可选，缺省时按路径第一段自动分组
    "headers": [{"key": "Content-Type", "value": "application/json", "description": ""}],
    "params":  [{"key": "from", "value": "app", "required": false, "description": "来源"}],
    "body": {"username": "demo", "password": "***"},  # 可选，对象或字符串
    "bodyType": "application/json",        # 可选
    "response": {"code": 0, "data": {"token": "..."}},# 可选，响应示例
    "curl": "curl -X POST ..."             # 可选，缺省时由脚本自动重建
  }
]

去重规则: 以 method(大写) + path(query 去除、末尾斜杠归一) 作为同一接口的键。
增量合并时, 后输入文件的非空字段覆盖先输入的(便于用新抓包刷新 token/参数, 同时保留旧的 AI 描述)。
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qsl

SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = SCRIPT_DIR.parent / "assets" / "template.html"

HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}

# 无业务意义的浏览器自动头，从文档中过滤掉
NOISE_HEADERS = {
    "host", "connection", "pragma", "cache-control", "content-length",
    "sec-ch-ua", "sec-ch-ua-platform", "sec-ch-ua-mobile", "sec-ch-ua-platform-version",
    "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest", "sec-fetch-user",
    "user-agent", "accept-encoding", "accept-language",
    "referer", "origin", "upgrade-insecure-requests", "dnt", "te",
}

# 敏感头：值需要脱敏展示
SENSITIVE_HEADERS = {"itoken", "authorization", "cookie", "token", "x-api-key", "x-auth-token", "api-key"}

# 路径段 → 中文模块标签
TAG_MAP = {
    "anon": "匿名接口", "current": "当前用户", "user": "用户管理", "users": "用户管理",
    "mchInfo": "商户信息", "merchant": "商户管理", "mch": "商户管理",
    "mchApply": "商户申请", "mchPolling": "商户轮询",
    "isvInfo": "服务商信息", "isv": "服务商管理",
    "payIfDefines": "支付接口", "payWays": "支付方式", "payOrder": "支付订单",
    "payChannel": "支付渠道", "payConfig": "支付配置",
    "agents": "代理商管理", "agent": "代理商管理",
    "complaints": "投诉管理", "order": "订单管理", "orders": "订单管理",
    "goods": "商品管理", "product": "商品管理",
    "auth": "认证授权", "login": "认证授权", "account": "账户管理",
    "upload": "文件上传", "file": "文件管理", "files": "文件管理",
    "report": "报表统计", "statistics": "统计报表", "stats": "统计报表",
    "config": "系统配置", "system": "系统管理", "siteInfos": "站点信息",
    "notify": "通知回调", "callback": "通知回调", "webhook": "通知回调",
    "member": "会员管理", "vip": "会员管理",
    "finance": "财务管理", "settlement": "结算管理",
    "risk": "风控管理", "audit": "审核管理",
}

# 路径末段 → 中文名称
NAME_MAP = {
    "siteInfos": "站点信息", "user": "当前用户信息", "currentUser": "当前用户",
    "login": "登录", "logout": "退出登录", "register": "注册",
    "list": "列表", "getAll": "获取全部", "getAllArea": "获取所有地区",
    "count": "统计数量", "summary": "汇总", "detail": "详情", "get": "获取详情",
    "create": "创建", "add": "新增", "update": "更新", "delete": "删除", "remove": "删除",
    "export": "导出", "import": "导入", "download": "下载", "upload": "上传",
    "mchList": "商户列表", "applyCreatedBy": "申请创建人",
    "guidanceQuantity": "引导数量", "payIfDefines": "支付接口定义",
    "payWays": "支付方式", "payOrder": "支付订单", "agents": "代理商列表",
    "mchInfo": "商户信息", "isvInfo": "服务商信息", "mchPolling": "商户轮询",
    "mchApply": "商户申请", "complaints": "投诉",
    "info": "信息", "status": "状态", "enable": "启用", "disable": "停用",
    "verify": "验证", "check": "检查", "reset": "重置", "config": "配置",
    "password": "密码", "profile": "个人资料", "avatar": "头像",
}

# 常见请求头中文说明
HEADER_DESC = {
    "Content-Type": "请求体类型", "Accept": "期望响应格式",
    "Authorization": "身份凭证", "iToken": "用户身份令牌",
    "Cookie": "会话 Cookie", "Token": "认证令牌",
    "X-Requested-With": "AJAX 请求标识", "Referer": "来源页面",
    "Origin": "请求来源", "User-Agent": "客户端标识",
    "X-CSRF-Token": "CSRF 防护令牌", "X-Request-ID": "请求追踪 ID",
}

# 常见查询参数中文说明
PARAM_DESC = {
    "page": "页码", "pageNumber": "页码", "pageNum": "页码",
    "pageSize": "每页数量", "size": "每页数量", "limit": "限制数量",
    "keyword": "搜索关键词", "queryType": "查询类型", "queryDateRange": "查询日期范围",
    "sort": "排序字段", "order": "排序方向", "orderBy": "排序字段",
    "startDate": "开始日期", "endDate": "结束日期",
    "status": "状态", "state": "状态", "type": "类型", "sysType": "系统类型",
    "id": "ID", "name": "名称", "phone": "手机号", "email": "邮箱",
    "token": "令牌", "sign": "签名", "timestamp": "时间戳",
    "payOrderId": "支付订单号", "mchNo": "商户编号",
    "addType": "新增类型", "applyDefault": "默认申请",
    "queryConfig": "查询配置", "from": "来源",
}

# HTTP 方法对应的中文动词
METHOD_VERB = {
    "GET": "查询", "POST": "创建/操作", "PUT": "更新", "DELETE": "删除",
    "PATCH": "部分更新", "HEAD": "检查", "OPTIONS": "探测",
}


def shell_quote(s: str) -> str:
    """用单引号包裹，兼容 cmd/bash 展示。"""
    s = str(s)
    if "'" not in s:
        return f"'{s}'"
    return '"' + s.replace('"', '\\"') + '"'


def build_curl(api: dict) -> str:
    """根据字段重建 curl 命令。"""
    parts = [f"curl -X {api['method']} {shell_quote(api['url'])}"]
    for h in api.get("headers", []):
        parts.append(f"-H {shell_quote(str(h.get('key', '')) + ': ' + str(h.get('value', '')))}")
    body = api.get("body")
    if body:
        body_text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        parts.append(f"--data-raw {shell_quote(body_text)}")
    return " \\\n  ".join(parts)


def dedup_key(api: dict) -> str:
    """同一接口的判定键: METHOD + 归一化 path(去除 query、去末尾斜杠)。"""
    method = str(api.get("method") or "GET").strip().upper()
    url = str(api.get("url") or "").strip()
    parsed = urlparse(url if "://" in url else "http://" + url)
    path = (parsed.path or "/").rstrip("/")
    if not path:
        path = "/"
    return f"{method}|{path}"


def merge_api(old: dict, new: dict) -> dict:
    """字段级合并: new 的非空值覆盖 old 的; 空值保留 old(保护旧的 AI 描述/分组)。"""
    merged = dict(old)
    for k, v in new.items():
        if v is None:
            continue
        if isinstance(v, str):
            if v.strip():
                merged[k] = v
        elif isinstance(v, (list, dict)):
            if v:  # 非空列表/对象才覆盖
                merged[k] = v
        else:
            merged[k] = v
    return merged


def strip_url_quotes(url: str) -> str:
    """去除 URL 外层包裹的单/双引号（convert_json.py 可能残留）。"""
    url = url.strip()
    while len(url) >= 2 and url[0] in "\"'" and url[-1] == url[0]:
        url = url[1:-1].strip()
    return url


def mask_sensitive(value: str) -> str:
    """脱敏敏感值：保留前 8 位 + ***。"""
    s = str(value)
    if len(s) <= 12:
        return "***（已脱敏）"
    return s[:8] + "***（已脱敏）"


def auto_name(path: str, method: str) -> str:
    """根据路径末段和方法自动生成中文名称。"""
    segs = [s for s in path.split("/") if s]
    if not segs:
        return "未命名接口"
    last = segs[-1]
    # 通用动词后缀：与父段组合生成更精准的名称
    verb_suffix = {"get": "详情", "list": "列表", "count": "统计",
                   "create": "创建", "add": "新增", "update": "更新",
                   "delete": "删除", "info": "信息", "detail": "详情"}
    if last.lower() in verb_suffix and len(segs) >= 2:
        parent = segs[-2]
        # 尝试从 NAME_MAP / TAG_MAP 获取父段中文名
        parent_cn = NAME_MAP.get(parent) or TAG_MAP.get(parent) or parent
        return f"{parent_cn}{verb_suffix[last.lower()]}"
    # 尝试精确匹配末段
    if last in NAME_MAP:
        return NAME_MAP[last]
    # 尝试匹配路径中的已知段
    for seg in reversed(segs):
        if seg in NAME_MAP:
            return NAME_MAP[seg]
    # 回退：用末段原文
    return last


def auto_tag(path: str) -> str:
    """根据路径段自动生成中文标签。跳过 api/v1/v2 等通用段。"""
    segs = [s for s in path.split("/") if s]
    # 跳过通用前缀段
    skip = {"api", "v1", "v2", "v3", "rest", "service"}
    biz_segs = [s for s in segs if s.lower() not in skip]
    if not biz_segs:
        return "未分组"
    first = biz_segs[0]
    # 精确匹配
    if first in TAG_MAP:
        return TAG_MAP[first]
    # 大小写不敏感匹配
    for k, v in TAG_MAP.items():
        if k.lower() == first.lower():
            return v
    return first


def auto_description(name: str, method: str, path: str) -> str:
    """根据方法和名称生成简洁中文描述。"""
    verb = METHOD_VERB.get(method, "请求")
    # 特殊路径推断
    path_lower = path.lower()
    if "login" in path_lower:
        return "用户登录认证，返回令牌"
    if "logout" in path_lower:
        return "用户退出登录"
    if "upload" in path_lower:
        return "上传文件"
    if "export" in path_lower or "download" in path_lower:
        return f"{verb}并导出数据"
    # 名称本身已含动词（获取/查询/创建/统计等）时直接用作描述，避免「查询获取xx」冗余
    verb_chars = {"获", "查", "创", "删", "更", "统", "上", "导", "下", "登", "退", "检", "验"}
    if name and name[0] in verb_chars:
        return name
    # 通用：动词 + 中文名称
    return f"{verb}{name}"


def normalize_api(raw: dict, idx: int) -> dict:
    """校验并补全单个接口条目，同时清洗脏数据。"""
    api = dict(raw)
    api["id"] = idx

    method = str(api.get("method") or "GET").strip().upper()
    api["method"] = method if method in HTTP_METHODS else (method or "GET")

    # --- URL 清洗：去除外层引号 ---
    url = str(api.get("url") or "").strip()
    url = strip_url_quotes(url)
    if not url:
        raise ValueError(f"第 {idx + 1} 个接口缺少 url 字段: {raw.get('name')}")
    api["url"] = url

    parsed = urlparse(url if "://" in url else "http://" + url)
    api["path"] = api.get("path") or parsed.path or "/"

    # --- 参数清洗：URL query 并入 params，清理残留引号 ---
    params = list(api.get("params") or [])
    new_params = []
    idx_by_key = {}
    for p in params:
        k = p.get("key")
        if k and k not in idx_by_key:
            idx_by_key[k] = len(new_params)
            np = dict(p)
            # 清理参数值中的残留引号
            v = str(np.get("value") or "").strip()
            if v and v[0] in "\"'" and v[-1] in "\"'":
                v = v[1:-1]
            elif v and v[-1] in "\"'":
                v = v.rstrip("\"'")
            np["value"] = v
            # 补充参数说明
            if not np.get("description") and k in PARAM_DESC:
                np["description"] = PARAM_DESC[k]
            new_params.append(np)
    for k, v in parse_qsl(parsed.query, keep_blank_values=True):
        if k in idx_by_key:
            new_params[idx_by_key[k]]["value"] = v
        else:
            new_params.append({"key": k, "value": v, "required": False,
                               "description": PARAM_DESC.get(k, "")})
    api["params"] = new_params

    # --- 请求头清洗：过滤噪声头 + 脱敏敏感头 + 补充说明 ---
    raw_headers = list(api.get("headers") or [])
    clean_headers = []
    seen_keys = set()
    for h in raw_headers:
        key = str(h.get("key") or "").strip()
        if not key:
            continue
        # 过滤噪声头
        if key.lower() in NOISE_HEADERS:
            continue
        # 去重（保留第一次出现的）
        if key.lower() in seen_keys:
            continue
        seen_keys.add(key.lower())
        value = str(h.get("value") or "")
        desc = str(h.get("description") or "")
        # 脱敏敏感头
        if key.lower() in SENSITIVE_HEADERS:
            value = mask_sensitive(value)
            if not desc:
                desc = "敏感字段（已脱敏）"
        # 补充常见头说明
        if not desc and key in HEADER_DESC:
            desc = HEADER_DESC[key]
        clean_headers.append({"key": key, "value": value, "description": desc})
    api["headers"] = clean_headers

    # --- 自动生成中文名称 ---
    if not api.get("name"):
        api["name"] = auto_name(api["path"], method)
    elif not any('\u4e00' <= c <= '\u9fff' for c in str(api["name"])):
        # 名称全是英文时尝试翻译
        mapped = auto_name(api["path"], method)
        if mapped != api["path"].rstrip("/").split("/")[-1]:
            api["name"] = mapped

    # --- 自动生成中文标签 ---
    if not api.get("tag"):
        api["tag"] = auto_tag(api["path"])

    # --- 自动生成中文描述 ---
    if not api.get("description"):
        api["description"] = auto_description(api["name"], method, api["path"])

    # --- 重建 curl（使用清洗后的数据）---
    api["curl"] = build_curl(api)

    return api


def extract_apis_from_html(html_path: Path):
    """从已生成的 HTML 中反提取 const DOC = {...} 的 apis 数组。"""
    text = html_path.read_text(encoding="utf-8")
    m = re.search(r"const DOC\s*=\s*(\{.*?\});\s*\n", text, re.S)
    if not m:
        return None
    try:
        doc = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    apis = doc.get("apis")
    return apis if isinstance(apis, list) else None


def load_apis(path: Path):
    """从 json 文件读取 apis 数组(支持 {apis:[...]} 或 [...] 两种形态)。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"错误: JSON 解析失败 {path} - {e}", file=sys.stderr)
        return None
    if isinstance(data, dict) and "apis" in data:
        data = data["apis"]
    if not isinstance(data, list):
        return None
    return data


def merge_inputs(apis_lists):
    """按顺序合并多批接口, 按 method+path 去重, 后者非空字段覆盖前者。"""
    bucket = {}  # dedup_key -> merged raw dict
    order = []   # 保持首次出现顺序
    stats = {"added": 0, "updated": 0}
    for apis in apis_lists:
        for raw in apis:
            key = dedup_key(raw)
            if key not in bucket:
                bucket[key] = dict(raw)
                order.append(key)
                stats["added"] += 1
            else:
                bucket[key] = merge_api(bucket[key], raw)
                stats["updated"] += 1
    merged = [bucket[k] for k in order]
    return merged, stats


def sort_apis(apis):
    """按 tag → name 排序, 保证多次生成顺序稳定。"""
    return sorted(apis, key=lambda a: (str(a.get("tag") or ""), str(a.get("name") or "")))


def main() -> int:
    parser = argparse.ArgumentParser(description="生成单文件 HTML 接口文档(支持增量合并)")
    parser.add_argument("inputs", nargs="+", help="一个或多个 apis.json 路径(按顺序合并去重)")
    parser.add_argument("-o", "--output", help="输出 HTML 路径 (默认: 同目录 api-doc.html)")
    parser.add_argument("--title", default="API 接口文档", help="文档标题")
    parser.add_argument("--source", default="", help="数据来源说明，如原始文件名")
    parser.add_argument("--theme", default="dark", choices=["dark", "light"], help="默认主题")
    parser.add_argument("--from-html", dest="from_html", help="从已生成的 HTML 反提取接口作为合并基线")
    parser.add_argument("--save-master", dest="save_master", help="将合并去重后的 apis 数组写回此 JSON 路径, 供下次增量使用")
    args = parser.parse_args()

    # 收集所有输入批次
    apis_lists = []
    sources = []

    if args.from_html:
        fh = Path(args.from_html)
        if not fh.is_file():
            print(f"错误: 找不到 HTML 文件 {fh}", file=sys.stderr)
            return 1
        apis = extract_apis_from_html(fh)
        if not apis:
            print(f"错误: 无法从 {fh} 中提取接口数据(非本工具生成的文档?)", file=sys.stderr)
            return 1
        apis_lists.append(apis)
        sources.append(fh.name)
        print(f"从 HTML 反提取: {len(apis)} 个接口 ({fh.name})")

    for inp in args.inputs:
        p = Path(inp)
        if not p.is_file():
            print(f"错误: 找不到输入文件 {p}", file=sys.stderr)
            return 1
        apis = load_apis(p)
        if apis is None:
            print(f"错误: {p} 不是有效的 apis 数组", file=sys.stderr)
            return 1
        if not apis:
            print(f"警告: {p} 为空, 跳过", file=sys.stderr)
            continue
        apis_lists.append(apis)
        sources.append(p.name)
        print(f"读取: {len(apis)} 个接口 ({p.name})")

    if not apis_lists:
        print("错误: 没有可用的输入数据", file=sys.stderr)
        return 1

    # 合并去重
    merged_raw, stats = merge_inputs(apis_lists)
    print(f"合并去重: 新增 {stats['added']} 个, 更新 {stats['updated']} 个, 合计 {len(merged_raw)} 个")

    # 排序后规范化
    merged_raw = sort_apis(merged_raw)
    try:
        apis = [normalize_api(a, i) for i, a in enumerate(merged_raw)]
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1

    # 回写 master json
    if args.save_master:
        mp = Path(args.save_master)
        # 写回的是规范化前的合并原始数组, 便于下次继续作为输入合并
        master_payload = json.dumps(merged_raw, ensure_ascii=False, indent=1)
        mp.write_text(master_payload, encoding="utf-8")
        print(f"已回写 master: {mp} ({len(merged_raw)} 个接口)")

    if not TEMPLATE_PATH.is_file():
        print(f"错误: 找不到模板文件 {TEMPLATE_PATH}", file=sys.stderr)
        return 1

    doc = {
        "title": args.title,
        "source": " + ".join(sources) if sources else args.source,
        "theme": args.theme,
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "apis": apis,
    }

    # 防止 JSON 中的 </script> 提前闭合脚本标签
    payload = json.dumps(doc, ensure_ascii=False, indent=1).replace("</", "<\\/")

    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = html.replace("/*__DOC_DATA__*/null", payload)
    html = html.replace("__DOC_TITLE__", args.title.replace("&", "&amp;").replace("<", "&lt;"))

    output_path = Path(args.output) if args.output else Path(args.inputs[0]).with_name("api-doc.html")
    output_path.write_text(html, encoding="utf-8")
    print(f"OK: 已生成 {output_path} ({len(apis)} 个接口)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
