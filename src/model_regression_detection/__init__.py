"""Model Regression Detection System package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("model-regression-detection-system")
except PackageNotFoundError:  # pragma: no cover - only possible outside an installed environment
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
