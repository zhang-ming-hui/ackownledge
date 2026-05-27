"""允许通过 `python -m skills_ie` 启动 CLI。"""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
