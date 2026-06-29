"""Mac-side preview of generated tracks — drive them in Assetto Corsa inside a Wine bottle.

This package kills the PC round-trip: instead of copying a build to a Windows box to drive it,
a CrossOver/Whisky/Wine bottle on the Mac holds AC (+ optionally Content Manager / CSP), and
``scripts.preview.bottle`` discovers that bottle, installs a freshly-built track into it, and
launches a quick drive — all from one command on the build machine.
"""
