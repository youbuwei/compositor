/**
 * dsh-zhipu-mcp —— 智谱 BigModel 专属 MCP 的 DeepSeek Harness 独立插件。
 *
 * 桥接智谱官方远程 MCP 服务器（Streamable HTTP，见 docs.bigmodel.cn）：
 *   - 联网搜索：https://open.bigmodel.cn/api/mcp/web_search_prime/mcp
 *   - 网页读取：https://open.bigmodel.cn/api/mcp/web_reader/mcp
 *   - 开源仓库：https://open.bigmodel.cn/api/mcp/zread/mcp（zread.ai，GitHub 仓库文档/结构/源码）
 *
 * 需要 GLM Coding Plan 套餐的 API Key。
 *
 * API Key 解析顺序：
 *   1. config.apiKey —— 插件配置中直接填写的 Key；
 *   2. 凭据服务中名为 config.apiKeyRef（默认 ZAI_CODING_CN_API_KEY）的引用，
 *      即 GLM Coding Plan 正在使用的 Key，无需重复填写；
 *   3. 环境变量 config.apiKeyRef。
 *
 * 工具名保持稳定（重启/更新不变化）：
 *   - mcp__web-search-prime__webSearchPrime
 *   - mcp__web-reader__webReader
 *   - mcp__zread__search_doc / mcp__zread__get_repo_structure / mcp__zread__read_file
 *
 * 卸载：移除引用本插件的补丁条目 / `dsh plugin remove`，重启 DSH。
 */

import { homedir, platform } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

/** Cordis 插件名（用于加载诊断）。 */
export const name = 'zhipu-mcp'

/** 依赖的宿主服务：credentials 用于按引用名解析 API Key。 */
export const inject = ['credentials']

/** 智谱官方远程 MCP 端点清单。 */
export const servers = [
  {
    serverName: 'web-search-prime',
    url: 'https://open.bigmodel.cn/api/mcp/web_search_prime/mcp',
  },
  {
    serverName: 'web-reader',
    url: 'https://open.bigmodel.cn/api/mcp/web_reader/mcp',
  },
  {
    serverName: 'zread',
    url: 'https://open.bigmodel.cn/api/mcp/zread/mcp',
  },
]

/**
 * DSH 安装根目录候选（按平台）。
 * 桥接插件（dsh-mcp-client、schemastery）优先复用运行中 DSH 自带的副本，
 * 版本与宿主严格一致；也兜底支持将依赖安装为普通包后按裸名解析。
 * 非标准安装可通过环境变量 DSH_APP_ROOT 指向 DSH 的应用根目录。
 */
const APP_ROOTS = [
  process.env.DSH_APP_ROOT,
  platform() === 'darwin' ? '/Applications/DSH Desktop.app/Contents/Resources/app' : undefined,
  platform() === 'darwin' ? join(homedir(), 'Applications/DSH Desktop.app/Contents/Resources/app') : undefined,
  platform() === 'win32' && process.env.LOCALAPPDATA
    ? join(process.env.LOCALAPPDATA, 'Programs', 'DSH Desktop', 'resources', 'app')
    : undefined,
].filter(Boolean)

/** 从 DSH 安装目录或普通包解析一个 ESM 模块。 */
async function importFromDshApp(relPath) {
  let lastError
  for (const root of APP_ROOTS) {
    try {
      return await import(pathToFileURL(join(root, relPath)).href)
    } catch (error) {
      lastError = error
    }
  }
  try {
    return await import(relPath)
  } catch {
    // 落入下方汇总错误
  }
  throw new Error(
    `dsh-zhipu-mcp: 无法加载 ${relPath}；已尝试 ${APP_ROOTS.join(' , ')}。`
    + '非标准安装请设置环境变量 DSH_APP_ROOT 指向 DSH 应用根目录，'
    + '或安装 @deepseek-ai/dsh-mcp-client 使其可被裸名解析。',
    { cause: lastError },
  )
}

/**
 * 插件配置 schema（使用宿主自带的 schemastery；不可用时保持 undefined，
 * 由 apply 内部按可选字段处理）。
 */
export let Config
try {
  const { default: z } = await importFromDshApp('node_modules/@deepseek-ai/schemastery/lib/index.mjs')
  Config = z.object({
    apiKey: z.string().description('智谱 API Key；留空则按 apiKeyRef 从凭据服务或环境变量解析'),
    apiKeyRef: z.string().default('ZAI_CODING_CN_API_KEY').description('凭据服务 / 环境变量中的 Key 引用名'),
  }).description('dsh-zhipu-mcp 配置')
} catch {
  Config = undefined
}

/** 按解析顺序获取 API Key；全部落空时抛出带指引的错误。 */
async function resolveApiKey(ctx, config) {
  const explicit = typeof config?.apiKey === 'string' ? config.apiKey.trim() : ''
  if (explicit) return explicit
  const ref = config?.apiKeyRef || 'ZAI_CODING_CN_API_KEY'
  try {
    const credentials = ctx.get('credentials')
    const hit = credentials ? await credentials.resolve(ref) : undefined
    if (hit?.value) return hit.value
  } catch {
    // 凭据服务不可用时回落到环境变量
  }
  const fromEnv = process.env[ref]
  if (fromEnv) return fromEnv
  throw new Error(
    `dsh-zhipu-mcp: 未找到智谱 API Key —— 请在插件配置的 apiKey 中直接填写，或在凭据服务 / 环境变量中提供 ${ref}`,
  )
}

/**
 * 激活插件：解析 API Key，然后通过 @deepseek-ai/dsh-mcp-client
 * 为每台智谱 MCP 服务器挂载一个子插件实例。
 *
 * @param ctx - Cordis 插件上下文（宿主已提供 tools / credentials 服务）。
 * @param config - 经过 Config 校验的插件配置。
 */
export async function apply(ctx, config) {
  const apiKey = await resolveApiKey(ctx, config)
  const mcpClient = await importFromDshApp('node_modules/@deepseek-ai/dsh-mcp-client/lib/index.js')
  for (const server of servers) {
    ctx.plugin(mcpClient, {
      transport: 'streamable-http',
      ...server,
      headers: { Authorization: `Bearer ${apiKey}` },
    })
  }
  ctx.logger?.info?.(`dsh-zhipu-mcp: 已注册 ${servers.length} 台智谱 MCP 服务器（联网搜索 / 网页读取 / 开源仓库）`)
}
