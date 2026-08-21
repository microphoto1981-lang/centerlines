#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""CENTERLINES — Building Setup GUI v1.1."""

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
        self.geometry("1200x760")
        self.minsize(1100, 700)
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
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Папка проекта:").grid(row=0, column=0, sticky="w")
        self.path_label = ttk.Label(top, text=str(self.project_dir), anchor="w")
        self.path_label.grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(top, text="Выбрать папку", command=self.choose_folder).grid(row=0, column=2, padx=(4, 18))
        ttk.Label(top, text="Название здания:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(top, textvariable=self.name_var, width=35).grid(row=1, column=1, sticky="w", padx=8, pady=(10, 0))
        ttk.Label(top, text="Отметка 1 этажа, м:").grid(row=1, column=2, sticky="e", pady=(10, 0))
        ttk.Entry(top, textvariable=self.first_level_var, width=12).grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(10, 0))

        info = ttk.LabelFrame(self, text="Этажные блоки", padding=10)
        info.pack(fill="both", expand=True, padx=12, pady=8)
        widths = [17, 12, 24, 10, 10, 15, 11, 11]
        headers = ["Название", "Тип", "DXF", "Количество", "Высота, м", "Толщина плиты, мм", "Дверь Z, м", "Дверь H, м"]
        for col, (title, width) in enumerate(zip(headers, widths)):
            info.columnconfigure(col, weight=1 if col == 2 else 0, minsize=width * 7)
            ttk.Label(info, text=title).grid(row=0, column=col, sticky="w", padx=4, pady=(2, 6))
        info.rowconfigure(1, weight=1)
        self.rows_frame = info

        buttons = ttk.Frame(self, padding=(12, 0, 12, 12))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Добавить блок", command=self.add_block).pack(side="left")
        ttk.Button(buttons, text="Удалить последний", command=self.remove_block).pack(side="left", padx=6)
        ttk.Button(buttons, text="Сохранить building.json", command=self.save).pack(side="right")
        ttk.Button(buttons, text="Сохранить и собрать", command=self.save_and_build).pack(side="right", padx=6)
        self.status = tk.StringVar(value="Готово")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x", side="bottom")

    def _scan_dxf(self): self.dxf_files=sorted(self.project_dir.glob("*.dxf"),key=lambda p:p.name.lower())
    def choose_folder(self):
        folder=filedialog.askdirectory(initialdir=self.project_dir)
        if not folder:return
        self.project_dir=Path(folder); self.path_label.config(text=str(self.project_dir)); self._scan_dxf(); self._clear_rows(); self._set_example()
    def _clear_rows(self):
        for row in self.blocks: row["frame"].destroy()
        self.blocks.clear()
    def _set_example(self):
        self.add_block("Подвал","basement",self._find_dxf("lvl 0.dxf"),1,"2.2","600","1.800","0.800")
        self.add_block("1 этаж","single",self._find_dxf("lvl 1.dxf"),1,"4.0","200","2.100","0.900")
        self.add_block("Типовые","repeat",self._find_dxf("lvl 2.dxf"),3,"3.2","180","2.100","0.900")
        self.add_block("Последний","last",self._find_dxf("lvl 5.dxf"),1,"3.4","180","2.400","0.900")
    def _find_dxf(self,preferred):
        for p in self.dxf_files:
            if p.name.lower()==preferred.lower(): return p.name
        return self.dxf_files[0].name if self.dxf_files else ""
    def add_block(self, name="", block_type="repeat", dxf="", count=1, height="3.2", slab_thickness="180", door_z_start="2.100", door_height="0.900"):
        row = {}
        r = len(self.blocks) + 1
        name_var = tk.StringVar(value=name); type_var = tk.StringVar(value=block_type); dxf_var = tk.StringVar(value=dxf)
        count_var = tk.StringVar(value=str(count)); height_var = tk.StringVar(value=str(height)); slab_var = tk.StringVar(value=str(slab_thickness))
        door_z_var = tk.StringVar(value=str(door_z_start)); door_h_var = tk.StringVar(value=str(door_height))
        widgets=[]
        widgets.append(ttk.Entry(self.rows_frame, textvariable=name_var, width=18))
        widgets.append(ttk.Combobox(self.rows_frame, textvariable=type_var, values=("basement", "single", "repeat", "last"), state="readonly", width=11))
        widgets.append(ttk.Combobox(self.rows_frame, textvariable=dxf_var, values=[p.name for p in self.dxf_files], width=27))
        widgets.append(ttk.Spinbox(self.rows_frame, from_=1, to=999, textvariable=count_var, width=9))
        widgets.append(ttk.Entry(self.rows_frame, textvariable=height_var, width=10))
        widgets.append(ttk.Entry(self.rows_frame, textvariable=slab_var, width=13))
        widgets.append(ttk.Entry(self.rows_frame, textvariable=door_z_var, width=10))
        widgets.append(ttk.Entry(self.rows_frame, textvariable=door_h_var, width=10))
        for col, widget in enumerate(widgets): widget.grid(row=r, column=col, sticky="ew" if col == 2 else "w", padx=4, pady=2)
        row.update({"widgets": widgets, "name": name_var, "type": type_var, "file": dxf_var, "count": count_var, "height": height_var, "slab_thickness": slab_var, "door_z_start": door_z_var, "door_height": door_h_var})
        self.blocks.append(row)
    def remove_block(self):
        if self.blocks:
            row=self.blocks.pop()
            for widget in row.get("widgets",[]): widget.destroy()
    def _num(self,text,label):
        try:return float(str(text).replace(",","."))
        except ValueError:raise ValueError(f"{label}: введите число.")
    def collect(self):
        first_level=self._num(self.first_level_var.get(),"Отметка 1 этажа")
        blocks=[]
        for i,row in enumerate(self.blocks,1):
            name=row["name"].get().strip(); typ=row["type"].get().strip(); file=row["file"].get().strip()
            try: count=int(row["count"].get())
            except ValueError: raise ValueError(f"Блок №{i}: количество должно быть целым числом.")
            height=self._num(row["height"].get(),f"Блок №{i}: высота"); slab_thickness=self._num(row["slab_thickness"].get(),f"Блок №{i}: толщина плиты")
            door_z_start=self._num(row["door_z_start"].get(),f"Блок №{i}: дверь Z начала"); door_height=self._num(row["door_height"].get(),f"Блок №{i}: высота двери")
            if not name: raise ValueError(f"Блок №{i}: не задано название.")
            if not file: raise ValueError(f"Блок №{i}: не выбран DXF.")
            if count<1: raise ValueError(f"Блок №{i}: количество должно быть >= 1.")
            if height<0: raise ValueError(f"Блок №{i}: высота не может быть отрицательной.")
            if slab_thickness<=0: raise ValueError(f"Блок №{i}: толщина плиты должна быть больше 0 мм.")
            if door_z_start<0: raise ValueError(f"Блок №{i}: дверь Z начала не может быть отрицательной.")
            if door_height<=0: raise ValueError(f"Блок №{i}: высота двери должна быть больше 0.")
            blocks.append({"name":name,"type":typ,"file":file,"count":count,"height":height,"slab_thickness_mm":slab_thickness,"door_settings":{"z_start_m":door_z_start,"height_m":door_height}})
        return {"building":{"name":self.name_var.get().strip() or "Building","first_floor_level":first_level},"blocks":blocks}
    def save(self):
        try:data=self.collect()
        except ValueError as exc: messagebox.showerror("Ошибка ввода",str(exc)); return False
        path=self.project_dir/"building.json"; path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); self.status.set(f"Сохранено: {path.name}"); return True
    def save_and_build(self):
        if not self.save(): return
        builder=self.project_dir/"building_builder.py"
        if not builder.exists(): messagebox.showerror("CENTERLINES","В выбранной папке не найден building_builder.py."); return
        self.status.set("Идёт сборка здания..."); self.update_idletasks()
        try:
            result=subprocess.run([sys.executable,str(builder),str(self.project_dir/"building.json")],cwd=self.project_dir,capture_output=True,text=True,encoding="utf-8",errors="replace",env={**os.environ,"PYTHONIOENCODING":"utf-8"})
        except Exception as exc: messagebox.showerror("Ошибка запуска",str(exc)); self.status.set("Ошибка запуска"); return
        if result.returncode==0:
            self.status.set("BUILDING BUILD: OK"); messagebox.showinfo("CENTERLINES","Здание успешно собрано.\n\nSDNF:\n"+str(self.project_dir/"building.sdnf")+"\n\nIFC:\n"+str(self.project_dir/"building.ifc"))
        else:
            self.status.set("BUILDING BUILD: ERROR"); messagebox.showerror("Ошибка сборки",(result.stdout or "")+"\n"+(result.stderr or ""))

if __name__ == "__main__": BuildingSetup().mainloop()
