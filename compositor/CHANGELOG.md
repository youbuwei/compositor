# Changelog

## 1.1.0 — 2026-11-18

- 新增 `scripts/comp_png.py`:零依赖(纯标准库)PNG 资产生成器(`solid`/`gradient`/`ellipse`/`rect`/`dots`/`mask`)与预览合成器(变换、不透明度、全部混合模式、链接/非链接蒙版、编组、裁剪蒙版),编辑不再需要临时脚本或 Pillow。
- 安全强化:上游文档拉取固定到 release tag(默认 v1.6.13),永不再拉 main 分支;升级 pin 前展示 release notes 并需用户批准;pin 覆盖不足时明确警告。
- 确立"需求优先、版本特性后置"的工作原则;safe-editing 检查清单同步更新。

## 1.0.0 — 2026-11-17

- 初始发布:SKILL.md 工作流(检查 → 计划 → 写素材 → 原子更新 manifest → 验证 → 汇报)。
- `scripts/fetch_format_docs.py` 自适应文档缓存;`scripts/validate_comp.py` 结构校验器。
