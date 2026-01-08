"""Pipeline package

Initial scaffolding for an idiomatic package layout. This package will
gradually encapsulate orchestration logic for the four modules and expose a
clean API and CLI.

Current contents
- config: shared configuration dataclass for run parameters
- logging: minimal logger setup and step logging helper

No behavior is changed by this package in step 1; existing scripts continue to
run as before. Subsequent steps will wire cost_service and module runners to
these utilities.
"""

from .config import Config
from .logging import get_logger, log_step

__all__ = ["Config", "get_logger", "log_step"]

