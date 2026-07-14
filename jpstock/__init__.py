"""jpstock - 日本株の情報をまとめて取得・表示する CLI ツール."""

__version__ = "0.1.0"

from .models import StockSummary

__all__ = ["StockSummary", "__version__"]
