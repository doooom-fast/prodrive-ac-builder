"""audit_mesh check C (junction crossings) rebuilds trimmed decks via a lazy import of
build_network_mesh helpers, and downgrades ANY exception to "(check C skipped: ...)". In this repo
build_network_mesh exists, so that import must keep resolving — if one of these helpers is renamed,
check C silently stops running on every network build forever. This pins the contract.
"""


def test_check_c_helper_imports_resolve():
    from scripts.geometry.build_network_mesh import (  # noqa: F401
        _grade_cap_y,
        _layer_lift,
        _trim_ramp_merge,
    )
