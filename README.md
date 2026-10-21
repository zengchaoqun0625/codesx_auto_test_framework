# 🚀 AI 驱动的 API 自动化测试框架

> **把 cURL 抓包放进项目，对 AI 说一句话，即可生成可执行的 API 用例、Allure 配置、性能阈值和接口文档。**

基于 `pytest + Allure` 的 API 自动化测试框架。它以 JSON 用例为核心，提供 cURL 转换、变量关联、数据驱动断言、性能阈值、报告归档、通知和定时回归能力。

## 先启动本地管理台

在项目根目录执行下面的命令，然后打开 <http://127.0.0.1:5000/>：

```powershell
.\.venv\Scripts\python.exe web_app.py
```

管理台可完成 cURL 导入、模块执行、用例浏览、报告查看和本地 `.env` 配置。需要新增接口时，推荐直接对 AI 说：`帮我转换 curl 文件并生成测试用例`，即可走项目内置的完整 Skill 流程。

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

## 🖥️ 本地 Web 管理台

启动管理台（默认会自动打开浏览器）：

```powershell
.\.venv\Scripts\python.exe web_app.py
```

地址：<http://127.0.0.1:5000/>

管理台覆盖从新增接口到报告查看的完整日常流程：

1. 粘贴浏览器的 **Copy as cURL**，先预览生成的 JSON；抓包中的 Token、Cookie 与密码会替换为环境变量占位符。
2. 确认后才保存用例；同名文件不会覆盖，保存后自动同步性能阈值，并以 `collect-only` 验证统一入口能够收集。
3. 选择范围启动真实接口测试，查看实时日志，并进入 Allure、趋势、性能与总报告。
4. 查看定时调度总开关、已启用任务数量，以及邮件、飞书、钉钉、企业微信和电话告警的配置状态。页面不会显示任何密钥或 webhook。

通知与调度仍通过 `.env` 和 `api_project/config/scheduler_jobs.json` 配置；页面展示的是配置状态，不会主动发送通知。

---

## 📒 日常操作手册

### 1. 首次配置

```powershell
Copy-Item api_project/.env.example api_project/.env
```

在 `.env` 至少填入 `API_HOST`，或填入 `API_ENV` 与对应的 `TEST_API_HOST` / `PRO_API_HOST`；受鉴权接口再填写 `API_TOKEN` 或 `API_ITOKEN`。通知渠道在模板中默认关闭，只有在确认收件人、群机器人或电话告警目标后才启用对应的 `*_ENABLED=true`。

### 2. 新增接口（推荐 AI Skill）

1. 把浏览器 **Copy as cURL** 保存为项目内的 `*curl*.txt`，或在管理台的“CURL 转用例”页粘贴。
2. 对 AI 说：`帮我转换 curl 文件并生成测试用例`。
3. 审核预览：真实凭据必须是 `${API_TOKEN}`、`${API_ITOKEN}`、`${API_COOKIE}` 等占位符；为每个 `test_case` 补充业务断言。
4. 运行 `RUN_MODULE=list` 的收集检查，再选择新增模块执行真实接口测试。
5. 如需对外交付，再更新 `api_document/apis.json` 并生成 `api_document/api-doc.html`。

### 3. 日常执行与查看报告

```powershell
# 全量执行
python run_testcases.py

# 仅执行指定模块或 Allure 预设
$env:RUN_MODULE='查询模块,jqb_api_mchqrcodes_api'
python run_testcases.py
```

执行后从管理台“结果中心”进入总报告、Allure、趋势、汇总和性能报告。通知由 `SEND_EMAIL` 与 `PYTEST_NOTIFY_MODE` 决定；本地排查可临时用 `never` 避免对外发送。

Allure 历史备份由 `ALLURE_REPORT_KEEP` 控制，默认保留最近 3 份 `allure_reports/<时间戳>/` 目录和 `api_project/report/` 中对应的 ZIP；例如设为 `1` 只保留最新一份。

### 4. 定时回归

先运行 `python run_scheduler.py --dry-run` 核对计划，再将 `.env` 的 `SCHEDULER_ENABLED=true` 与目标任务的 `enabled: true` 同时打开。当前 `scheduler_jobs.json` 的任务均为启用状态，启动调度器前务必确认频率、通知目标和存储清理策略。

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

**重要：**新增 JSON 会优先匹配对应的 `ALLURE_CONFIGS` 预设；若尚未配置，统一入口会自动使用 `generated_*_api` 兜底分组，仍会执行并出现在收集结果中。为保证报告分组的业务语义，仍应通过 `allure-api-analyzer` 补齐正式预设。

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

