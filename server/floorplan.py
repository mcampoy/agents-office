"""Floor plan made to measure: only the rooms a project can use, each with the desks it needs.

configure.py uses it for the profiles it generates (a hand-made profile, like equipo-idi's, keeps its own
layout.json). The result is a layout.json in the Pixel Agents format (version 1), the same one the web editor
saves. Three bands, so the plan stays wide and low like the screen:

    row 0        paintings and shelves hanging on the top wall
    1            top wall
    2-9          owner | coordination | top work rooms
    10           wall with doors
    11-14        corridor: café (lounge) | passage | verification | reception (the exit)
    15           wall with doors
    16-22        bottom work rooms | coworking (floating, always last)
    23           bottom wall

The owner's and coordination offices keep a fixed geometry: the floor relies on it (owner's desk, boards,
the door between both offices). Work rooms grow with their desks: two rows of desks, four tiles per desk.
Rooms go to the band that keeps the plan narrowest; the last room of each band takes the leftover width.
"""
import itertools
import math

ROWS = 24
BOTTOM = (16, 22)
WALL, VOID = 0, 255
WALL_COLOR = {"h": 214, "s": 30, "b": -100, "c": -55}
WOOD = (7, {"h": 25, "s": 48, "b": -43, "c": -88})
LIGHT_WOOD = (7, {"h": 30, "s": 40, "b": -25, "c": -80})
TILE = (1, {"h": 209, "s": 39, "b": -25, "c": -80})
GREEN_TILE = (1, {"h": 150, "s": 25, "b": -25, "c": -80})
VIOLET_TILE = (1, {"h": 265, "s": 25, "b": -30, "c": -80})
GRAY = (4, {"h": 220, "s": 8, "b": -20, "c": -30})
CARPET = (1, {"h": 345, "s": 35, "b": -35, "c": -60})

# Area color and floor of the known zones; any other zone of a project gets one from EXTRA
STYLE = {
    "owner": ("#e0b050", WOOD),
    "coordination": ("#d07a4a", LIGHT_WOOD),
    "exploration": ("#4a90d0", TILE),
    "lounge": ("#c06090", CARPET),
    "verification": ("#9060d0", GRAY),
    "reception": ("#60b0a0", GRAY),
    "reading": ("#50a060", WOOD),
    "base": ("#5070c0", TILE),
    "communication": ("#c05050", VIOLET_TILE),
    "floating": ("#a0a0a0", GREEN_TILE),
}
EXTRA = [("#c0a040", TILE), ("#40a0c0", LIGHT_WOOD), ("#a05080", VIOLET_TILE), ("#70a040", GREEN_TILE)]

# Rooms that are always there (the floor needs them); the corridor ones are not work rooms
FIXED = ("owner", "coordination", "lounge", "reception", "floating")
CORRIDOR = ("lounge", "verification", "reception")
OFFICE_W = 9            # owner and coordination
CAFE_W = 10            # the armchairs, the coffee table and a plant
RECEPTION_W = 7
MIN_ROOM_W = 9
DESK_STEP = 4           # a desk is 3 tiles wide, plus one to walk


def room_width(desks):
    """Two rows of desks, four tiles each, plus the margins."""
    return max(MIN_ROOM_W, DESK_STEP * math.ceil(desks / 2) + 2)


class Plan:
    def __init__(self, cols):
        self.cols = cols
        self.tiles = [VOID] * (cols * ROWS)
        self.colors = [None] * (cols * ROWS)
        self.areas = [None] * (cols * ROWS)
        self.furniture = []

    def i(self, c, r):
        return r * self.cols + c

    def floor(self, c, r, floor, area):
        kind, color = floor
        self.tiles[self.i(c, r)] = kind
        self.colors[self.i(c, r)] = dict(color)
        self.areas[self.i(c, r)] = area

    def wall(self, c, r):
        self.tiles[self.i(c, r)] = WALL
        self.colors[self.i(c, r)] = dict(WALL_COLOR)
        self.areas[self.i(c, r)] = None

    def room(self, label, floor, c0, c1, r0, r1):
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                self.floor(c, r, floor, label)

    def item(self, kind, c, r):
        self.furniture.append({"uid": f"plan-{len(self.furniture) + 1:03d}", "type": kind, "col": c, "row": r})

    def office_desk(self, c, r):
        """Front desk at (c, r+1) with the chair behind (above): the agent faces the front."""
        self.item("CUSHIONED_CHAIR_FRONT", c + 1, r)
        self.item("DESK_FRONT", c, r + 1)
        self.item("PC_BACK", c + 2, r + 1)

    def desk(self, c, r, pc=True):
        """3×2 front desk at (c, r), PC on top and bench below: the agent sits with its back to us."""
        self.item("DESK_FRONT", c, r)
        if pc:
            self.item("PC_FRONT_OFF", c + 1, r)
        self.item("CUSHIONED_BENCH", c + 1, r + 2)

    def desks(self, c0, r0, count, pc=True):
        """`count` desks in two rows (r0+1 and r0+4), left to right."""
        per_row = math.ceil(count / 2)
        for k in range(count):
            row, col = divmod(k, per_row)
            self.desk(c0 + 1 + DESK_STEP * col, r0 + 1 + 3 * row, pc)


