#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CENTERLINES — Building Builder v0.2

Многоэтажная сборка поверх существующего одноэтажного ядра.

Этапы:
1. Проверка building.json.
2. Расчёт Z этажей.
3. Для каждого физического этажа запускается существующий centerlines.py.
4. Через функции существующего agent.py читаются стены/колонны/плиты.
5. Для каждого этажа назначается абсолютная отметка Z.
6. Все объекты объединяются в одну модель.
7. Формируется единый building.sdnf.

Существующее одноэтажное ядро centerlines.py не изменяется.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ALLOWED_TYPES = {"basement", "single", "repeat", "last"}
DEFAULT_SLAB_THICKNESS_MM = 200.0


class ConfigError(Exception):
    pass


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Файл конфигурации не найден: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"Ошибка JSON в {path.name}: строка {exc.lineno}, столбец {exc.colno}: {exc.msg}"
        ) from exc

    if not isinstance(data, dict):
        raise ConfigError("Корень building.json должен быть объектом.")
    return data


def require_number(value: Any, field: str, allow_negative: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"Поле '{field}' должно быть числом.")
    value = float(value)
    if not allow_negative and value < 0:
        raise ConfigError(f"Поле '{field}' не может быть отрицательным.")
    return value


def validate_and_build(config: dict[str, Any], project_root: Path) -> list[dict[str, Any]]:
    building = config.get("building")
    blocks = config.get("blocks")

    if not isinstance(building, dict):
        raise ConfigError("Отсутствует объект 'building'.")
    if not isinstance(blocks, list) or not blocks:
        raise ConfigError("Поле 'blocks' должно содержать хотя бы один блок.")

    first_floor_level = require_number(
        building.get("first_floor_level", 0.0),
        "building.first_floor_level",
    )

    for i, block in enumerate(blocks, start=1):
        if not isinstance(block, dict):
            raise ConfigError(f"Блок №{i} должен быть объектом.")

        for field in ("name", "type", "file", "count", "height", "slab_thickness_mm"):
            if field not in block:
                raise ConfigError(f"Блок №{i}: отсутствует поле '{field}'.")

        block_type = block["type"]
        if block_type not in ALLOWED_TYPES:
            raise ConfigError(
                f"Блок №{i}: неизвестный type '{block_type}'. "
                f"Допустимо: {', '.join(sorted(ALLOWED_TYPES))}."
            )

        if not isinstance(block["name"], str) or not block["name"].strip():
            raise ConfigError(f"Блок №{i}: 'name' должен быть непустой строкой.")

        if not isinstance(block["file"], str) or not block["file"].strip():
            raise ConfigError(f"Блок №{i}: 'file' должен быть непустой строкой.")

        count = block["count"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ConfigError(f"Блок №{i}: 'count' должен быть целым числом >= 1.")

        height = require_number(
            block["height"], f"blocks[{i}].height", allow_negative=False
        )
        slab_thickness_mm = require_number(
            block["slab_thickness_mm"],
            f"blocks[{i}].slab_thickness_mm",
            allow_negative=False,
        )
        if slab_thickness_mm <= 0:
            raise ConfigError(
                f"Блок №{i}: толщина плиты должна быть больше 0 мм."
            )

        if block_type == "basement" and i != 1:
            raise ConfigError("Блок типа 'basement' должен быть первым.")
        if block_type == "last" and i != len(blocks):
            raise ConfigError("Блок типа 'last' должен быть последним.")
        if block_type == "repeat" and count < 2:
            raise ConfigError("Блок type='repeat' должен иметь count >= 2.")

    floors: list[dict[str, Any]] = []

    basement_blocks = [b for b in blocks if b["type"] == "basement"]
    if basement_blocks:
        b = basement_blocks[0]
        z = first_floor_level - float(b["height"])
        floors.append({
            "floor_number": 0,
            "name": b["name"],
            "type": b["type"],
            "file": b["file"],
            "z": z,
            "height": float(b["height"]),
            "slab_thickness_mm": float(b["slab_thickness_mm"]),
        })

    current_z = first_floor_level
    floor_number = 1

    for block in blocks:
        if block["type"] == "basement":
            continue

        count = int(block["count"])
        height = float(block["height"])

        for repeat_index in range(count):
            floors.append({
                "floor_number": floor_number,
                "name": block["name"],
                "type": block["type"],
                "file": block["file"],
                "z": current_z,
                "height": height,
                "slab_thickness_mm": float(block["slab_thickness_mm"]),
                "repeat_index": repeat_index + 1,
            })
            floor_number += 1
            current_z += height

    missing = []
    for floor in floors:
        if not (project_root / floor["file"]).exists():
            missing.append(floor["file"])

    if missing:
        raise ConfigError(
            "Не найдены DXF-файлы: " + ", ".join(sorted(set(missing)))
        )

    return floors


def print_report(config: dict[str, Any], floors: list[dict[str, Any]]) -> None:
    building_name = config.get("building", {}).get("name", "Unnamed Building")

    print()
    print("=" * 76)
    print("CENTERLINES — BUILDING VALIDATION")
    print("=" * 76)
    print(f"Здание: {building_name}")
    print()
    print(f"{'Уровень':<10} {'DXF':<22} {'Тип':<12} {'Z, м':>10} {'H, м':>10} {'Плита, мм':>12}")
    print("-" * 76)

    for floor in floors:
        label = "Подвал" if floor["floor_number"] == 0 else str(floor["floor_number"])
        print(
            f"{label:<10} {floor['file']:<22} {floor['type']:<12} "
            f"{floor['z']:>10.3f} {floor['height']:>10.3f} {floor['slab_thickness_mm']:>12.0f}"
        )

    above_ground = sum(f["floor_number"] >= 1 for f in floors)
    basement_count = sum(f["floor_number"] == 0 for f in floors)

    print()
    print(f"Надземных этажей: {above_ground}")
    print(f"Подвалов:          {basement_count}")
    print(f"Всего уровней:     {len(floors)}")
    print()
    print("Проверка конфигурации: OK")
    print("Проверка файлов DXF:   OK")
    print("Расчёт отметок Z:      OK")


def run_floor_processor(
    floor: dict[str, Any],
    project_root: Path,
    work_dir: Path,
) -> tuple[list[dict], list[dict], list]:
    """
    Использует существующий centerlines.py и функции agent.py.
    Возвращает объекты уже с абсолютными Z.
    """
    import ezdxf
    import agent

    src_file = project_root / floor["file"]
    tag = f"floor_{floor['floor_number']:03d}"
    osi_file = work_dir / f"{tag}_CENTERLINES.dxf"

    # Существующее одноэтажное ядро: без изменений.
    subprocess.run(
        [sys.executable, str(project_root / "centerlines.py"),
         str(src_file), str(osi_file)],
        cwd=project_root,
        check=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )

    src = ezdxf.readfile(str(src_file))
    scale = agent.dxf_scale(src)

    walls = agent.read_walls_from_osi(scale, str(osi_file))
    columns = agent.read_columns(src, floor["height"] * 1000.0)
    slab_thickness_mm = float(floor["slab_thickness_mm"])
    plates = agent.read_plates(src, slab_thickness_mm)

    z0 = float(floor["z"])
    z1 = z0 + float(floor["height"])

    for w in walls:
        w["z1"] = z0
        w["z2"] = z1

    for c in columns:
        c["z1"] = z0
        c["z2"] = z1

    # Правило CENTERLINES:
    # отметка этажа = рабочая/опорная отметка конструкций.
    # Плита центрируется относительно этой отметки, а стены и колонны
    # начинаются от той же отметки. Это исключает подвисание вертикальных
    # конструкций на T/2 над плитой в Forum.
    #
    # Таким образом:
    #   стены/колонны: Z = z0
    #   плита:         Z = z0 (середина толщины)
    slab_thickness_m = slab_thickness_mm / 1000.0
    for p in plates:
        p.z = z0

    return walls, columns, plates



NODE_TOLERANCE_M = 0.001  # 1 mm


class NodeRegistry:
    """
    Global registry of geometric connection points.

    Important:
    SDNF 3.0 used by the current writer does not expose a standalone global
    node table. The registry therefore establishes canonical coordinates and
    element endpoint IDs inside CENTERLINES first; the SDNF writer will use
    these canonical coordinates in the next integration step.
    """

    def __init__(self, tolerance: float = NODE_TOLERANCE_M):
        self.tolerance = float(tolerance)
        self.nodes: list[dict[str, Any]] = []
        self._buckets: dict[tuple[int, int, int], list[int]] = {}

    def _key(self, x: float, y: float, z: float) -> tuple[int, int, int]:
        s = self.tolerance
        return (round(x / s), round(y / s), round(z / s))

    def get_or_create(self, x: float, y: float, z: float) -> int:
        key = self._key(x, y, z)

        # Search the bucket and neighboring buckets so points within tolerance
        # are merged even near a quantization boundary.
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    bucket = (key[0] + dx, key[1] + dy, key[2] + dz)
                    for node_id in self._buckets.get(bucket, []):
                        n = self.nodes[node_id - 1]
                        if (
                            abs(n["x"] - x) <= self.tolerance
                            and abs(n["y"] - y) <= self.tolerance
                            and abs(n["z"] - z) <= self.tolerance
                        ):
                            return node_id

        node_id = len(self.nodes) + 1
        self.nodes.append({
            "id": node_id,
            "x": float(x),
            "y": float(y),
            "z": float(z),
        })
        self._buckets.setdefault(key, []).append(node_id)
        return node_id

    def add_wall(self, wall: dict[str, Any]) -> None:
        wall["node1"] = self.get_or_create(wall["x1"], wall["y1"], wall["z1"])
        wall["node2"] = self.get_or_create(wall["x2"], wall["y2"], wall["z1"])
        wall["node3"] = self.get_or_create(wall["x2"], wall["y2"], wall["z2"])
        wall["node4"] = self.get_or_create(wall["x1"], wall["y1"], wall["z2"])

    def add_column(self, column: dict[str, Any]) -> None:
        column["node1"] = self.get_or_create(column["x"], column["y"], column["z1"])
        column["node2"] = self.get_or_create(column["x"], column["y"], column["z2"])

    def add_plate(self, plate: Any) -> None:
        top = plate._closed(plate.contour)
        ztop = plate.z + plate.thickness / 2.0
        zbot = plate.z - plate.thickness / 2.0
        plate.node_top = [
            self.get_or_create(x, y, ztop) for x, y in top
        ]
        plate.node_bottom = [
            self.get_or_create(x, y, zbot) for x, y in top
        ]

    def attach(self, walls: list[dict], columns: list[dict], plates: list[Any]) -> None:
        for w in walls:
            self.add_wall(w)
        for c in columns:
            self.add_column(c)
        for p in plates:
            self.add_plate(p)


def global_element_ids(
    walls: list[dict],
    columns: list[dict],
    plates: list[Any],
    start_id: int,
) -> int:
    """
    Assign one global element ID sequence across the complete building.
    """
    next_id = start_id

    for w in walls:
        w["id"] = next_id
        next_id += 1

    for c in columns:
        c["id"] = next_id
        next_id += 1

    for p in plates:
        p.id = next_id
        next_id += 1
        for hole in p.holes:
            hole.id = next_id
            next_id += 1

    return next_id


def canonicalize_geometry(
    walls: list[dict],
    columns: list[dict],
    plates: list[Any],
    registry: NodeRegistry,
) -> None:
    """
    Replace endpoint coordinates by the canonical coordinates stored in the
    global Node Registry.

    SDNF itself describes members/plates by coordinates, not by a standalone
    global node table. Therefore the correct way to transfer connectivity is
    to make coincident endpoints have exactly the same coordinates.
    """
    def coord(node_id: int) -> tuple[float, float, float]:
        n = registry.nodes[node_id - 1]
        return n["x"], n["y"], n["z"]

    for w in walls:
        x, y, z = coord(w["node1"])
        w["x1"], w["y1"], w["z1"] = x, y, z

        x, y, z = coord(w["node3"])
        w["x2"], w["y2"], w["z2"] = x, y, z

    for c in columns:
        x, y, z = coord(c["node1"])
        c["x"], c["y"], c["z1"] = x, y, z

        x, y, z = coord(c["node2"])
        c["z2"] = z

    for p in plates:
        top = p._closed(p.contour)
        if not hasattr(p, "node_top"):
            continue

        # Canonicalize contour XY from the top node registry. Plate writer
        # derives top/bottom Z from plate.z and thickness.
        canonical_xy = []
        for node_id in p.node_top[:-1] if len(p.node_top) > 1 and p.node_top[0] == p.node_top[-1] else p.node_top:
            x, y, _ = coord(node_id)
            canonical_xy.append((x, y))

        if canonical_xy:
            p.contour = p._closed(canonical_xy)


def build_building(config: dict[str, Any], floors: list[dict[str, Any]], project_root: Path):
    from unified_sdnf_writer import UnifiedSDNFWriter

    work_dir = project_root / "_building_work"
    work_dir.mkdir(exist_ok=True)

    all_walls: list[dict] = []
    all_columns: list[dict] = []
    all_plates: list = []
    floor_stats = []

    for index, floor in enumerate(floors):
        print(
            f"Обработка: этаж {'подвал' if floor['floor_number'] == 0 else floor['floor_number']} "
            f"| {floor['file']} | Z={floor['z']:.3f} м | H={floor['height']:.3f} м "
            f"| T={floor['slab_thickness_mm']:.0f} мм"
        )

        walls, columns, plates = run_floor_processor(
            floor, project_root, work_dir
        )

        # Keep floor provenance for diagnostics.
        for w in walls:
            w["_floor_number"] = floor["floor_number"]
        for c in columns:
            c["_floor_number"] = floor["floor_number"]
        for p in plates:
            p._floor_number = floor["floor_number"]

        all_walls.extend(walls)
        all_columns.extend(columns)
        all_plates.extend(plates)

        floor_stats.append({
            "floor": floor["floor_number"],
            "file": floor["file"],
            "z": floor["z"],
            "height": floor["height"],
            "walls": len(walls),
            "columns": len(columns),
            "plates": len(plates),
            "holes": sum(len(p.holes) for p in plates),
        })

    # Global element numbering.
    next_id = global_element_ids(
        all_walls, all_columns, all_plates, start_id=1
    )

    # Global geometric node registry.
    registry = NodeRegistry(tolerance=NODE_TOLERANCE_M)
    registry.attach(all_walls, all_columns, all_plates)

    # Save a diagnostic node map. This is deliberately separate from SDNF:
    # current SDNF writer has no standalone global node table.
    node_map = project_root / "_building_work" / "building_nodes_v03.json"
    node_map.write_text(
        json.dumps(
            {
                "tolerance_m": registry.tolerance,
                "nodes": registry.nodes,
                "node_count": len(registry.nodes),
                "element_count": next_id - 1,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    # IFC semantic export: Column / Wall / Slab.
    ifc_floors = []
    for floor in floors:
        fn = floor["floor_number"]
        ifc_floors.append({
            "floor_number": fn,
            "name": floor.get("name", f"Floor {fn}"),
            "z": floor["z"],
            "walls": [w for w in all_walls if w.get("_floor_number") == fn],
            "columns": [c for c in all_columns if c.get("_floor_number") == fn],
            "plates": [p for p in all_plates if getattr(p, "_floor_number", None) == fn],
        })
    from ifc_writer import IFCWriter
    ifc_output = project_root / "building.ifc"
    IFCWriter().write(ifc_output, ifc_floors)

    output = project_root / "building.sdnf"

    # SDNF transfers geometry by coordinates. Canonicalize all coincident
    # endpoints before writing so inter-floor connections are exact.
    canonicalize_geometry(all_walls, all_columns, all_plates, registry)

    UnifiedSDNFWriter(0.0).write(
        output,
        all_walls,
        all_columns,
        all_plates,
    )

    return output, floor_stats, registry, next_id - 1, ifc_output

def main() -> int:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("building.json")
    project_root = config_path.parent.resolve()

    try:
        config = load_config(config_path)
        floors = validate_and_build(config, project_root)
        print_report(config, floors)
        print()
        print("BUILDING VALIDATION: OK")
        print()
        print("Запуск обработки этажей...")

        output, stats, registry, element_count, ifc_output = build_building(config, floors, project_root)

        print()
        print("=" * 76)
        print("BUILDING BUILD: OK")
        print("=" * 76)

        total_walls = total_columns = total_plates = total_holes = 0
        for s in stats:
            print(
                f"Этаж {s['floor']:>2}: "
                f"стены={s['walls']}, колонны={s['columns']}, "
                f"плиты={s['plates']}, отверстия={s['holes']}"
            )
            total_walls += s["walls"]
            total_columns += s["columns"]
            total_plates += s["plates"]
            total_holes += s["holes"]

        print("-" * 76)
        print(f"Всего стен:       {total_walls}")
        print(f"Всего колонн:     {total_columns}")
        print(f"Всего плит:       {total_plates}")
        print(f"Всего отверстий:  {total_holes}")
        print(f"Глобальных узлов: {len(registry.nodes)}")
        print(f"Глобальных элементов: {element_count}")
        print(f"Карта узлов:      {project_root / '_building_work' / 'building_nodes_v03.json'}")
        print(f"Результат:        {output}")
        print("=" * 76)
        return 0

    except Exception as exc:
        print()
        print("BUILDING BUILD: ERROR")
        print(f"ERROR: {exc}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
