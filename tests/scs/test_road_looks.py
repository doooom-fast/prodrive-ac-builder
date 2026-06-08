"""road_look.sii parsing -> CrossSection."""

import tempfile
from pathlib import Path

from scripts.scs.road_looks import CrossSection, parse_road_looks

SII = """SiiNunit
{
road_look : highway.look {
    lanes_left: 2
    lanes_right: 2
    lane_width: 3.75
    shoulder_size_right: 2.5
}
road_look : local.look {
    lanes_left: 1
    lanes_right: 1
    lane_width: 3.0
}
}
"""


def test_parse_road_looks():
    with tempfile.TemporaryDirectory() as d:
        world = Path(d) / "def" / "world"
        world.mkdir(parents=True)
        (world / "road_look.sii").write_text(SII)
        looks = parse_road_looks(Path(d))
    assert set(looks) == {"highway.look", "local.look"}, list(looks)
    hw = looks["highway.look"]
    assert (hw.lanes_left, hw.lanes_right) == (2, 2)
    assert hw.lane_width_m == 3.75 and hw.shoulder_m == 2.5
    assert hw.total_width_m == 20.0  # (2+2)*3.75 + 2*2.5
    assert looks["local.look"].total_width_m == 6.0  # (1+1)*3.0


def test_cross_section_default_total():
    assert CrossSection("x").total_width_m == 9.0  # (1+1)*4.5
