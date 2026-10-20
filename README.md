# API 自动化测试框架

这是一个以 JSON 用例为中心的 API 回归测试框架。cURL 转换只是用例录入方式之一；实际执行由 `api_project/testcases/test_api.py` 的统一参数化入口完成，并统一产出 pytest、Allure、性能和历史趋势报告。

## 实际工作流

```text
cURL / 手写 JSON
        ↓
api_project/case_data_files/*.json
        ↓  （补全 ALLURE_CONFIGS 映射）
api_project/testcases/test_api.py
        ↓
pytest 请求、变量提取、断言、Allure 附件
        ↓
api_project/common/report_manager.py
        ↓
报告归档、性能统计、趋势汇总、按配置发送通知
```

`test_api.py` 仅执行能够映射到 `ALLURE_CONFIGS` 的 JSON 文件；新增 JSON 后必须完成 Allure 配置，否则它不会进入统一入口。这是避免未知接口被静默执行的安全门禁。

## 快速开始

需要 Python 3.9+。Allure HTML 报告需要 JDK；只运行 pytest 不强制需要它。

```powershell
python -m pip install -r requirements.txt
Copy-Item api_project/.env.example api_project/.env
python run_testcases.py
```

`.env` 存放 token、Cookie、通知配置等敏感信息，不应提交。常用配置如下：

```ini
API_ITOKEN=your_token
API_COOKIE=
SEND_EMAIL=only_failed
AUTO_START_ALLURE=false
SCHEDULER_ENABLED=false
```

`SEND_EMAIL` 仅支持 `always`、`only_failed`、`never`。`AUTO_START_ALLURE` 默认关闭，避免每次运行自动启动服务。

## 新增接口：推荐流程

### 1. 录入用例

使用 cURL 无头转换器：

```powershell
python api_project/all_skills/curl-to-testcase/scripts/run_convert.py .\curl_login.txt
```

转换器会写入 `api_project/case_data_files/`，同时可能生成旧式 `test_*.py` 兼容文件。新用例以 JSON 为准；不要把独立 Python 用例当成主入口。

也可以直接在 `api_project/case_data_files/` 新建 JSON：

```json
{
  "test_cases": {
    "test_case_1": {
      "description": "查询示例",
      "logic": "query",
      "expected_status": 200,
      "assertions": [{"jsonpath": "$.code", "eq": 0}],
      "extract": [{"name": "order_id", "jsonpath": "$.data.orderId"}],
      "data": {
        "url": "/api/example/${order_id}",
        "method": "GET",
        "headers": {"iToken": "${API_ITOKEN}"},
        "params": {"page": 1}
      }
    }
  }
}
```

目前已注册的 `logic` 是 `query`。变量提取结果可用 `${变量名}` 被后续用例引用。请求头与报告会对敏感字段脱敏；仍不要在 JSON 中提交真实凭据。

### 2. 配置 Allure 映射

在 `api_project/common/allure_decorator.py` 的 `ALLURE_CONFIGS` 中新增或更新预设。预设名遵循 `jqb_<json文件名规范化>_api`；文件名比较时忽略大小写、`-`、`.` 与 `_`。例如 `api_mainChart.json` 对应 `jqb_api_mainchart_api`。

可使用本地 `allure-api-analyzer` Skill 完成候选配置，但提交前要核对模块、标题、严重级别和标签。

### 3. 同步性能阈值并验证

```powershell
python api_project/all_skills/curl-to-testcase/scripts/sync_performance_thresholds.py
$env:RUN_MODULE='list'
python -m pytest api_project/testcases --collect-only -q
python run_testcases.py
```

阈值脚本只补充新增接口，默认阈值为 5 秒；业务 SLA 应在 `api_project/config/performance_thresholds.json` 中复核后调整。

## 执行与报告

全量运行：

```powershell
python run_testcases.py
```

按模块或预设筛选（可逗号分隔）：

```powershell
$env:RUN_MODULE='查询模块,jqb_api_mchqrcodes_api'
python run_testcases.py
```

入口会依次运行 pytest、生成/压缩 Allure 报告、清理旧报告、记录历史趋势，并按 `.env` 配置通知。pytest-html-plus 结果位于 `api_project/report/`；历史趋势数据位于 `api_project/history/`。报告后置处理失败会让进程以非零状态退出，便于 CI 识别。

## 定时调度

任务定义在 `api_project/config/scheduler_jobs.json`，每个任务必须显式设置 `enabled: true` 才会注册。默认总开关也是关闭的：

```ini
SCHEDULER_ENABLED=true
```

先预览再启动：

```powershell
python run_scheduler.py --dry-run
python run_scheduler.py
```

`--force` 只忽略总开关，不会启用 JSON 中已关闭的任务。可在任务的 `env` 中设置 `RUN_MODULE` 和 `TEST_EXECUTOR`。

## 维护边界

| 目标 | 修改位置 |
| --- | --- |
| 接口请求和断言 | `api_project/case_data_files/*.json` |
| Allure 分组与标签 | `api_project/common/allure_decorator.py` |
| 性能阈值 | `api_project/config/performance_thresholds.json` |
| 报告与通知 | `api_project/.env`、`api_project/common/report_manager.py` |
| 定时任务 | `api_project/config/scheduler_jobs.json` |
| 报告归档 | `python api_project/config/archive_reports.py --dry-run` |

本项目的 AI 操作说明在 [api_project/all_skills/README.md](api_project/all_skills/README.md)，其中的三个 Skill 分别用于 cURL 转用例、Allure 映射和接口文档生成。
