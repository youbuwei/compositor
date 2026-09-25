# dsh-zhipu-mcp

智谱 BigModel 专属 MCP 的 DeepSeek Harness（DSH）独立插件：**联网搜索 + 网页读取 + 开源仓库**，一个插件装齐智谱 GLM Coding Plan 的三件套远程 MCP，无需本地安装任何服务。

Zhipu BigModel MCP (web search / web reader / GitHub repo reader) as a standalone DeepSeek Harness plugin. Requires a GLM Coding Plan API key.

| 服务器 | 模型可用工具 | 能力 |
|---|---|---|
| `web-search-prime` | `mcp__web-search-prime__webSearchPrime` | 全网搜索：新闻 / 股价 / 天气等实时信息 |
| `web-reader` | `mcp__web-reader__webReader` | 抓取任意网页的标题 / 正文 / 元数据 / 链接 |
| `zread` | `mcp__zread__search_doc` `mcp__zread__get_repo_structure` `mcp__zread__read_file` | GitHub 开源仓库：文档检索 / 目录结构 / 源码读取 |

## 前置条件

- DeepSeek Harness（Desktop 或 `dsh web` 均可）
- 智谱 [GLM Coding Plan](https://bigmodel.cn/coding-plan/overview) 套餐的 API Key（三件套是 Coding Plan 专属 MCP，普通 API Key 不通用）

## 安装

### 方式一：npm（推荐）

```sh
dsh plugin --profile web add dsh-zhipu-mcp@latest
# Desktop 用户把 --profile web 换成 --profile desktop，或在 Desktop 插件管理器中搜索安装
```

### 方式二：从 GitHub 安装

```sh
dsh plugin --profile web add git+https://github.com/youbuwei/dsh-zhipu-mcp.git
```

### 方式三：手动挂载（Desktop）

把仓库克隆到任意位置，在 profile 的 `cordis.patch.yml` 中加入：

```yaml
- insert:
    - id: zhipu-mcp
      name: /path/to/dsh-zhipu-mcp/index.js
      config:
        apiKeyRef: ZAI_CODING_CN_API_KEY
```

安装后**重启 DSH** 生效；可用 `dsh --profile <name> --dump-config | grep zhipu` 确认挂载。

## API Key 配置

解析顺序（前面的优先）：

1. 插件配置 `apiKey` —— 直接填写；
2. DSH 凭据服务中 `apiKeyRef`（默认 `ZAI_CODING_CN_API_KEY`）引用的 Key
   —— 如果你正在用 GLM Coding Plan 跑模型，**默认零配置**，直接复用当前 Key；
3. 环境变量 `ZAI_CODING_CN_API_KEY`。

本插件不保存任何密钥。

## 配置项

| 字段 | 默认值 | 说明 |
|---|---|---|
| `apiKey` | 空 | 直接指定智谱 API Key（一般留空） |
| `apiKeyRef` | `ZAI_CODING_CN_API_KEY` | 凭据服务 / 环境变量中的 Key 引用名 |

## 卸载

```sh
dsh plugin --profile web remove dsh-zhipu-mcp
```

或删除对应补丁条目，重启 DSH。

## 实现说明

- 通过运行中 DSH 自带的 `@deepseek-ai/dsh-mcp-client` 桥接（版本与宿主严格一致），
  每台服务器挂载一个子插件实例；工具名由 `serverName` + 原始工具名组成，升级后保持稳定。
- DSH 安装目录定位顺序：环境变量 `DSH_APP_ROOT` → macOS `/Applications`（或 `~/Applications`）→
  Windows `%LOCALAPPDATA%\Programs\DSH Desktop` → 裸名导入（已把 `@deepseek-ai/dsh-mcp-client`
  安装为可解析依赖的 profile）。
- 子实例 `failOnStartupError: false`：网络异常时 DSH 照常启动，仅该服务器工具暂不可用并自动重连。
- Config schema 使用宿主自带 schemastery，可在设置界面直接编辑。

## English

Standalone DeepSeek Harness plugin that bridges Zhipu's three official remote MCP servers (web search / web reader / GitHub repo reader) for GLM Coding Plan subscribers. Key resolution: plugin `apiKey` → DSH credential store ref (`ZAI_CODING_CN_API_KEY` by default, reusing the key your GLM model already uses) → environment variable. See the tables above for tools and config; install via `dsh plugin add`, restart DSH, done.

## License

[MIT](LICENSE)
