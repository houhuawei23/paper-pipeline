# 外部依赖说明

`paper-pipeline` 本身只负责流程编排。实际能力由外部工具提供。

## 1) arxiv2md-beta

用途：将 arXiv 论文转换为 Markdown。

要求：Python 包 `arxiv2md_beta` 可导入。

验证：

```bash
python -c "import arxiv2md_beta; print('ok')"
```

## 2) ask-llm

用途：翻译 Markdown（`ask-llm trans`）。

要求：

- 命令 `ask-llm` 在 `PATH`
- 或可通过 `--ask-llm-dir` 指向项目目录

验证：

```bash
ask-llm --help
```

## 3) mineru-parse

用途：解析 PDF 到 Markdown 素材目录。

要求：命令 `mineru-parse` 在 `PATH`。

验证：

```bash
mineru-parse --help
```

## 4) markdown_regex_replace（可选）

用途：按规则文件进行 Markdown 正则格式化。

行为：

- 若缺失，不会中断主流程
- 仅在你启用格式化且规则文件存在时生效

## 常见安装方式

你可以根据自己的环境选择安装方式（pip、pipx、源码 editable 等）。一个常见示例：

```bash
pip install -e .
# 外部工具按各自项目文档安装
```

## 失败排查

- 提示“未找到 arxiv2md_beta”：
  - 检查包是否安装到当前 Python 环境
- 提示“未找到 ask_llm”：
  - 安装 `ask-llm`，或加 `--ask-llm-dir`
- 提示“未找到 mineru-parse”：
  - 安装 MinerU 解析工具并确认命令可执行
