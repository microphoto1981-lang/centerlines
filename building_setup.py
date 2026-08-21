#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CENTERLINES — Building Setup GUI v1.0

Графический ввод структуры здания.
Создаёт building.json для building_builder.py.

Требование:
- XY этажей берутся как есть из исходных DXF;
- GUI задаёт только вертикальную структуру и высоты.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


class BuildingSetup(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CENTERLINES — Настройка многоэтажного здания")
        self.geometry("1120x650")
        self.minsize(1020, 580)

        self.project_dir = Path.cwd()
        self.blocks = []

        self.name_var = tk.StringVar(value="Test Building")
        self.first_level_var = tk.StringVar(value="0.000")

        self._build_ui()
        self._scan_dxf()
        self._set_example()

    def _build_ui(self):
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")

        ttk.Label(top, text="Папка проекта:").grid(row=0, column=0, sticky="w")
        self.path_label = ttk.Label(top, text=str(self.project_dir))
        self.path_label.grid(row=0, column=1, sticky="w", padx=8)

        ttk.Button(top, text="Выбрать папку", command=self.choose_folder).grid(
            row=0, column=2, padx=5
        )

        ttk.Label(top, text="Название здания:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(top, textvariable=self.name_var, width=35).grid(
            row=1, column=1, sticky="w", padx=8, pady=(10, 0)
        )

        ttk.Label(top, text="Отметка 1 этажа, м:").grid(row=1, column=2, sticky="e", pady=(10, 0))
        ttk.Entry(top, textvariable=self.first_level_var, width=12).grid(
            row=1, column=3, sticky="w", padx=8, pady=(10, 0)
        )

        info = ttk.LabelFrame(self, text="Этажные блоки", padding=10)
        info.pack(fill="both", expand=True, padx=12, pady=8)

        columns = [
            ("Название", 18),
            ("Тип", 13),
            ("DXF", 28),
            ("Количество", 11),
            ("Высота, м", 11),
            ("Толщина плиты, мм", 16),
        ]
        for col, (title, width) in enumerate(columns):
            ttk.Label(info, text=title).grid(row=0, column=col, sticky="w", padx=4, pady=4)

        self.rows_frame = ttk.Frame(info)
        self.rows_frame.grid(row=1, column=0, columnspan=6, sticky="nsew")

        info.columnconfigure(2, weight=1)
        info.rowconfigure(1, weight=1)

        buttons = ttk.Frame(self, padding=(12, 0, 12, 12))
        buttons.pack(fill="x")

        ttk.Button(buttons, text="Добавить блок", command=self.add_block).pack(side="left")
        ttk.Button(buttons, text="Удалить последний", command=self.remove_block).pack(
            side="left", padx=6
        )
        ttk.Button(buttons, text="Сохранить building.json", command=self.save).pack(
            side="right"
        )
        ttk.Button(buttons, text="Сохранить и собрать", command=self.save_and_build).pack(
            side="right", padx=6
        )

        self.status = tk.StringVar(value="Готово")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(
            fill="x", side="bottom"
        )

    def _scan_dxf(self):
        self.dxf_files = sorted(self.project_dir.glob("*.dxf"), key=lambda p: p.name.lower())

    def choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.project_dir)
        if not folder:
            return
        self.project_dir = Path(folder)
        self.path_label.config(text=str(self.project_dir))
        self._scan_dxf()
        self._clear_rows()
        self._set_example()

    def _clear_rows(self):
        for row in self.blocks:
            row["frame"].destroy()
        self.blocks.clear()

    def _set_example(self):
        # Example matching the tested building:
        # basement 2.2; first 4.0; typical 3 floors at 3.2; last 3.4
        self.add_block("Подвал", "basement", self._find_dxf("lvl 0.dxf"), 1, "2.2", "600")
        self.add_block("1 этаж", "single", self._find_dxf("lvl 1.dxf"), 1, "4.0", "200")
        self.add_block("Типовые", "repeat", self._find_dxf("lvl 2.dxf"), 3, "3.2", "180")
        self.add_block("Последний", "last", self._find_dxf("lvl 5.dxf"), 1, "3.4", "180")

    def _find_dxf(self, preferred):
        for p in self.dxf_files:
            if p.name.lower() == preferred.lower():
                return p.name
        return self.dxf_files[0].name if self.dxf_files else ""

    def add_block(self, name="", block_type="repeat", dxf="", count=1, height="3.2", slab_thickness="180"):
        row = {}
        frame = ttk.Frame(self.rows_frame)
        frame.grid(row=len(self.blocks), column=0, sticky="ew", pady=2)
        frame.columnconfigure(2, weight=1)

        name_var = tk.StringVar(value=name)
        type_var = tk.StringVar(value=block_type)
        dxf_var = tk.StringVar(value=dxf)
        count_var = tk.StringVar(value=str(count))
        height_var = tk.StringVar(value=str(height))
        slab_var = tk.StringVar(value=str(slab_thickness))

        ttk.Entry(frame, textvariable=name_var, width=18).grid(row=0, column=0, padx=4)
        ttk.Combobox(
            frame, textvariable=type_var,
            values=("basement", "single", "repeat", "last"),
            state="readonly", width=11
        ).grid(row=0, column=1, padx=4)

        dxf_combo = ttk.Combobox(
            frame, textvariable=dxf_var,
            values=[p.name for p in self.dxf_files],
            width=27
        )
        dxf_combo.grid(row=0, column=2, sticky="ew", padx=4)

        ttk.Spinbox(frame, from_=1, to=999, textvariable=count_var, width=9).grid(
            row=0, column=3, padx=4
        )
        ttk.Entry(frame, textvariable=height_var, width=10).grid(row=0, column=4, padx=4)
        ttk.Entry(frame, textvariable=slab_var, width=14).grid(row=0, column=5, padx=4)

        row.update({
            "frame": frame,
            "name": name_var,
            "type": type_var,
            "file": dxf_var,
            "count": count_var,
            "height": height_var,
            "slab_thickness": slab_var,
        })
        self.blocks.append(row)

    def remove_block(self):
        if not self.blocks:
            return
        self.blocks[-1]["frame"].destroy()
        self.blocks.pop()

    def _num(self, text, label):
        try:
            return float(str(text).replace(",", "."))
        except ValueError:
            raise ValueError(f"{label}: введите число.")

    def collect(self):
        first_level = self._num(self.first_level_var.get(), "Отметка 1 этажа")
        blocks = []

        for i, row in enumerate(self.blocks, 1):
            name = row["name"].get().strip()
            typ = row["type"].get().strip()
            file = row["file"].get().strip()

            try:
                count = int(row["count"].get())
            except ValueError:
                raise ValueError(f"Блок №{i}: количество должно быть целым числом.")

            height = self._num(row["height"].get(), f"Блок №{i}: высота")
            slab_thickness = self._num(
                row["slab_thickness"].get(),
                f"Блок №{i}: толщина плиты",
            )

            if not name:
                raise ValueError(f"Блок №{i}: не задано название.")
            if not file:
                raise ValueError(f"Блок №{i}: не выбран DXF.")
            if count < 1:
                raise ValueError(f"Блок №{i}: количество должно быть >= 1.")
            if height < 0:
                raise ValueError(f"Блок №{i}: высота не может быть отрицательной.")
            if slab_thickness <= 0:
                raise ValueError(f"Блок №{i}: толщина плиты должна быть больше 0 мм.")

            blocks.append({
                "name": name,
                "type": typ,
                "file": file,
                "count": count,
                "height": height,
                "slab_thickness_mm": slab_thickness,
            })

        return {
            "building": {
                "name": self.name_var.get().strip() or "Building",
                "first_floor_level": first_level,
            },
            "blocks": blocks,
        }

    def save(self):
        try:
            data = self.collect()
        except ValueError as exc:
            messagebox.showerror("Ошибка ввода", str(exc))
            return False

        path = self.project_dir / "building.json"
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8"
        )
        self.status.set(f"Сохранено: {path.name}")
        messagebox.showinfo("CENTERLINES", f"building.json сохранён:\n{path}")
        return True

    def save_and_build(self):
        if not self.save():
            return

        builder = self.project_dir / "building_builder.py"
        if not builder.exists():
            messagebox.showerror(
                "CENTERLINES",
                "В выбранной папке не найден building_builder.py."
            )
            return

        self.status.set("Идёт сборка здания...")
        self.update_idletasks()

        try:
            result = subprocess.run(
                [sys.executable, str(builder), str(self.project_dir / "building.json")],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        except Exception as exc:
            messagebox.showerror("Ошибка запуска", str(exc))
            self.status.set("Ошибка запуска")
            return

        if result.returncode == 0:
            self.status.set("BUILDING BUILD: OK")
            messagebox.showinfo(
                "CENTERLINES",
                "Здание успешно собрано.\n\n"
                f"Результат:\n{self.project_dir / 'building.sdnf'}"
            )
        else:
            self.status.set("BUILDING BUILD: ERROR")
            messagebox.showerror(
                "Ошибка сборки",
                (result.stdout or "") + "\n" + (result.stderr or "")
            )


if __name__ == "__main__":
    app = BuildingSetup()
    app.mainloop()
