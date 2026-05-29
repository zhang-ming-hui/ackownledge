#!/usr/bin/env python3
"""
Skills IE 信息抽取系统入口。

本项目同时包含 IR（信息检索）和 IE（信息抽取）两个子系统。
IE 子系统负责从爬取的技能描述文本中自动抽取结构化字段：
  - platforms：支持的平台/工具
  - languages：使用的编程语言/框架
  - action_types：执行的动作类型
  - target_domains：面向的应用领域
  - output_formats：输出格式

入口通过 Python 路径注入将 src/ 加入 sys.path，保证 skills_ie 包可导入。
CLI 主逻辑委托给 src/skills_ie/cli.py 中的 main() 函数。

用法示例：
  python ie_system/skills_ie_system.py extract --variant enhanced
  python ie_system/skills_ie_system.py evaluate --variant enhanced
"""
import sys
from pathlib import Path

# 仓库根目录 = 本文件所在目录（ie_system/）
REPO_ROOT = Path(__file__).resolve().parent

# src/ 目录存放 skills_ie 包，需要加入导入路径
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from skills_ie.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
