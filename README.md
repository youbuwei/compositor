# youbuwei / skills

<a href="https://www.skills.sh/youbuwei/skills"><img alt="skills.sh" src="https://www.skills.sh/b/youbuwei/skills?style=for-the-badge" height="28"></a>

A monorepo of agent skills. Each subdirectory is a self-contained skill with
its own `SKILL.md` and `CHANGELOG.md`; every skill keeps its original git
history (merged with `git subtree`).

## Skills

| Skill | What it does |
| --- | --- |
| [compositor](compositor/) | Create, inspect, and edit Compositor `.comp` layered image projects on macOS — writes the package format directly, no UI automation. |
| [profile-model-manager](profile-model-manager/) | 查看、更换和管理 Hermes 各 profile 的大模型配置（主模型、辅助模型、delegation 模型），支持单个/批量操作与 provider 切换。 |
| [github-accelerator](github-accelerator/) | Read-only GitHub fallback for public repos: direct-first mirror clone/download plus `gh api` reads. No repository writes. |
| [markitdown](markitdown/) | Convert files (PDF, Word, Excel, PowerPoint, images, audio, HTML, EPUB, ZIP, YouTube URLs) to Markdown for LLM pipelines, indexing, and analysis. |

## Plugin

| Package | What it does |
| --- | --- |
| [dsh-zhipu-mcp](dsh-zhipu-mcp/) | DeepSeek Harness plugin bundling the Zhipu BigModel MCP trio (web search / web reader / GitHub repo reader). Install with `dsh plugin --profile web add dsh-zhipu-mcp@latest` — it is not an agent skill and has no `SKILL.md`. |

## Install

With the [`skills`](https://github.com/vercel-labs/skills) CLI (Node.js ≥ 22.20):

```bash
npx skills add youbuwei/skills              # every skill in this repo
npx skills add youbuwei/skills/compositor   # just one
```

See each skill's own README for details.
