#!/usr/bin/env python3
"""兼容入口：转发到 ``paper_pipeline.cli``。"""

from paper_pipeline.cli import app


if __name__ == "__main__":
    app()
