---
name: curl-to-testcase
description: 将本项目中保存为 *curl*.txt 的 cURL 抓包转换为 JSON 测试用例，并完成 Allure 映射、性能阈值与可选接口文档的校验流程。适用于“转换 curl”“生成接口用例”“新增抓包接口”等请求。
---

# cURL 转测试用例

## 目标与边界

本 Skill 的主产物是 `api_project/case_data_files/*.json`。统一入口 `api_project/testcases/test_api.py` 从 JSON 参数化执行用例；转换器生成的 `test_*.py` 只用于兼容旧流程，不能替代 JSON。

不要自动安装依赖、下载 JDK、发送真实接口请求、覆盖已有用例或发布文档。上述操作分别需要用户明确授权。转换前先检查目标 JSON 是否已存在，并说明将修改的文件。

## 工作流

1. 确认项目根目录、cURL 文件和目标接口范围。仅接受本地 `.txt` 中的 cURL；文件名推荐含 `curl`。
2. 检查依赖：`python auto_install.py --check`。缺失时报告包名，等待用户授权安装。
3. 可选检查 JDK：`python api_project/all_skills/curl-to-testcase/scripts/check_jdk.py --check-only`。JDK 只在生成 Allure HTML 时需要。
4. 无头转换：

   ```powershell
   python api_project/all_skills/curl-to-testcase/scripts/run_convert.py <curl文件> [--url-prefix https://api.example.com]
   ```

   未传文件时，脚本会递归选择最新修改的 `*curl*.txt`；存在多个候选时，优先要求用户指定，避免误转换。
5. 审核新增 JSON：使用 `${API_ITOKEN}`、`${API_COOKIE}` 等占位符取代真实凭据；补充 `description`、`expected_status`、`assertions` 与需要的 `extract`。
6. 优先读取并执行 `../allure-api-analyzer/SKILL.md`，为需要业务分组的 JSON 增加或更新 `ALLURE_CONFIGS` 映射。未预置映射的 JSON 会使用统一入口的 `generated_*_api` 兜底分组，仍必须确认用例可以被收集：

   ```powershell
   $env:RUN_MODULE='list'
   python -m pytest api_project/testcases --collect-only -q
   ```

7. 同步性能阈值并人工审核新增规则：

   ```powershell
   python api_project/all_skills/curl-to-testcase/scripts/sync_performance_thresholds.py
   ```

8. 可选：如果用户要求交付接口说明，读取并执行 `../api-doc-generator/SKILL.md`。该步骤独立于测试执行。
9. 报告变更：列出 JSON、Allure 配置、阈值与文档产物；说明尚未执行真实测试，除非用户已明确授权运行。

## 验收清单

- JSON 可被解析，`test_cases` 非空，`logic` 为已注册的 `query`。
- 所有请求凭据均为环境变量引用，没有明文 secret。
- JSON 文件名可映射到 `ALLURE_CONFIGS`，或使用 `generated_*_api` 兜底分组；collect-only 能显示预期用例。
- 新增端点拥有性能阈值；默认 5 秒仅为起点，不等同 SLA。
- 生成接口文档时，`api_document/apis.json` 与 `api_document/api-doc.html` 均来自经审核的数据。
