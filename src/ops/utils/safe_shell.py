import shlex
from typing import Any


def quote(value: Any) -> str:
    """Safely quote a value for shell interpolation.

    Uses shlex.quote() to escape any shell metacharacters.
    None is converted to an empty string.
    """
    if value is None:
        return "''"
    return shlex.quote(str(value))


def safe_cmd(base: str, *args: Any) -> str:
    """Build a shell command by safely quoting all positional arguments.

    Usage:
        safe_cmd("mkdir -p {}", remote_path)
        safe_cmd("chown {}:{}", user, user)
    """
    quoted = [quote(a) for a in args]
    return base.format(*quoted)
