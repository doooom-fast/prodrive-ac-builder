"""SCS (ATS / ETS2) → Assetto Corsa source adapter.

Produces the same intermediate artifacts as the GPS pipeline (``data/centerline.geojson`` plus a
region/item manifest and converted assets) from an SCS truck-sim game archive, so the geometry →
Blender → kn5 back-half is reused unchanged. See ``docs/scs-to-ac-plan.md``.

Scaffold: interfaces and orchestration are defined here; external-tool calls raise
``NotImplementedError`` until wired in (see ``scripts/scs/README.md``).
"""
