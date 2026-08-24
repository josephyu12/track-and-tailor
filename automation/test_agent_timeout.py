#!/usr/bin/env python3
"""Agent timeout must kill the whole process group, not hang on grandchild pipes."""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from daily_run import run_agent_cmd  # noqa: E402

# Parent + grandchild both sleep. Killing only the parent leaves the grandchild
# holding stdout, which is what made subprocess.run(timeout=) hang for ~1h.
HANG_SCRIPT = r"""
import os, time
if os.fork() == 0:
    while True:
        time.sleep(1)
print("started", flush=True)
while True:
    time.sleep(1)
"""


class AgentTimeout(unittest.TestCase):
    def test_timeout_returns_instead_of_hanging_on_grandchild(self) -> None:
        t0 = time.time()
        code, out, timed_out = run_agent_cmd(
            [sys.executable, "-c", HANG_SCRIPT],
            timeout=1,
            cwd=str(Path(__file__).resolve().parent),
            env=os.environ.copy(),
        )
        elapsed = time.time() - t0
        self.assertTrue(timed_out)
        self.assertLess(elapsed, 12, msg=f"hung {elapsed:.1f}s; process group was not killed")
        self.assertIn("started", out)

    def test_fast_command_is_not_timed_out(self) -> None:
        code, out, timed_out = run_agent_cmd(
            [sys.executable, "-c", "print('ok')"],
            timeout=10,
            cwd=str(Path(__file__).resolve().parent),
            env=os.environ.copy(),
        )
        self.assertFalse(timed_out)
        self.assertEqual(code, 0)
        self.assertIn("ok", out)


if __name__ == "__main__":
    unittest.main()