## 🌍 环境、域名与登录 token 配置

环境选择无需修改代码。在 `api_project/.env` 配置测试和正式域名，再改一行 `API_ENV`：

```ini
API_ENV=test
TEST_API_HOST=https://test-api.example.com
PRO_API_HOST=https://api.example.com

# 二选一：API_TOKEN 优先；API_ITOKEN 兼容历史配置
API_TOKEN=your_test_token
# API_TOKEN_HEADER=iToken
# API_TOKEN_PREFIX=
```

- `API_ENV` 支持 `test` / `testing` / `pro` / `prod` / `production`。
- 临时指定域名可使用 `API_HOST=https://temporary-api.example.com`。
- 单次运行最高优先级为 `python run_testcases.py --api-host https://temporary-api.example.com`。
- 默认 token 请求头为 `iToken`。后端使用 Bearer Token 时设置 `API_TOKEN_HEADER=Authorization`、`API_TOKEN_PREFIX=Bearer`。

域名优先级：`--api-host` > `API_HOST` > `API_ENV` 对应的环境域名 > `host_config.py` > `pytest.ini`。

### 前置登录获取并自动刷新 token

在 JSON 用例中使用 `logic: "precondition"`。前置登录步骤默认不带旧 token；登录响应通过 `extract` 提取，`set_login_token` 指向变量名。后续正式请求自动使用该 token，若返回一次 401，会自动重新执行登录并重试该请求一次。

```json
{
  "test_cases": {
    "test_case_1": {
      "description": "登录后查询订单",
      "logic": "precondition",
      "pre_steps": [
        {
          "description": "获取登录 token",
          "use_token": false,
          "request_type": "json",
          "extract": [
            {"name": "LOGIN_TOKEN", "jsonpath": "$.data.token"}
          ],
          "set_login_token": "LOGIN_TOKEN",
          "data": {
            "url": "/api/login",
            "method": "POST",
            "json": {"username": "${LOGIN_USERNAME}", "password": "${LOGIN_PASSWORD}"}
          }
        }
      ],
      "expected_status": 200,
      "data": {
        "url": "/api/orders",
        "method": "GET"
      }
    }
  }
}
```

账号密码同样放在 `.env`，例如 `LOGIN_USERNAME=test_user`、`LOGIN_PASSWORD=***`；不要写进 JSON 或提交 Git。登录接口返回字段不是 `$.data.token` 时，只需改 JSONPath。

### 统一登录配置与多角色

当多个用例共用登录逻辑时，把登录步骤统一配置在 [api_project/config/auth_profiles.json](api_project/config/auth_profiles.json)，业务用例只写 `auth_profile`。账号、密码、静态 token 只放 `.env`，不写入配置文件或用例 JSON。

```json
{
  "profiles": {
    "admin": {
      "token_variable": "ADMIN_LOGIN_TOKEN",
      "token_header_name": "Authorization",
      "token_prefix": "Bearer",
      "login": {
        "request_type": "json",
        "expected_status": 200,
        "extract": [
          {"name": "ADMIN_LOGIN_TOKEN", "jsonpath": "$.data.accessToken"}
        ],
        "data": {
          "url": "/api/login",
          "method": "POST",
          "json": {
            "username": "${ADMIN_USERNAME}",
            "password": "${ADMIN_PASSWORD}"
          }
        }
      }
    },
    "merchant": {
      "token_env": "MERCHANT_TOKEN",
      "token_header_name": "iToken"
    }
  }
}
```

在业务用例中只指定角色：

```json
{
  "description": "管理员查询订单",
  "auth_profile": "admin",
  "data": {"url": "/api/orders", "method": "GET"}
}
```

- 每个角色的 token、认证头、Bearer 前缀和 401 重登回调相互隔离；同一轮执行中每个角色仅首次登录一次。
- 配置了 `token_env`（如 `MERCHANT_TOKEN`）且 `.env` 有值时优先使用静态 token；未配置时仅在同时提供 `login` 的情况下才会走登录流程。
- 角色名拼写错误、缺少 `token_variable`、token 未提取到时会立即报清晰错误。

### 测试数据和断言规则分层

业务 JSON 只保留接口行为与变量占位符；环境数据和通用断言分别维护在配置文件中：

