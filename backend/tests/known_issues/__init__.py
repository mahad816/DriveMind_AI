"""Executable registry of KNOWN, UNFIXED defects (see docs/KNOWN_ISSUES.md).

Each test states the CORRECT behaviour and is marked with ``known_issue``. While the
bug exists the test fails and is reported as XFAIL, so the suite stays green. It is
``strict``: the moment a fix makes the test pass, pytest reports XPASS as a failure,
forcing whoever fixed it to delete the marker and update the registry. Nothing rots.

Only AssertionError counts as the expected failure; a crash or import error is a real
failure and is never hidden.
"""

import pytest


def known_issue(issue_id: str, summary: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(
        strict=True, raises=AssertionError, reason=f"{issue_id} (docs/KNOWN_ISSUES.md): {summary}"
    )
