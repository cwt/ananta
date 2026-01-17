import warnings

# Suppress deprecation warnings from uvloop/winloop for Python 3.10+ compatibility
warnings.filterwarnings("ignore", category=DeprecationWarning)

from importlib.metadata import version

__version__ = version("ananta")

# ANSI escape codes for text colors
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"
RESET = "\033[0m"

# Large height for long outputs
LINES = 1000