| 内容 | 文件 | 是否放敏感值 |
| --- | --- | --- |
| 环境名、域名变量、数据分区 | `api_project/config/environment_profiles.json` | 否 |
| 账号密码、静态 token | `api_project/.env` | 是，不提交 Git |
| 业务测试数据 | `api_project/config/test_data.json` | 否 |
| 通用断言 | `api_project/config/assertion_rules.json` | 否 |

`test_data.json` 的 `common` 对所有环境生效，`environments.test` / `environments.pro` 覆盖同名字段：

```json
{
  "common": {"PAGE_SIZE": 20},
  "environments": {
    "test": {"ORDER_ID": "test-order-001"},
    "pro": {"ORDER_ID": "smoke-order-001"}
  }
}
```

业务 JSON 继续使用 `${ORDER_ID}`、`${PAGE_SIZE}`；运行时优先级为：前序接口 `extract` 的值 > `.env`/CI 环境变量 > `test_data.json`。新增环境数据或账号只改配置，不改业务 JSON。

`assertion_rules.json` 可复用断言：

```json
{
  "rules": {
    "business_success": [
      {"jsonpath": "$.code", "eq": 0}
    ]
  }
}
```

用例写入一次 `"assertion_rules": ["business_success"]` 后，后续调整规则只改配置文件；原有内联 `assertions` 会继续执行。

### 单接口与逐接口断言

断言的最小单位是一个 JSON 文件内的单个 `test_case`。统一入口会逐条展开并独立显示为 `文件名/test_case_x`，因此同一接口的不同参数、正反例，或不同接口都可以分别设置断言。

```json
{
  "description": "查询订单成功",
  "expected_status": 200,
  "assertion_rules": ["business_success"],
  "assertions": [
    {"jsonpath": "$.data.items", "type": "list"},
    {"jsonpath": "$.data.items", "not_empty": true},
    {"jsonpath": "$.data.total", "eq": 1},
    {"key": "data.items.0.status", "contains": "PAID"},
    {"response_time": 2}
  ]
}
```

- `expected_status` 断言 HTTP 状态码；未配置时 `query` 用例默认断言 `200`。
- `assertions` 按顺序执行，支持 `jsonpath`（或 `expression`）和 `key` 点路径；比较方式为 `eq`、`contains`、`length`、`type`、`not_empty`，也可单独使用 `response_time`（秒）。任一失败即该条用例失败。
- `assertion_rules` 从 `api_project/config/assertion_rules.json` 引入可复用断言，并且会与该用例的内联 `assertions` 一起执行；适合所有接口共用的业务成功码。接口特有字段、列表长度和性能要求则写在各自的 `test_case` 中。
- 为同一接口覆盖多个场景时，在同一文件的 `test_cases` 下增加 `test_case_2`、`test_case_3`；它们拥有各自的请求参数和断言，报告中也会分别统计。

### 请求重试策略

[request_retry.json](api_project/config/request_retry.json) 统一控制重试次数、间隔和状态码。默认只重试 `GET`、`HEAD`、`OPTIONS` 的 429、502、503 和网络超时，最多 3 次；登录与 `POST`/`PUT`/`DELETE` 等写请求不会自动重试。

确实需要对幂等写请求重试时，在该用例或登录配置中显式添加 `"retry": true`；需要禁止某个读请求重试时设置 `"retry": false`。这样可避免重复下单、重复创建等副作用。

---

## 🧪 手动新增用例（不使用 AI 也完全支持）

### 方式一：无头转换 cURL

```powershell
python api_project/all_skills/curl-to-testcase/scripts/run_convert.py .\curl_login.txt
```

如果无法从 cURL 自动识别域名，可追加 `--url-prefix https://api.example.com`。

转换后生成的 `api_project/testcases/test_*.py` 可以单独执行，也会委托统一执行器，因此与 JSON 统一入口具有相同行为：环境数据替换、`auth_profile` 角色认证、`precondition` 登录、`assertion_rules` 和请求重试全部生效。不要在生成脚本中复制或修改请求发送逻辑；需要认证或断言时直接编辑对应 JSON 配置。

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
- `expected_status`：HTTP 响应状态码断言；`assertions`：JSONPath、点路径、包含、长度、类型、非空和响应时间断言
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

编辑 `api_project/config/scheduler_jobs.json`：任务需要同时满足 `enabled: true` 和 `.env` 中 `SCHEDULER_ENABLED=true` 才会执行。当前仓库中的 3 个任务均为启用状态；首次启动前请按实际环境确认执行频率和清理策略。

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
