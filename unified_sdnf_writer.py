from pathlib import Path
from datetime import datetime

class UnifiedSDNFWriter:
    """SDNF 3.0 writer using the exact structures validated in Forum."""

    def __init__(self, floor_height=3.3):
        self.floor_height = float(floor_height)
        self.next_id = 1

    def _packet00(self):
        now = datetime.now()
        return [
            "Packet 00",
            '"SDNF Version 3.0"',
            '""',
            '""',
            '"NONAME"',
            '"CENTERLINES"',
            f'"{now:%d.%m.%Y}" "{now:%H:%M:%S}"',
            '0 ""',
            '""',
            '0',
        ]

    def _column(self, object_id, x, y, z1=0.0, z2=None):
        if z2 is None:
            z2 = self.floor_height
        # Exact 10-line Packet 10 structure accepted by Forum.
        return [
            f'{object_id} 10 0 0 "" "" 1',
            '" " "" 0.000000 0 1',
            f'1.000000 0.000000 0.000000 {x:.6f} {y:.6f} {z1:.6f} {x:.6f} {y:.6f} {z2:.6f} 0.0 0.0',
            '0 0',
            '0 0 0 0 0 0',
            '0 0 0 0 0 0 0 0 0 0 0 0',
            '0 "" 0 "" "" "" "" 0 0',
            '0 0 0 0 0 0 0 0 0 0 0 0',
            '0 0 0.0 0 0 0.0 0.0',
            '0 0 0 0 0 0',
        ]

    def _wall(self, object_id, x1, y1, x2, y2, thickness=0.0, z1=0.0, z2=None):
        if z2 is None:
            z2 = self.floor_height
        # Exact 16-line Packet 20 surface structure from Forum-exported wall.
        return [
            f'{object_id} 0 0 0 "slab" 0',
            f'"" "" {thickness:.6f} 5 0.0 0',
            f'{x1:.6f} {y1:.6f} {z1:.6f} 1',
            f'{x2:.6f} {y2:.6f} {z1:.6f} 1',
            f'{x2:.6f} {y2:.6f} {z2:.6f} 1',
            f'{x1:.6f} {y1:.6f} {z2:.6f} 1',
            f'{x1:.6f} {y1:.6f} {z1:.6f} 0',
            f'{x1:.6f} {y1:.6f} {z1:.6f} 1',
            f'{x2:.6f} {y2:.6f} {z1:.6f} 1',
            f'{x2:.6f} {y2:.6f} {z2:.6f} 1',
            f'{x1:.6f} {y1:.6f} {z2:.6f} 1',
            f'{x1:.6f} {y1:.6f} {z1:.6f} 0',
            '0 "" 0 "" "" "" "" 0 0',
            '0 0 0',
            '0 0 0.0 0 0',
            '0 0 0 0 0',
        ]

    def _plate(self, plate):
        # Use the validated Packet 20 writer already tested in Forum.
        pts = plate._closed(plate.contour)
        ztop = plate.z + plate.thickness / 2.0
        zbot = plate.z - plate.thickness / 2.0
        lines = [
            f'{plate.id} 0 0 0 "slab" 0',
            f'"" "" {plate.thickness:.6f} {len(pts)} 0.0 0',
        ]
        for x, y in pts:
            lines.append(f'{x:.6f} {y:.6f} {ztop:.6f} 1')
        # close marker
        lines[-1] = lines[-1][:-1] + '0'
        for x, y in pts:
            lines.append(f'{x:.6f} {y:.6f} {zbot:.6f} 1')
        lines[-1] = lines[-1][:-1] + '0'
        lines += [
            '0 "" 0 "" "" "" "" 0 0',
            '0 0 0',
            '0 0 0.0 0 0',
            '0 0 0 0 0',
        ]
        return lines

    def _opening(self, opening, parent_plate):
        pts = parent_plate._closed(opening.contour)
        ztop = parent_plate.z + parent_plate.thickness / 2.0
        zbot = parent_plate.z - parent_plate.thickness / 2.0
        lines = [
            f'{opening.id} {parent_plate.id}',
            f'0 {parent_plate.thickness:.6f} {len(pts)}',
        ]
        for x, y in pts:
            lines.append(f'{x:.6f} {y:.6f} {ztop:.6f} 1')
        lines[-1] = lines[-1][:-1] + '0'
        for x, y in pts:
            lines.append(f'{x:.6f} {y:.6f} {zbot:.6f} 1')
        lines[-1] = lines[-1][:-1] + '0'
        lines += ['0 0 0 0', '0 0 0']
        return lines

    def write(self, filename, walls, columns, plates):
        lines = self._packet00()

        # Packet 10 — columns.
        if columns:
            lines += ['Packet 10', f'"meters" {len(columns)}']
            for c in columns:
                lines += self._column(c["id"], c["x"], c["y"], c.get("z1", 0.0), c.get("z2"))
            lines += []

        # Packet 20 — walls + slabs.
        packet20_count = len(walls) + len(plates)
        lines += ['Packet 20', f'"meters" "meters" {packet20_count}']
        for w in walls:
            lines += self._wall(
                w["id"], w["x1"], w["y1"], w["x2"], w["y2"],
                w.get("thickness", 0.0), w.get("z1", 0.0), w.get("z2")
            )
        for p in plates:
            lines += self._plate(p)

        # Packet 22 — all openings.
        openings = [(p, o) for p in plates for o in p.holes]
        if openings:
            lines += ['Packet 22', f'"meters" "meters" {len(openings)}']
            for p, o in openings:
                lines += self._opening(o, p)

        Path(filename).write_text("\n".join(lines) + "\n", encoding="utf-8")
