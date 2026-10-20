# 🚀 AI 驱动的 API 自动化测试框架

> **把 cURL 抓包放进项目，对 AI 说一句话，即可生成可执行的 API 用例、Allure 配置、性能阈值和接口文档。**

基于 `pytest + Allure` 的 API 自动化测试框架。它以 JSON 用例为核心，提供 cURL 转换、变量关联、数据驱动断言、性能阈值、报告归档、通知和定时回归能力。

```text
“帮我转换 curl 文件并生成测试用例”
                  ↓
     AI 编排项目内置 curl-to-testcase Skill
                  ↓
 cURL → JSON 用例 → Allure 映射 → 性能阈值 → 可选接口文档
                  ↓
       python run_testcases.py 执行与生成报告
```

## ✨ 为什么优先使用 AI 流程

| 传统新增接口 | AI 一句话流程 |
| --- | --- |
| 手动解析 cURL、创建 JSON、编写配置 | 自动定位 cURL 并调用无头转换器 |
| 手动确认报告分组和标题 | 自动补齐候选 Allure 映射，再按业务语义核对 |
| 容易遗漏性能基线与接口说明 | 自动同步阈值；按需生成 HTML 接口文档 |
| 多个入口、不清楚如何验收 | 输出变更清单，并执行收集检查 |

AI 并不改变框架的执行方式：最终仍由统一的 JSON 测试入口运行。因此生成结果可审查、可维护，也可不依赖 AI 继续使用。

---

## 🪄 30 秒开始：AI 一句话生成用例

### 1. 保存 cURL

从浏览器开发者工具或抓包工具复制 **Copy as cURL**，保存为项目内任意位置的文本文件；推荐文件名包含 `curl`，例如：

```text
curl_login.txt
curl_order.txt
```

一个文件可以包含多条 cURL 命令。

### 2. 对 AI 说一句话

在支持本仓库本地 Skill 的 AI 编程工具中打开项目，直接输入：

```text
帮我转换 curl 文件并生成测试用例
```

也可以说：`一键转换 curl`、`把这个 curl 转成测试用例`、`新增抓包接口并完善报告配置`。

### 3. AI 自动编排的内容

```mermaid
flowchart LR
    A[定位 cURL 文件] --> B[转换为 JSON 用例]
    B --> C[脱敏并检查请求数据]
    C --> D[补齐 Allure 分组与标签]
    D --> E[同步性能阈值]
    E --> F[collect-only 验证收集结果]
    F --> G[按需生成 HTML 接口文档]
```

生成的主要文件如下：

| 产物 | 用途 |
| --- | --- |
| `api_project/case_data_files/*.json` | 唯一的测试用例数据来源 |
| `api_project/common/allure_decorator.py` | Allure 模块、标签、标题与严重级别映射 |
| `api_project/config/performance_thresholds.json` | 接口性能阈值；新增接口默认 5 秒，需按 SLA 复核 |
| `api_document/apis.json` / `api_document/api-doc.html` | 可选的接口说明产物 |

AI 会在涉及安装依赖、下载 JDK、覆盖已有文件、执行真实接口或使用缺失凭据时提示你确认；除此以外，一条指令即可启动完整编排。

---

## 🧭 框架实际执行流程

```text
JSON 用例
  ↓
test_api.py 自动扫描并参数化（仅执行已映射 Allure 配置的 JSON）
  ↓
请求发送 → 变量提取 → 断言 → 请求/响应脱敏附件
  ↓
pytest + Allure 原始结果
  ↓
报告、压缩包、历史趋势、性能统计、通知
```

**重要：**新增 JSON 后必须有对应的 `ALLURE_CONFIGS` 预设，否则统一入口会跳过该文件。这是框架避免未知接口被静默执行的安全门禁；AI 流程会负责检查它。

---

## ⚡ 本地快速开始

### 环境要求

| 组件 | 说明 |
| --- | --- |
| Python 3.9+ | 运行框架和转换工具 |
| JDK 8+ | 生成 Allure HTML 报告时需要 |
| cURL 文本 | 使用 AI 转换流程时需要 |

### 初始化

```powershell
python -m pip install -r requirements.txt
Copy-Item api_project/.env.example api_project/.env
```

在 `api_project/.env` 填写本地敏感配置；该文件已被忽略，不应提交：

```ini
API_ITOKEN=your_token
API_COOKIE=
SEND_EMAIL=only_failed
AUTO_START_ALLURE=false
SCHEDULER_ENABLED=false
```

