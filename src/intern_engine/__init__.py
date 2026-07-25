"""intern-engine: a self-updating Cybersecurity + AI early-career job tracker."""

__version__ = "1.0.0"

# Keep the top-level import dependency-free: only pull in the model + enums.
from .models import Role, Category, RoleType  # noqa: F401

__all__ = ["Role", "Category", "RoleType", "__version__"]
