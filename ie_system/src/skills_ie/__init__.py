"""Skills IE 包对外暴露的核心接口。"""

from .config import IEConfig, load_config
from .extractor import SkillsIESystem

__all__ = ["IEConfig", "SkillsIESystem", "load_config"]