- `SEND_EMAIL`：`always`、`only_failed` 或 `never`
- `AUTO_START_ALLURE`：是否在测试后自动启动 Allure 服务，默认关闭
- `SCHEDULER_ENABLED`：定时任务总开关，默认关闭

### 执行测试

```powershell
python run_testcases.py
```

运行入口会执行 pytest，并在测试完成后生成/压缩报告、清理旧报告、保存趋势数据，再依据 `.env` 配置发送通知。

---

## 🧪 手动新增用例（不使用 AI 也完全支持）

### 方式一：无头转换 cURL

```powershell
python api_project/all_skills/curl-to-testcase/scripts/run_convert.py .\curl_login.txt
```

如果无法从 cURL 自动识别域名，可追加 `--url-prefix https://api.example.com`。

### 方式二：直接编写 JSON

在 `api_project/case_data_files/` 创建文件：

```json
{
  "test_cases": {
    "test_case_1": {
      "description": "查询订单",
      "logic": "query",
      "expected_status": 200,
      "assertions": [
        {"jsonpath": "$.code", "eq": 0}
      ],
      "extract": [
        {"name": "order_id", "jsonpath": "$.data.orderId"}
      ],
      "data": {
        "url": "/api/order/${order_id}",
        "method": "GET",
        "headers": {"iToken": "${API_ITOKEN}"},
        "params": {"page": 1}
      }
    }
  }
}
```

支持的核心能力：

- `${变量名}`：引用 `.env` 或前序用例 `extract` 保存的变量
- `assertions`：响应状态、JSONPath、点路径、包含、长度、类型、非空和响应时间断言
- `logic: query`：当前标准请求处理器

不要把 `Authorization`、iToken、Cookie、密码或 webhook 写入 JSON；一律使用 `.env` 变量引用。

### 补齐 Allure 映射

JSON 文件名应对应 `api_project/common/allure_decorator.py` 中的预设键：

```text
api_mainChart.json  →  jqb_api_mainchart_api
```

文件名匹配时会忽略大小写、`-`、`.` 和 `_`。编辑后用以下命令验证收集情况：

```powershell
$env:RUN_MODULE='list'
python -m pytest api_project/testcases --collect-only -q
```

同步性能阈值：

```powershell
python api_project/all_skills/curl-to-testcase/scripts/sync_performance_thresholds.py
```

---

## 🎯 按范围执行

全量运行：

```powershell
python run_testcases.py
```

按模块或 Allure 预设运行（多个用逗号分隔）：

```powershell
$env:RUN_MODULE='查询模块,jqb_api_mchqrcodes_api'
python run_testcases.py
```

查看可用模块与预设：

```powershell
$env:RUN_MODULE='list'
python -m pytest api_project/testcases --collect-only -q
```

---

## 📊 报告、性能与归档

| 内容 | 位置 / 命令 |
| --- | --- |
| pytest-html-plus 报告 | `api_project/report/` |
| Allure 原始结果 | `api_project/data/` |
| 历史趋势与汇总 | `api_project/history/` |
| 性能阈值 | `api_project/config/performance_thresholds.json` |
| 预览报告归档 | `python api_project/config/archive_reports.py --dry-run` |
| 执行报告归档 | `python api_project/config/archive_reports.py` |

---

## ⏰ 定时回归

编辑 `api_project/config/scheduler_jobs.json`：任务需要同时满足 `enabled: true` 和 `.env` 中 `SCHEDULER_ENABLED=true` 才会执行。

先预览任务：

```powershell
python run_scheduler.py --dry-run
```

再启动：

```powershell
python run_scheduler.py
```

可在每个任务的 `env` 中指定 `RUN_MODULE` 和 `TEST_EXECUTOR`，让冒烟与全量回归使用不同范围。

---

## 🤖 本仓库内置 Skills

| Skill | 适用场景 |
| --- | --- |
| [`curl-to-testcase`](api_project/all_skills/curl-to-testcase/SKILL.md) | cURL 一键转 JSON 用例、映射和性能阈值 |
| [`allure-api-analyzer`](api_project/all_skills/allure-api-analyzer/SKILL.md) | 新 JSON 未被收集、需要整理报告分组时 |
| [`api-doc-generator`](api_project/all_skills/api-doc-generator/SKILL.md) | 生成或增量维护单页 HTML 接口文档 |

详细的协作边界与维护顺序见 [`api_project/all_skills/README.md`](api_project/all_skills/README.md)。
