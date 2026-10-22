"""Exit statuses: the CLI's observable contract.

The statuses `bump-version` exits with, documented for users in
README.md under "Exit statuses". Scripts branch on these, so every exit site
names one rather than a bare integer. This module imports nothing from the
package, so every other module may import it.
"""

from __future__ import annotations

EXIT_OK = 0  # Success, including a genuine no-op and a declined optional step
EXIT_FAILURE = 1  # Something went wrong
EXIT_DECLINED = 2  # The operator declined the operation; nothing was changed
EXIT_INTERRUPTED = 130  # EOF or Ctrl-C (128 + SIGINT, the shell convention)
