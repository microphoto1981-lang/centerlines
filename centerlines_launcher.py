# -*- coding: utf-8 -*-
"""CENTERLINES single-file EXE launcher.

Keeps the existing source-mode GUI intact while making the multi-floor
builder work from a PyInstaller one-file executable. DXF files remain
external and are selected from the GUI.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def _bundled_path(name: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / name
    return Path(__file__).resolve().parent / name


def packaged_run_floor_processor(floor, project_root: Path, work_dir: Path):
    import ezdxf
    import agent

    src_file = project_root / floor["file"]
    tag = f"floor_{floor['floor_number']:03d}"
    osi_file = work_dir / f"{tag}_CENTERLINES.dxf"

    # In the EXE there is no external Python interpreter. Execute the
    # bundled centerlines.py with runpy instead of starting python.exe.
    script = _bundled_path("centerlines.py")
    old_argv = sys.argv[:]
    try:
        sys.argv = [str(script), str(src_file), str(osi_file)]
        runpy.run_path(str(script), run_name="__main__")
    finally:
        sys.argv = old_argv

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

    for p in plates:
        p.z = z0

    return walls, columns, plates


def main() -> int:
    import building_builder
    import building_setup
    import tkinter.messagebox as messagebox

    # Replace only the two source-mode subprocess boundaries. The geometry
    # algorithms and the existing GUI remain unchanged.
    building_builder.run_floor_processor = packaged_run_floor_processor

    def save_and_build(self):
        if not self.save():
            return

        self.status.set("Идёт сборка здания...")
        self.update_idletasks()

        old_argv = sys.argv[:]
        try:
            sys.argv = [str(_bundled_path("building_builder.py")),
                        str(self.project_dir / "building.json")]
            rc = building_builder.main()
            if rc == 0:
                self.status.set("BUILDING BUILD: OK")
                messagebox.showinfo(
                    "CENTERLINES",
                    "Здание успешно собрано.\n\n"
                    f"Результат:\n{self.project_dir / 'building.sdnf'}\n"
                    f"IFC:\n{self.project_dir / 'building.ifc'}"
                )
            else:
                self.status.set("BUILDING BUILD: ERROR")
        except Exception as exc:
            self.status.set("BUILDING BUILD: ERROR")
            messagebox.showerror("Ошибка сборки", str(exc))
        finally:
            sys.argv = old_argv

    building_setup.BuildingSetup.save_and_build = save_and_build
    app = building_setup.BuildingSetup()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
