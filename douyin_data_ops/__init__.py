"""Root package bridge for running unittest without installing the project."""

from pathlib import Path


__version__ = "0.1.0"
__path__ = [str(Path(__file__).resolve().parent.parent / "src" / "douyin_data_ops")]

