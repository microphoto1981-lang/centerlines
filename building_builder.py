#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CENTERLINES — multi-floor building builder.

Door openings are represented by three independent IFCWALLSTANDARDCASE
objects: left wall, right wall and top lintel. No IFC opening/boolean is used.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ALLOWED_TYPES = {"basement", "single", "repeat", "last"}
NODE_TOLERANCE_M = 0.001
DOOR_TOLERANCE_M = 0.005

class ConfigError(Exception):
    pass

def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Файл конфигурации не найден: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Ошибка JSON в {path.name}: строка {exc.lineno}, столбец {exc.colno}: {exc.msg}") from exc
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
    first_floor_level = require_number(building.get("first_floor_level", 0.0), "building.first_floor_level")
    for i, block in enumerate(blocks, 1):
        if not isinstance(block, dict):
            raise ConfigError(f"Блок №{i} должен быть объектом.")
        for field in ("name", "type", "file", "count", "height", "slab_thickness_mm"):
            if field not in block:
                raise ConfigError(f"Блок №{i}: отсутствует поле '{field}'.")
        if block["type"] not in ALLOWED_TYPES:
            raise ConfigError(f"Блок №{i}: неизвестный type '{block['type']}'.")
        if not isinstance(block["name"], str) or not block["name"].strip():
            raise ConfigError(f"Блок №{i}: 'name' должен быть непустой строкой.")
        if not isinstance(block["file"], str) or not block["file"].strip():
            raise ConfigError(f"Блок №{i}: 'file' должен быть непустой строкой.")
        count = block["count"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ConfigError(f"Блок №{i}: 'count' должен быть целым числом >= 1.")
        height = require_number(block["height"], f"blocks[{i}].height", False)
        slab = require_number(block["slab_thickness_mm"], f"blocks[{i}].slab_thickness_mm", False)
        if slab <= 0:
            raise ConfigError(f"Блок №{i}: толщина плиты должна быть больше 0 мм.")
        if block["type"] == "basement" and i != 1:
            raise ConfigError("Блок типа 'basement' должен быть первым.")
        if block["type"] == "last" and i != len(blocks):
            raise ConfigError("Блок типа 'last' должен быть последним.")
        if block["type"] == "repeat" and count < 2:
            raise ConfigError("Блок type='repeat' должен иметь count >= 2.")
    floors = []
    basement = next((b for b in blocks if b["type"] == "basement"), None)
    if basement:
        floors.append({"floor_number": 0, "name": basement["name"], "type": basement["type"], "file": basement["file"], "z": first_floor_level-float(basement["height"]), "height": float(basement["height"]), "slab_thickness_mm": float(basement["slab_thickness_mm"]), "door_settings": dict(basement.get("door_settings", {}) or {})})
    current_z = first_floor_level
    floor_number = 1
    for block in blocks:
        if block["type"] == "basement":
            continue
        for repeat_index in range(int(block["count"])):
            floors.append({"floor_number": floor_number, "name": block["name"], "type": block["type"], "file": block["file"], "z": current_z, "height": float(block["height"]), "slab_thickness_mm": float(block["slab_thickness_mm"]), "door_settings": dict(block.get("door_settings", {}) or {}), "repeat_index": repeat_index+1})
            floor_number += 1
            current_z += float(block["height"])
    missing = [f["file"] for f in floors if not (project_root / f["file"]).exists()]
    if missing:
        raise ConfigError("Не найдены DXF-файлы: " + ", ".join(sorted(set(missing))))
    return floors

def print_report(config, floors):
    print("\n" + "="*76)
    print("CENTERLINES — BUILDING VALIDATION")
    print("="*76)
    print(f"Здание: {config.get('building', {}).get('name', 'Unnamed Building')}\n")
    for f in floors:
        label = "Подвал" if f["floor_number"] == 0 else str(f["floor_number"])
        print(f"Этаж {label:<3} {f['file']:<22} Z={f['z']:.3f} м H={f['height']:.3f} м T={f['slab_thickness_mm']:.0f} мм")
    print(f"\nВсего уровней: {len(floors)}")
    print("Проверка конфигурации: OK")
    print("Проверка файлов DXF:   OK")
    print("Расчёт отметок Z:      OK")

def _parallel_collinear_interval(wall, door, tol=DOOR_TOLERANCE_M):
    wx1,wy1,wx2,wy2 = map(float,(wall["x1"],wall["y1"],wall["x2"],wall["y2"]))
    dx1,dy1,dx2,dy2 = map(float,(door["x1"],door["y1"],door["x2"],door["y2"]))
    wdx,wdy = wx2-wx1,wy2-wy1; ddx,ddy = dx2-dx1,dy2-dy1
    wl=math.hypot(wdx,wdy); dl=math.hypot(ddx,ddy)
    if wl<=tol or dl<=tol: return None
    if abs(wdx*ddy-wdy*ddx)>tol*wl*dl: return None
    distance=abs(wdx*(dy1-wy1)-wdy*(dx1-wx1))/wl
    if distance>tol: return None
    ux,uy=wdx/wl,wdy/wl
    a=(dx1-wx1)*ux+(dy1-wy1)*uy; b=(dx2-wx1)*ux+(dy2-wy1)*uy
    lo,hi=sorted((a,b)); lo=max(0.0,lo); hi=min(wl,hi)
    return (lo,hi) if hi-lo>tol else None

def _wall_piece(wall, x1,y1,x2,y2,z1,z2, door_piece=False, piece_type=None):
    p=dict(wall); p.update(x1=x1,y1=y1,x2=x2,y2=y2,z1=z1,z2=z2)
    p["_door_piece"] = door_piece
    if piece_type: p["_door_piece_type"] = piece_type
    return p

def split_wall_by_doors(wall, doors, tol=DOOR_TOLERANCE_M):
    """Create exactly left + right + top wall pieces for each door."""
    x1,y1,x2,y2 = map(float,(wall["x1"],wall["y1"],wall["x2"],wall["y2"]))
    length=math.hypot(x2-x1,y2-y1)
    if length<=tol: return [wall]
    ux,uy=(x2-x1)/length,(y2-y1)/length
    relevant=[]
    for door in doors:
        iv=_parallel_collinear_interval(wall,door,tol)
        if iv is not None:
            relevant.append((iv[0],iv[1],door))
    if not relevant: return [wall]
    relevant.sort(key=lambda q:q[0])
    for i in range(1,len(relevant)):
        if relevant[i][0] < relevant[i-1][1]-tol:
            raise ConfigError("Дверные проёмы одной стены пересекаются.")
    z_bottom=float(wall["z1"]); z_top=float(wall["z2"])
    pieces=[]; cursor=0.0
    for a,b,d in relevant:
        if a-cursor>tol:
            pieces.append(_wall_piece(wall,x1+ux*cursor,y1+uy*cursor,x1+ux*a,y1+uy*a,z_bottom,z_top))
        dz1=float(d["z1"]); dz2=float(d["z2"])
        if dz1 < z_bottom-tol or dz2 > z_top+tol or dz2 <= dz1+tol:
            raise ConfigError("Дверной проём выходит за пределы высоты стены.")
        pieces.append(_wall_piece(wall,x1+ux*a,y1+uy*a,x1+ux*b,y1+uy*b,dz2,z_top,True,"top"))
        cursor=b
    if length-cursor>tol:
        pieces.append(_wall_piece(wall,x1+ux*cursor,y1+uy*cursor,x2,y2,z_bottom,z_top))
    return pieces

def run_floor_processor(floor, project_root, work_dir):
    import ezdxf
    import agent
    src_file=project_root/floor["file"]
    tag=f"floor_{floor['floor_number']:03d}"
    osi_file=work_dir/f"{tag}_CENTERLINES.dxf"
    door_osi_file=work_dir/f"{tag}_DOOR_CENTERLINES.dxf"
    env={**os.environ,"PYTHONIOENCODING":"utf-8"}
    subprocess.run([sys.executable,str(project_root/"centerlines.py"),str(src_file),str(osi_file),"walls"],cwd=project_root,check=True,env=env)
    subprocess.run([sys.executable,str(project_root/"centerlines.py"),str(src_file),str(door_osi_file),"door"],cwd=project_root,check=True,env=env)
    src=ezdxf.readfile(str(src_file)); scale=agent.dxf_scale(src)
    walls=agent.read_walls_from_osi(scale,str(osi_file))
    doors=agent.read_walls_from_osi(scale,str(door_osi_file))
    columns=agent.read_columns(src,floor["height"]*1000.0)
    plates=agent.read_plates(src,float(floor["slab_thickness_mm"]))
    z0=float(floor["z"]); z1=z0+float(floor["height"])
    for w in walls: w["z1"],w["z2"]=z0,z1
    for c in columns: c["z1"],c["z2"]=z0,z1
    for p in plates: p.z=z0
    cfg=floor.get("door_settings",{}) or {}
    dz=float(cfg.get("z_start_m",2.100)); dh=float(cfg.get("height_m",0.900))
    if dz<0 or dh<=0: raise ConfigError("Параметры двери: Z начала >= 0, высота > 0.")
    for d in doors:
        d["z1"]=z0+dz; d["z2"]=z0+dz+dh; d["_floor_number"]=floor["floor_number"]
    original=len(walls)
    all_wall_elements = walls + doors
    return all_wall_elements,columns,plates,doors,original

class NodeRegistry:
    def __init__(self,tolerance=NODE_TOLERANCE_M): self.tolerance=float(tolerance); self.nodes=[]; self._buckets={}
    def _key(self,x,y,z): s=self.tolerance; return round(x/s),round(y/s),round(z/s)
    def get_or_create(self,x,y,z):
        key=self._key(x,y,z)
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for dz in (-1,0,1):
                    for nid in self._buckets.get((key[0]+dx,key[1]+dy,key[2]+dz),[]):
                        n=self.nodes[nid-1]
                        if abs(n["x"]-x)<=self.tolerance and abs(n["y"]-y)<=self.tolerance and abs(n["z"]-z)<=self.tolerance: return nid
        nid=len(self.nodes)+1; self.nodes.append({"id":nid,"x":float(x),"y":float(y),"z":float(z)}); self._buckets.setdefault(key,[]).append(nid); return nid
    def add_wall(self,w):
        w["node1"]=self.get_or_create(w["x1"],w["y1"],w["z1"]); w["node2"]=self.get_or_create(w["x2"],w["y2"],w["z1"]); w["node3"]=self.get_or_create(w["x2"],w["y2"],w["z2"]); w["node4"]=self.get_or_create(w["x1"],w["y1"],w["z2"])
    def add_column(self,c): c["node1"]=self.get_or_create(c["x"],c["y"],c["z1"]); c["node2"]=self.get_or_create(c["x"],c["y"],c["z2"])
    def add_plate(self,p):
        top=p._closed(p.contour); p.node_top=[self.get_or_create(x,y,p.z+p.thickness/2) for x,y in top]; p.node_bottom=[self.get_or_create(x,y,p.z-p.thickness/2) for x,y in top]
    def attach(self,walls,columns,plates):
        for w in walls:self.add_wall(w)
        for c in columns:self.add_column(c)
        for p in plates:self.add_plate(p)

def global_element_ids(walls,columns,plates,start_id=1):
    n=start_id
    for group in (walls,columns):
        for e in group:e["id"]=n;n+=1
    for p in plates:
        p.id=n;n+=1
        for h in p.holes:h.id=n;n+=1
    return n

def canonicalize_geometry(walls,columns,plates,registry):
    def coord(nid): n=registry.nodes[nid-1]; return n["x"],n["y"],n["z"]
    for w in walls:
        x,y,z=coord(w["node1"]);w["x1"],w["y1"],w["z1"]=x,y,z
        x,y,z=coord(w["node3"]);w["x2"],w["y2"],w["z2"]=x,y,z
    for c in columns:
        x,y,z=coord(c["node1"]);c["x"],c["y"],c["z1"]=x,y,z;_,_,z=coord(c["node2"]);c["z2"]=z
    for p in plates:
        if not hasattr(p,"node_top"):continue
        ids=p.node_top[:-1] if len(p.node_top)>1 and p.node_top[0]==p.node_top[-1] else p.node_top
        pts=[]
        for nid in ids:x,y,_=coord(nid);pts.append((x,y))
        if pts:p.contour=p._closed(pts)

def build_building(config,floors,project_root):
    from unified_sdnf_writer import UnifiedSDNFWriter
    work_dir=project_root/"_building_work";work_dir.mkdir(exist_ok=True)
    all_walls=[];all_columns=[];all_plates=[];floor_stats=[]
    for floor in floors:
        block_cfg = floor.get("door_settings", {}) or {}
        if not isinstance(block_cfg, dict):
            raise ConfigError(f"Этаж {floor['floor_number']}: параметры двери должны быть объектом.")
        dz=float(block_cfg.get("z_start_m",2.100));dh=float(block_cfg.get("height_m",0.900))
        if dz<0 or dh<=0: raise ConfigError(f"Этаж {floor['floor_number']}: параметры двери — Z начала >= 0, высота > 0.")
        print(f"Обработка: этаж {'подвал' if floor['floor_number']==0 else floor['floor_number']} | {floor['file']} | Z={floor['z']:.3f} м | H={floor['height']:.3f} м | T={floor['slab_thickness_mm']:.0f} мм | дверь Z={dz:.3f} м H={dh:.3f} м")
        floor["door_settings"]={"z_start_m":dz,"height_m":dh}
        walls,cols,plates,doors,original=run_floor_processor(floor,project_root,work_dir)
        for w in walls:w["_floor_number"]=floor["floor_number"]
        for c in cols:c["_floor_number"]=floor["floor_number"]
        for p in plates:p._floor_number=floor["floor_number"]
        all_walls.extend(walls);all_columns.extend(cols);all_plates.extend(plates)
        floor_stats.append({"floor":floor["floor_number"],"file":floor["file"],"z":floor["z"],"height":floor["height"],"walls":len(walls),"original_walls":original,"doors":len(doors),"columns":len(cols),"plates":len(plates),"holes":sum(len(p.holes) for p in plates)})
    next_id=global_element_ids(all_walls,all_columns,all_plates,1);registry=NodeRegistry();registry.attach(all_walls,all_columns,all_plates)
    node_map=work_dir/"building_nodes_v05.json";node_map.write_text(json.dumps({"tolerance_m":registry.tolerance,"nodes":registry.nodes,"node_count":len(registry.nodes),"element_count":next_id-1},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    ifc_floors=[]
    for floor in floors:
        fn=floor["floor_number"]
        ifc_floors.append({"floor_number":fn,"name":floor.get("name",f"Floor {fn}"),"z":floor["z"],"walls":[w for w in all_walls if w.get("_floor_number")==fn],"columns":[c for c in all_columns if c.get("_floor_number")==fn],"plates":[p for p in all_plates if getattr(p,"_floor_number",None)==fn]})
    from ifc_writer import IFCWriter
    ifc_output=project_root/"building.ifc";IFCWriter().write(ifc_output,ifc_floors)
    output=project_root/"building.sdnf";canonicalize_geometry(all_walls,all_columns,all_plates,registry);UnifiedSDNFWriter(0.0).write(output,all_walls,all_columns,all_plates)
    return output,floor_stats,registry,next_id-1,ifc_output

def main():
    config_path=Path(sys.argv[1]) if len(sys.argv)>1 else Path("building.json");project_root=config_path.parent.resolve()
    try:
        config=load_config(config_path);floors=validate_and_build(config,project_root);print_report(config,floors);print("\nBUILDING VALIDATION: OK\n\nЗапуск обработки этажей...")
        output,stats,registry,element_count,ifc_output=build_building(config,floors,project_root)
        print("\n"+"="*76+"\nBUILDING BUILD: OK\n"+"="*76);totals={k:0 for k in ("walls","doors","columns","plates","holes")}
        for s in stats:
            print(f"Этаж {s['floor']:>2}: исходных стен={s['original_walls']}, стен после дверей={s['walls']}, двери={s['doors']}, колонны={s['columns']}, плиты={s['plates']}, отверстия={s['holes']}")
            for k in totals:totals[k]+=s[k]
        print("-"*76);print(f"Всего стеновых элементов: {totals['walls']}");print(f"Всего дверей обработано:  {totals['doors']}");print(f"Всего колонн:             {totals['columns']}");print(f"Всего плит:               {totals['plates']}");print(f"Всего отверстий плит:    {totals['holes']}");print(f"Глобальных узлов:         {len(registry.nodes)}");print(f"Глобальных элементов:     {element_count}");print(f"Результат SDNF:           {output}");print(f"Результат IFC:            {ifc_output}");return 0
    except Exception as exc:
        print("\nBUILDING BUILD: ERROR");print(f"ERROR: {exc}");raise

if __name__ == "__main__":raise SystemExit(main())
