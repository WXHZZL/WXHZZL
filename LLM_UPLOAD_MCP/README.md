# AnythingLLM 文档上传页

一个无构建步骤的单页工具，用于把本地文档上传到 AnythingLLM，并触发工作区向量嵌入。

## 使用

1. 启动 AnythingLLM，默认地址为 <http://localhost:3001>。
2. 在 AnythingLLM 中至少创建一个工作区。
3. 用浏览器直接打开 `index.html`。
4. 填写「服务地址」与「API 密钥」（填一次即记住在本机浏览器里）。
5. 选择一个或多个文件。
6. 点击“上传并嵌入”。

页面会依次显示工作区获取、文件上传和嵌入状态；没填密钥时直接给出中文提示，不会发请求。

## 工作流程

```text
读取工作区列表
  -> 使用第一个工作区
  -> 上传文件
  -> 获取文档 location
  -> 调用 update-embeddings
```

涉及接口：

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/api/v1/workspaces` | 获取工作区 |
| `POST` | `/api/v1/document/upload` | 上传文件 |
| `POST` | `/api/v1/workspace/{slug}/update-embeddings` | 触发嵌入 |

## 配置

服务地址与 API Key 在页面上填写，保存在浏览器 `localStorage`（键名
`anythingllm.api` / `anythingllm.key`），源码里没有任何硬编码密钥：

| 项 | 默认值 | 说明 |
|------|--------|------|
| 服务地址 | `http://localhost:3001/api/v1` | 末尾斜杠会自动去掉 |
| API 密钥 | 空（**必须填写**） | AnythingLLM 的 API Key |

> 早先版本把课程演示用的 Key 写死在 `index.html` 里，现已改为界面输入 + 本机存储，
> 这份 HTML 可以安全提交。那把演示 Key 建议直接作废。
> 注意：`localStorage` 是明文存在浏览器目录里的，公用电脑上用完请清掉。

## 注意事项

- 当前实现默认使用工作区列表中的第一个工作区。
- 页面依赖浏览器访问本机 AnythingLLM，需确保服务允许跨域请求。
- 文件上传和嵌入状态只保存在当前页面内存中，刷新后会清空（密钥不会，它存在 localStorage）。
- 这是本地演示工具，不应部署到公网。

