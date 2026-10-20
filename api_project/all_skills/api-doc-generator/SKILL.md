---
name: api-doc-generator
description: 将经过整理与脱敏的接口清单 JSON 渲染为可搜索、可增量维护的单文件 HTML 接口文档。适用于“生成接口文档”“更新 api-doc.html”“合并接口清单”等请求。
---

# 接口文档生成器

## 输入与输出

输入是一个或多个接口清单 JSON，不是测试执行产物。调用脚本前先将 cURL、表格或 JSON 用例整理为接口数组，并移除真实 token、Cookie、密码和 webhook。

默认交付位置：

- `api_document/apis.json`：审核后的接口清单
- `api_document/api-doc.html`：单文件 HTML 文档

## 生成

```powershell
python api_project/all_skills/api-doc-generator/scripts/generate_doc.py `
  api_document/apis.json `
  -o api_document/api-doc.html `
  --title '项目接口文档' `
  --source '接口清单'
```

脚本按 `method + path` 去重。维护累计文档时，使用 `--save-master` 保存去重后的基线；后续传入基线与新批次 JSON 进行增量合并。基线遗失时可用 `--from-html` 从已生成 HTML 提取。

## 约束

- 文档生成不修改测试用例、Allure 配置或性能阈值。
- 自动补全的名称、标签与描述必须经人工确认；业务含义不清时保留待确认说明。
- HTML 内的复制 cURL 也必须是脱敏版本。
- 覆盖现有 `apis.json` 或 `api-doc.html` 前先告知用户；交付前确认两个文件都已生成且 HTML 可打开。
