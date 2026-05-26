#!/usr/bin/env python3
"""Skills IE 信息抽取系统入口。"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from skills_ie.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
