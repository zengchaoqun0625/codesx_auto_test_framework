---
name: allure-api-analyzer
description: 分析本项目 JSON 用例并维护 ALLURE_CONFIGS，使统一参数化入口能够收集并以正确的业务分组展示用例。适用于“完善 Allure 配置”“新 JSON 没有执行”“分析接口模块”等请求。
---

# Allure API Analyzer

## 事实来源

- 用例：`api_project/case_data_files/*.json`
- 配置：`api_project/common/allure_decorator.py` 中的 `ALLURE_CONFIGS`
- 执行入口：`api_project/testcases/test_api.py`

`test_api.py` 在导入时扫描 JSON，并以规范化文件名匹配预设键：`jqb_<文件名>_api`。比较时忽略文件名中的大小写、`-`、`.` 和 `_`。无法匹配的 JSON 不会被统一入口参数化。

## 执行步骤

1. 读取 JSON 的文件名、URL、HTTP 方法和 `description`；不读取或输出真实鉴权值。
2. 检查已有 `ALLURE_CONFIGS` 映射并列出缺失或语义明显错误的项。
3. 为每个缺失项提出最小变更：`suite`、`epic`、`sub_suite`、`severity`、`tags` 和 `title`。模块命名以仓库已有配置为优先，不依据 URL 猜测后直接提交。
4. 修改仅限 `api_project/common/allure_decorator.py` 的 `ALLURE_CONFIGS`。不要修改 `test_api.py`、请求实现或 JSON 用例来迁就标签。
5. 运行收集检查：

   ```powershell
   $env:RUN_MODULE='list'
   python -m pytest api_project/testcases --collect-only -q
   ```

6. 汇报新增/更新的预设、关联 JSON 文件以及仍需业务方确认的分类。

## 质量要求

- 标题描述业务动作，不能只复述文件名。
- `severity` 与风险匹配；不默认使用最高等级。
- 标签用于检索，保持精简且避免重复。
- 映射存在不代表接口已验证；真实执行仍通过 `python run_testcases.py` 完成。
