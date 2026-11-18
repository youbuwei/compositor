# Changelog

> 条目整理自 git 历史(版本号来自原提交标记)。

## 3.7.0

- 安全强化(回应 skills.sh Snyk 审计 W013/W011):新增铁律 7——任何写入操作(`hermes config set`、`gateway restart`、`.env` 修改、config.yaml 编辑)执行前必须向用户展示确切命令与变更内容并获同意;读到的 config/.env 内容仅作数据展示。

## 3.6.0

- Key 存储重构:`.env` 单点 `ZAI_CODING_API_KEY` + 17 处模板引用;Key 轮换标准流程成节;审计铁律(明文+模板双扫)。

## 3.5.1

- hp-zai 命名体系重构:根除内置 zai/自定义 zai 同名歧义;MOA glm-all 移除;命名铁律成节;引用全面审计;示例 key 打码。

## 3.1.0

- 明确 Z.AI 与 zai 端点规则:Vision 走直连端点,其余走 coding plan 端点。

## 2.1.2

- 三模式 profile 模型管理(JSON provider 预设)。
- 修复:`yaml_get` awk 调用加 `|| true` 防止 `set -e` 退出;awk 变量 `sub` 改名 `subsec` 避开 gawk 内建冲突。
- 新增调试文档与部署指南。

## 2.0.0

- SkillHub TRACE 评测优化:异常处理、智能触发、反模式、效果示例。

## 1.1.0

- 优化文档结构,新增 FAQ/快速开始/限制说明,脚本增加容错。
