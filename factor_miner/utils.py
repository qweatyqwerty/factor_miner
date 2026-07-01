"""通用工具函数."""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import yaml


def setup_logging(level: str = "INFO") -> logging.Logger:
    """配置日志."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return logging.getLogger("factor_miner")


def load_config(path: str = "config.yaml") -> Dict[str, Any]:
    """加载 YAML 配置文件."""
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {cfg_path.absolute()}")
    with cfg_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_dir(path: str) -> Path:
    """确保目录存在，返回 Path 对象."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def today_str(fmt: str = "%Y%m%d") -> str:
    """返回当前日期字符串."""
    return datetime.now().strftime(fmt)
