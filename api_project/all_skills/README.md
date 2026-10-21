# 本地 Skills

这些 Skill 服务于本仓库的 JSON 用例主流程，而不是替代测试执行入口。使用前先确认工作目录是项目根目录，并始终以 `api_project/case_data_files/`、`ALLURE_CONFIGS` 和实际测试收集结果为准。

| Skill | 用途 | 主要产物 | 何时使用 |
| --- | --- | --- | --- |
| `curl-to-testcase` | 将已保存的 cURL 转为可维护的测试资产 | JSON 用例、性能阈值、可选接口文档 | 新增或更新抓包接口 |
| `allure-api-analyzer` | 为 JSON 用例补齐 Allure 预设 | `common/allure_decorator.py` | 新 JSON 无法被统一入口收集时 |
| `api-doc-generator` | 将已整理的接口清单渲染为单页 HTML 文档 | `apis.json`、`api-doc.html` | 需要交付或维护接口说明时 |

## 推荐顺序

1. 先转换或手写 JSON 用例；敏感凭据改为 `${API_ITOKEN}` 等环境变量引用。
2. 用 `allure-api-analyzer` 提出 `ALLURE_CONFIGS` 变更，并人工确认业务语义。
3. 运行 `sync_performance_thresholds.py`，再用 `RUN_MODULE=list` 的 collect-only 检查用例是否已收集。
4. 运行 `python run_testcases.py` 验证请求、断言和报告。
5. 仅在需要交付接口说明时运行 `api-doc-generator`；它不参与 pytest 执行。

## 共同规则

- JSON 用例是执行单一事实来源；旧式 `test_*.py` 仅为兼容产物。
- 不在 JSON、HTML 或 Skill 输出中写入真实 token、Cookie、密码或 webhook。
- 所有生成或覆盖操作前先说明目标文件；只有用户确认后才安装依赖、下载 JDK、发送请求或覆盖已有文档。
- 新增 JSON 优先补充与文件名匹配的 `ALLURE_CONFIGS` 预设；未预置时统一入口会以 `generated_*_api` 兜底分组执行，后续再由维护者确认业务语义。
- 自动生成的名称、标签、描述和 5 秒性能阈值都是候选值，业务语义与 SLA 必须由维护者确认。
