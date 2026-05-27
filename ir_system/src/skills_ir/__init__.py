"""Skills IR 包对外暴露的核心接口。"""

from .config import IRConfig, load_config
from .engine import SkillsIRSystem

__all__ = ["IRConfig", "SkillsIRSystem", "load_config"]
