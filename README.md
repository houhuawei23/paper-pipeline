# paper-pipeline

一个用于论文自动化处理的 CLI，支持：

- arXiv ID 批量下载与处理
- 本地 PDF 与 PDF URL 处理
- Markdown 格式化
- 可选翻译（通过外部 `ask-llm`）

本项目本身是“编排层”，核心解析/翻译能力依赖外部工具（见下文）。

## 功能特性

- **统一入口**：一个命令处理 arXiv / PDF / URL
- **TTY 友好**：终端环境下尽量保留外部工具实时进度
- **并发支持**：arXiv 批量可用 `--threads` 并发
- **输出定位稳健**：支持 sidecar、日志解析、目录差分、mtime 兜底
- **可安装为命令**：`paper-pipeline`

## 项目结构

```text
paper_pipeline/
├── paper_pipeline/
│   ├── cli.py
│   ├── arxiv_flow.py
│   ├── pdf_flow.py
│   ├── subprocess_runner.py
│   ├── output_locator.py
│   ├── validation.py
│   └── ...
├── process_paper_pipeline_beta.py   # 向后兼容脚本入口（转发到包内 CLI）
├── tests/
├── pyproject.toml
├── README.md
└── CONTRIBUTORS.md
```

## 版本变更

- **v0.3.0**
  - arXiv 输出目录与文件命名改为 `Arxiv-<date>-<title>` 方案，内部 Markdown 固定为 `paper.md` / `Appendix.md` / `References.md`，翻译产物固定为 `*_trans.md`，PDF 命名为 `<目录名>.pdf`。
  - 通过向 `arxiv2md-beta` 传递 `--naming-scheme paper-pipeline`、向 `ask-llm trans` 传递 `--translated-suffix _trans` 直接生成目标文件名，移除流水线中的事后 rename 逻辑。
  - 依赖包同步更新：`arxiv2md-beta` 新增 `--naming-scheme` 参数，`ask-llm` 新增 `--translated-suffix` 参数。
  - 统一 `__init__.py` 与 `pyproject.toml` 的版本号为 `0.3.0`。

- **v0.2.1**
  - 修复 `validation.detect_input_type` 对带版本号 ID（如 `2501.11120v2`）的处理逻辑。
  - 修复 `--no-arxiv-progress` 在并行或显式指定时可能重复传入 `--no-progress` 的问题。
  - 清理 `pdf_flow.rename_full_md_to_pdf_name` 中的不可达分支。
  - `formatting.py` 仅在 `tools/` 目录存在时才将其加入 `sys.path`，避免已安装包环境下的副作用。
  - 统一 `__init__.py` 与 `pyproject.toml` 的版本号为 `0.2.1`。
  - 补充 `validation` 模块的边界测试用例。

- **v0.2.0**
  - arXiv 论文翻译时，标题、作者、ArXiv 等元数据不再被单独提取保留，而是与正文一起交给 `ask-llm trans` 翻译。
  - 移除 `paper_pipeline/preamble_split.py` 及相关测试。
  - 日志文件名增加时分秒，避免同一天多次运行覆盖。
  - PDF 流程优先复用已存在的 `{stem}.md`，减少重复重命名。

## 环境要求

- Python 3.10+
- 推荐：`pipx` 或虚拟环境（`venv` / `uv` / `conda`）

## 安装

### 1) 安装本项目

```bash
git clone <your-repo-url>
cd paper_pipeline
pip install -e .
```

安装后可使用命令：

```bash
paper-pipeline --help
```

### 2) 安装外部依赖工具

本项目依赖以下外部工具：

- `arxiv2md-beta`（arXiv 转 Markdown）
- `ask-llm`（翻译）
- `mineru-parse`（PDF 解析）
- 可选：`markdown_regex_replace.py`（正则格式化规则）

详细安装方法见：`docs/EXTERNAL_DEPENDENCIES.md`

## 快速开始

### 处理一篇 arXiv

```bash
paper-pipeline 2501.11120 -o ./output
```

### 批量处理 arXiv

```bash
# 逗号分隔
paper-pipeline "2501.11120,2401.12345" -o ./output --threads 4

# 文件输入（每行一个 ID）
paper-pipeline ./arxiv_ids.txt -o ./output --threads 4
```

### 处理本地 PDF

```bash
paper-pipeline ./paper.pdf --source Arxiv --short Demo
```

### 处理 PDF URL

```bash
paper-pipeline "https://example.com/paper.pdf" -o ./output
```

## 常用参数

- `-o, --output`：输出目录（arXiv 模式必填）
- `--ask-llm-dir`：手动指定 `ask_llm` 工程目录
- `--skip-translation`：跳过翻译
- `--skip-formatting`：跳过 regex 格式化
- `--skip-prettier`：跳过 prettier
- `-T, --threads`：arXiv 并发数
- `--no-arxiv-progress`：传给 `arxiv2md-beta` 关闭进度条
- `-v, --verbose` / `-q, --quiet`：日志级别

## 外部依赖定位策略

默认情况下，本项目会尝试自动发现外部依赖。你也可以显式指定：

- `--ask-llm-dir <path>`
- 环境变量 `PAPER_PIPELINE_REPO_ROOT`（用于推断 `academic/arxiv2md-beta` 等相对路径）

## 开发

```bash
pip install -e ".[dev]"
pytest
```

## 兼容入口

仍可使用旧脚本入口：

```bash
python process_paper_pipeline_beta.py --help
```

它会转发到包内 CLI，便于旧流程平滑迁移。

## 发布到 GitHub 建议

1. 确保忽略无关本地文件（如 `__pycache__`, `.pytest_cache`）。
2. 在 README 中明确“本项目依赖外部工具”。
3. 附带最小可运行示例与参数说明。
4. 若对外开源，建议补充 `LICENSE` 与 `CONTRIBUTING.md`。

## Contributors

参见 [CONTRIBUTORS.md](CONTRIBUTORS.md)。

## License

建议在发布仓库时添加许可证（例如 MIT）。当前仓库未内置许可证文件。
