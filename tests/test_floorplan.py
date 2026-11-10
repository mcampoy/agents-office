"""The floor plan made to measure (server/floorplan.py)."""
import sys
import unittest
from collections import deque
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from configure import GENERIC_RULES  # noqa: E402
from server import floorplan  # noqa: E402


def rooms(layout):
    return {a["label"] for a in layout["areas"]}


def reachable(layout):
    """Zones reachable walking from the owner's office (furniture aside)."""
    cols, rows, tiles, areas = layout["cols"], layout["rows"], layout["tiles"], layout["areaTiles"]
    start = areas.index("owner")
    seen, queue = {start}, deque([start])
    while queue:
        k = queue.popleft()
        c, r = k % cols, k // cols
        for n in ((c + 1, r), (c - 1, r), (c, r + 1), (c, r - 1)):
            j = n[1] * cols + n[0]
            if 0 <= n[0] < cols and 0 <= n[1] < rows and j not in seen and tiles[j] not in (floorplan.WALL, floorplan.VOID):
                seen.add(j)
                queue.append(j)
    return {areas[k] for k in seen if areas[k]}


class FloorPlan(unittest.TestCase):
    def test_only_the_rooms_it_needs(self):
        layout = floorplan.build(floorplan.desks_needed([], GENERIC_RULES))
        self.assertEqual(rooms(layout), {"owner", "coordination", "lounge", "reception", "floating",
                                         "exploration", "reading", "base", "verification"})
        self.assertLess(layout["cols"], 48)
        self.assertLess(layout["rows"], 28)

    def test_consistent_and_every_room_reachable(self):
        layout = floorplan.build({"exploration": 7, "communication": 3, "base": 2, "verification": 2, "radar": 1})
        n = layout["cols"] * layout["rows"]
        self.assertEqual((len(layout["tiles"]), len(layout["tileColors"]), len(layout["areaTiles"])), (n, n, n))
        self.assertEqual(reachable(layout), rooms(layout))
        # The outer wall is closed: the first and last columns are wall or void on every row
        for r in range(layout["rows"]):
            for c in (0, layout["cols"] - 1):
                self.assertIn(layout["tiles"][r * layout["cols"] + c], (floorplan.WALL, floorplan.VOID))

    def test_every_room_has_its_desks(self):
        needed = {"exploration": 7, "base": 3, "radar": 2, "floating": 5}
        seats = floorplan.seats_by_zone(floorplan.build(needed))
        for zone, n in needed.items():
            self.assertGreaterEqual(seats.get(zone, 0), n, zone)
        self.assertEqual(floorplan.short_of(floorplan.build(needed), needed), [])

    def test_a_grown_team_no_longer_fits(self):
        layout = floorplan.build({"exploration": 2})
        self.assertEqual(floorplan.short_of(layout, {"exploration": 6, "verification": 2}), ["exploration", "verification"])

    def test_deterministic(self):
        needed = floorplan.desks_needed([{"agent": "radar", "zone": "exploration"}], GENERIC_RULES)
        self.assertEqual(floorplan.build(needed), floorplan.build(needed))

    def test_needed_desks(self):
        own = [{"agent": "lente-*", "zone": "reading"}, {"agent": "main", "zone": "coordination"},
               {"agent": "investigador", "zone": "exploration"}, {"agent": "radar", "zone": "exploration"}]
        need = floorplan.desks_needed(own, [{"agent": "Explore", "zone": "exploration"}])
        # Two agents + two for the generic type + one of headroom; the main agent has its own office
        self.assertEqual(need, {"reading": 1, "exploration": 5})


if __name__ == "__main__":
    unittest.main()
