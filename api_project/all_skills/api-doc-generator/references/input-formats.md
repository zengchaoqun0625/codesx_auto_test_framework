# 输入格式解析规则

本参考文档描述如何从各种抓包/记录文件中提取接口信息，并规范化为 `apis.json` 数组。

## 统一数据模型

每个接口规范化为以下 JSON 对象（字段说明见 `scripts/generate_doc.py` 文件头注释）：

```json
{
  "name": "接口中文名",
  "method": "GET|POST|PUT|DELETE|PATCH|...",
  "url": "完整 URL，含 query string",
  "description": "接口功能描述（AI 推断）",
  "tag": "分组/模块名",
  "headers": [{"key": "...", "value": "...", "description": "..."}],
  "params": [{"key": "...", "value": "...", "required": false, "description": "..."}],
  "body": "请求体（对象或字符串，可选）",
  "bodyType": "application/json（可选）",
  "response": "响应示例（可选）",
  "curl": "完整 curl 命令（可选，脚本会自动重建）"
}
```

## 格式一：curl 命令（抓包工具 "Copy as cURL" 导出）

特征：以 `curl` 开头，可能单行，也可能用 `\`（bash）或 `` ` ``/`` ^ ``（PowerShell/cmd）续行的多行块。

解析要点：
- `-X` / `--request` → method；缺省时：有 `-d`/`--data`/`--data-raw`/`--data-binary` 为 POST，否则 GET。
- 第一个非选项参数（URL，通常带引号）→ url。
- `-H 'Key: Value'` / `--header` → headers，按第一个 `: ` 拆分。
- `-d` / `--data*` → body；若 `Content-Type` 含 `json`，尝试解析为对象；`--data-binary '@/path'` 记录为文件引用说明。
- `-u user:pass` → 转为 `Authorization: Basic` 说明；`--cookie` → `Cookie` 头。
- 忽略 `-k`、`--compressed`、`-s`、`-v` 等传输选项。
- 多个 curl 之间常以空行或下一个 `curl` 分隔；文件可能混合注释行（`#`、`//`），忽略之。

## 格式二：一行一个接口（简化记录）

常见变体（字段顺序不固定，按内容识别）：

```
GET https://api.example.com/users 用户列表
POST /api/orders 创建订单 {"sku":"A1","qty":2}
用户登录 | POST | https://api.example.com/login
GET,https://api.example.com/goods,商品列表
```

解析要点：
- 先识别 HTTP 方法关键词（GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS，大小写均可）。
- 再识别 URL（含 `http(s)://` 或以 `/` 开头的路径）。
- 行内出现的 JSON 片段（`{...}` 或 `[...]`）→ body。
- 其余文本 → 作为 name/description 候选。
- 分隔符可能是空格、制表符、逗号、竖线 `|`。
- 相对路径（如 `/api/users`）无法推断域名时，url 原样保留，并在 description 中注明"来源为相对路径"；若文件中出现多个相同 host 的完整 URL，可推测该 host 作为默认值，但必须在文档来源说明中注明。

## 格式三：CSV / 表格导出

特征：首行可能是表头，如 `name,method,url,headers,params,body` 或中文表头 `接口名,请求方式,地址`。

解析要点：
- 有表头：按列名映射（中英文模糊匹配：name/接口名/名称、method/方式/方法、url/地址/路径、headers/请求头、params/参数、body/请求体、description/描述/说明）。
- 无表头：按"格式二"逐行处理。
- headers 单元格内多个头常用 `;`、`\n` 或 `&` 分隔，逐个拆成 key/value。
- 注意 CSV 引号转义（`""` → `"`），字段内可能含逗号。

## 语义推断规则（AI  enrichment）

解析出基础字段后，按以下规则补全：

1. **name**：用户记录的名字优先；否则用路径最后一段 + 方法推断，如 `GET /api/users/{id}` → "获取用户详情"。
2. **description**：根据 REST 语义推断：
   - `GET /xxx` 列表 → "查询xx列表"；`GET /xxx/{id}` → "查询xx详情"
   - `POST /xxx` → "新建xx"；`PUT/PATCH /xxx/{id}` → "更新xx"；`DELETE /xxx/{id}` → "删除xx"
   - 路径含 `login/logout/auth/token` → 认证相关；含 `upload` → 文件上传；含 `export/download` → 导出下载。
   - 结合 body 字段名、query 参数名补充细节。推断的描述保持简洁一句话，不确定时用"疑似/可能"措辞或留空。
3. **tag**：取路径中有业务意义的第一段（跳过 `api`、`v1`、`v2` 等版本段），如 `/api/order/list` → `order 模块`；文件本身有注释分组时优先使用。
4. **headers 说明**：常见头补充中文说明（Authorization→身份凭证、Content-Type→请求体类型、Cookie→会话 Cookie 等）。
5. **params 说明**：常见参数补充说明（page→页码、size/pageSize→每页数量、keyword→搜索关键词、timestamp→时间戳、sign→签名等）。
6. **敏感信息**：token、密码、密钥类的值保留原样但 description 注明"敏感字段"；若用户要求脱敏，替换为 `***`。

## 注意事项

- 同一 URL+method 出现多次时保留首次出现，后续记录的不同参数可合并进 params 示例。
- 编码按 UTF-8 读取，失败时尝试 GBK（中文 Windows 常见）。
- 无法识别的行不要丢弃，归入"未解析"并在交付时告知用户行号，由用户确认。