def build(desks):
    """The plan for {zone: desks}. Zones missing from FIXED are added; reading is a shared table (four chairs).

    Returns the layout dict (version 1). Deterministic: the same input gives the same plan."""
    desks = dict(desks)
    for zone in FIXED:
        desks.setdefault(zone, 0)
    desks["floating"] = max(4, desks["floating"])
    work = [z for z in desks if z not in FIXED and z not in CORRIDOR]
    # Known rooms first, in the usual order; the project's own ones after them, alphabetically
    order = ["exploration", "reading", "base", "communication"]
    work.sort(key=lambda z: (order.index(z) if z in order else len(order), z))
    widths = {z: (MIN_ROOM_W + 2 if z == "reading" else room_width(max(2, desks[z]))) for z in work}
    widths["floating"] = room_width(desks["floating"])

    # Widths below are the column of each band's closing wall: wall 0, room, wall, room, wall...
    verification = max(2, desks.get("verification", 0)) if "verification" in desks else 0
    corridor_w = CAFE_W + 3 + (DESK_STEP * verification + 2 if verification else 0) + RECEPTION_W + 1

    def band(rooms, start):
        return start + sum(widths[z] + 1 for z in rooms)

    # Every split of the work rooms between both bands: the narrowest plan wins; on a tie, the one that keeps
    # the usual order (exploration up, the rest down)
    best = None
    for mask in itertools.product((0, 1), repeat=len(work)):
        top = [z for z, up in zip(work, mask) if up]
        bottom = [z for z, up in zip(work, mask) if not up] + ["floating"]
        right = max(band(top, 2 * (OFFICE_W + 1)), band(bottom, 0), corridor_w)
        usual = sum(up != (z == "exploration") for z, up in zip(work, mask))
        key = (right, usual, abs(band(top, 2 * (OFFICE_W + 1)) - band(bottom, 0)))
        if best is None or key < best[0]:
            best = (key, top, bottom, right)
    _, top, bottom, right = best
    cols = right + 1
    inner = right - 1      # last column inside the outer wall
    # The last room of each band takes what is left, so its wall is the outer one
    if top:
        widths[top[-1]] += right - band(top, 2 * (OFFICE_W + 1))
    widths[bottom[-1]] += right - band(bottom, 0)

    p = Plan(cols)
    for r in range(1, ROWS):
        for c in range(cols):
            p.wall(c, r)
    doors = [(10, 5), (10, 6)]   # owner ↔ coordination

    # Top band
    style = dict(STYLE)
    extra = iter(EXTRA * 4)
    for z in work:
        style.setdefault(z, next(extra))
    p.room("owner", style["owner"][1], 1, OFFICE_W, 2, 9)
    p.room("coordination", style["coordination"][1], OFFICE_W + 2, 2 * OFFICE_W + 1, 2, 9)
    doors += [(5, 10), (OFFICE_W + 6, 10)]
    c = 2 * OFFICE_W + 3
    placed = {"owner": (1, 2), "coordination": (OFFICE_W + 2, 2)}
    for z in top:
        p.room(z, style[z][1], c, c + widths[z] - 1, 2, 9)
        placed[z] = (c, 2)
        doors.append((c + widths[z] // 2, 10))
        c += widths[z] + 1
    # Bottom band
    c = 1
    for z in bottom:
        p.room(z, style[z][1], c, c + widths[z] - 1, *BOTTOM)
        placed[z] = (c, BOTTOM[0])
        doors.append((c + widths[z] // 2, 15))
        c += widths[z] + 1
    # Corridor: one continuous floor (no walls between its stretches)
    reception_c0 = inner - RECEPTION_W + 1
    p.room("lounge", style["lounge"][1], 1, CAFE_W, 11, 14)
    p.room(None, GRAY, CAFE_W + 1, reception_c0 - 1, 11, 14)
    if verification:
        v0 = reception_c0 - (DESK_STEP * verification + 2) - 1
        p.room("verification", style["verification"][1], v0, reception_c0 - 1, 11, 14)
        for k in range(verification):
            p.desk(v0 + 1 + DESK_STEP * k, 11)
    p.room("reception", style["reception"][1], reception_c0, inner, 11, 14)
    for cc, rr in doors:
        p.floor(cc, rr, GRAY, None)

    # Owner: desk (the boards stand below it), bookshelf, painting, plant, bin
    p.office_desk(4, 3)
    p.item("DOUBLE_BOOKSHELF", 1, 0)
    p.item("LARGE_PAINTING", 7, 0)
    p.item("PLANT", 1, 7)
    p.item("BIN", 8, 5)
    # Coordination: the main agent's desk and the whiteboard
    c0 = OFFICE_W + 2
    p.office_desk(c0 + 3, 3)
    p.item("WHITEBOARD", c0 + 1, 0)
    p.item("SMALL_PAINTING", c0 + 7, 0)
    p.item("PLANT_2", c0 + 8, 7)
    # Café: armchairs around the coffee table; the archive (engram) is the bookshelf on its wall
    p.item("SOFA_FRONT", 5, 11)
    p.item("SOFA_SIDE", 4, 12)
    p.item("COFFEE_TABLE", 5, 12)
    p.item("SOFA_SIDE:left", 7, 12)
    p.item("SOFA_BACK", 5, 14)
    p.item("COFFEE", 6, 13)
    p.item("DOUBLE_BOOKSHELF", 8, 9)
    p.item("PLANT", CAFE_W - 1, 13)
    p.item("POT", CAFE_W, 14)
    # Reception: benches for agents without a room, near the exit
    for k in range(RECEPTION_W - 3):
        p.item("WOODEN_BENCH", reception_c0 + 1 + k, 12)
    p.item("PLANT_2", inner, 11)
    # Work rooms
    for z in work + ["floating"]:
        c0, r0 = placed[z]
        if z == "reading":
            p.item("TABLE_FRONT", c0 + 4, r0 + 2)
            p.item("WOODEN_CHAIR_SIDE", c0 + 3, r0 + 2)
            p.item("WOODEN_CHAIR_SIDE", c0 + 3, r0 + 4)
            p.item("WOODEN_CHAIR_SIDE:left", c0 + 7, r0 + 2)
            p.item("WOODEN_CHAIR_SIDE:left", c0 + 7, r0 + 4)
            p.item("BOOKSHELF", c0, r0 + 6)
        else:
            p.desks(c0, r0, max(2, desks[z]) if z != "floating" else desks[z], pc=z != "floating")
        p.item("PLANT_2", c0 + widths[z] - 1, r0)
    if "exploration" in placed:
        c0, _ = placed["exploration"]
        p.item("CLOCK", c0 + widths["exploration"] - 2, 0)

    return {
        "version": 1,
        "cols": cols,
        "rows": ROWS,
        "layoutRevision": 1,
        "tiles": p.tiles,
        "tileColors": p.colors,
        "furniture": p.furniture,
        "pets": [],
        "areas": [{"label": z, "color": style[z][0]} for z in style if z in desks],
        "areaTiles": p.areas,
    }


SEATS = ("CUSHIONED_CHAIR", "CUSHIONED_BENCH", "WOODEN_CHAIR", "WOODEN_BENCH", "SOFA_")


def seats_by_zone(layout):
    """Seats in each zone of an existing layout (to tell whether the team still fits)."""
    cols = layout["cols"]
    areas = layout.get("areaTiles") or []
    out = {}
    for f in layout.get("furniture", []):
        k = f["row"] * cols + f["col"]
        if f["type"].startswith(SEATS) and 0 <= k < len(areas) and areas[k]:
            out[areas[k]] = out.get(areas[k], 0) + 1
    return out


def short_of(layout, needed):
    """Zones of `needed` missing from the layout or with fewer seats than needed (without the headroom)."""
    seats = seats_by_zone(layout)
    return sorted(z for z, n in needed.items() if seats.get(z, 0) < n - 1)


def desks_needed(zone_rules, generic_rules, headroom=1):
    """Desks per zone: one per project agent with a rule, two per room a generic subagent type goes to,
    plus `headroom` so the team can grow a little before the plan needs regenerating."""
    need = {}
    for rule in zone_rules:
        if "*" in rule["agent"]:
            need.setdefault(rule["zone"], 0)
            continue
        need[rule["zone"]] = need.get(rule["zone"], 0) + 1
    for zone in {r["zone"] for r in generic_rules}:
        need[zone] = need.get(zone, 0) + 2
    return {z: n + headroom for z, n in need.items() if z not in ("owner", "coordination")}
