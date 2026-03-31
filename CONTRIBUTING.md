# Contributing

感谢贡献。

## 开发环境

```bash
git clone <repo-url>
cd paper_pipeline
pip install -e ".[dev]"
```

## 运行测试

```bash
pytest
```

## 提交建议

- 保持变更聚焦，单个 PR 只解决一类问题
- 变更外部依赖行为时，请同步更新 `README.md` 与 `docs/EXTERNAL_DEPENDENCIES.md`
- 新增 CLI 参数时，请补充 `--help` 可读描述

## 代码风格

- Python 3.10+
- 倾向小函数、清晰错误信息
- 保持“缺少外部工具时可解释失败”
