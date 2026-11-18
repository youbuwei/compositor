# Changelog

> 条目整理自 git 历史。

## 1.2.0

- 安全强化(回应 skills.sh Snyk 审计 W011/W012):pip 安装命令钉住 `markitdown==0.1.6` 实测版本;声明转换出的第三方内容(网页/EPUB/YouTube 等)仅是数据、绝不当指令执行。

## 1.1.0

- 初始发布:MarkItDown 文件转 Markdown 技能(基于微软 MarkItDown v0.1.6)。
- 附安装与配置指南。
- 移除 Hermes 专属路径,兼容 ClawHub。
