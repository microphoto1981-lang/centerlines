import os
import sys
import re
import math
import subprocess
import tkinter as tk
from tkinter import messagebox, filedialog, scrolledtext
import ezdxf

from plate import Plate, Opening
from unified_sdnf_writer import UnifiedSDNFWriter

FLOOR_HEIGHT_DEFAULT = 3300.0
SLAB_THICKNESS_DEFAULT = 200.0

UNIT_SCALE = {0:1.0,1:0.0254,2:0.3048,3:1609.344,4:0.001,5:0.01,6:1.0,7:1000.0}

def close_contour(points):
    pts = list(points)
    if pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts

def signed_area(points):
    pts = points[:-1] if points and points[0] == points[-1] else points
    return 0.5 * sum(
        pts[i][0] * pts[(i+1)%len(pts)][1] -
        pts[(i+1)%len(pts)][0] * pts[i][1]
        for i in range(len(pts))
    )

def point_in_polygon(point, polygon):
    x, y = point
    pts = polygon[:-1] if polygon and polygon[0] == polygon[-1] else polygon
    inside = False
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i+1) % len(pts)]
        if (y1 > y) != (y2 > y):
            xinters = (x2-x1) * (y-y1) / (y2-y1) + x1
            if x < xinters:
                inside = not inside
    return inside

def dxf_scale(doc):
    return UNIT_SCALE.get(int(doc.header.get("$INSUNITS", 0) or 0), 1.0)

def read_walls_from_osi(scale, osi_file):
    doc = ezdxf.readfile(osi_file)
    walls = []
    rx = re.compile(r'^walls_(\d+(?:\.\d+)?)$')
    for e in doc.modelspace().query("LINE"):
        m = rx.match(e.dxf.layer)
        if not m:
            continue
        thickness_mm = float(m.group(1))
        walls.append({
            "id": len(walls)+1,
            "x1": e.dxf.start.x * scale,
            "y1": e.dxf.start.y * scale,
            "x2": e.dxf.end.x * scale,
            "y2": e.dxf.end.y * scale,
            "thickness": thickness_mm * 0.001,
        })
    return walls

def read_columns(doc, floor_height_mm):
    # The current test DXF contains no columns layer.
    # When a 'columns' layer exists, convert each closed line-group to a column center.
    lines = list(doc.modelspace().query('LINE[layer=="columns"]'))
    if not lines:
        return []

    result, used = [], set()
    scale = dxf_scale(doc)

    for i, line in enumerate(lines):
        if i in used:
            continue
        pts = [(line.dxf.start.x, line.dxf.start.y),
               (line.dxf.end.x, line.dxf.end.y)]
        used.add(i)
        end = pts[-1]

        for _ in range(len(lines)):
            found = False
            for j, l in enumerate(lines):
                if j in used:
                    continue
                a = (l.dxf.start.x, l.dxf.start.y)
                b = (l.dxf.end.x, l.dxf.end.y)
                if abs(a[0]-end[0]) < .01 and abs(a[1]-end[1]) < .01:
                    pts.append(b); end = b; used.add(j); found = True; break
                if abs(b[0]-end[0]) < .01 and abs(b[1]-end[1]) < .01:
                    pts.append(a); end = a; used.add(j); found = True; break
            if not found:
                break
            if abs(end[0]-pts[0][0]) < .01 and abs(end[1]-pts[0][1]) < .01:
                break

        if len(pts) >= 3:
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            result.append({
                "id": len(result)+1,
                "x": cx * scale,
                "y": cy * scale,
                "z1": 0.0,
                "z2": floor_height_mm * 0.001,
            })
    return result

def _closed_polyline_points(e, scale):
    """Read a straight-segment closed LWPOLYLINE into a contour."""
    pts = []
    for p in e:
        bulge = float(p[4]) if len(p) > 4 else 0.0
        if abs(bulge) > 1e-12:
            raise ValueError(
                "На слое slab/slabs обнаружен дуговой сегмент. "
                "Пока поддерживаются только прямые сегменты."
            )
        pts.append((float(p[0]) * scale, float(p[1]) * scale))
    if len(pts) >= 3:
        return close_contour(pts)
    return None


def _line_contours(doc, scale, layer_names):
    """Reconstruct closed contours from connected LINE entities."""
    raw = []
    for e in doc.modelspace().query("LINE"):
        if e.dxf.layer.lower() in layer_names:
            raw.append((
                (float(e.dxf.start.x) * scale, float(e.dxf.start.y) * scale),
                (float(e.dxf.end.x) * scale, float(e.dxf.end.y) * scale),
            ))

    unused = set(range(len(raw)))
    contours = []
    tol = 0.01 * max(scale, 1.0)

    while unused:
        seed = unused.pop()
        a, b = raw[seed]
        chain = [a, b]

        changed = True
        while changed:
            changed = False

            # Extend at the end.
            end = chain[-1]
            for idx in list(unused):
                p, q = raw[idx]
                if math.hypot(p[0]-end[0], p[1]-end[1]) <= tol:
                    chain.append(q)
                    unused.remove(idx)
                    changed = True
                    break
                if math.hypot(q[0]-end[0], q[1]-end[1]) <= tol:
                    chain.append(p)
                    unused.remove(idx)
                    changed = True
                    break
            if changed:
                if math.hypot(chain[-1][0]-chain[0][0],
                              chain[-1][1]-chain[0][1]) <= tol:
                    break
                continue

            # Extend at the beginning.
            start = chain[0]
            for idx in list(unused):
                p, q = raw[idx]
                if math.hypot(p[0]-start[0], p[1]-start[1]) <= tol:
                    chain.insert(0, q)
                    unused.remove(idx)
                    changed = True
                    break
                if math.hypot(q[0]-start[0], q[1]-start[1]) <= tol:
                    chain.insert(0, p)
                    unused.remove(idx)
                    changed = True
                    break

        if len(chain) >= 4 and math.hypot(chain[-1][0]-chain[0][0],
                                           chain[-1][1]-chain[0][1]) <= tol:
            # Remove duplicated final point; close_contour adds it back.
            contours.append(close_contour(chain[:-1]))

    return contours


def read_plates(doc, thickness_mm):
    """
    Read slab geometry from both common DXF representations:

    1) closed LWPOLYLINE on layer slab/slabs;
    2) a closed chain of LINE entities on layer slab/slabs.

    Contours are classified by containment:
      - an outer contour becomes a Plate;
      - a contour inside an outer contour becomes an Opening.

    This handles both lvl 1.dxf (outer slabs are LWPOLYLINE) and
    floor_clean.dxf (outer slab is a LINE chain, openings are LWPOLYLINE).
    """
    scale = dxf_scale(doc)
    layer_names = {"slab", "slabs"}
    contours = []

    # Closed LWPOLYLINE contours.
    for e in doc.modelspace().query("LWPOLYLINE"):
        if not e.closed or e.dxf.layer.lower() not in layer_names:
            continue
        pts = _closed_polyline_points(e, scale)
        if pts:
            contours.append({
                "points": pts,
                "area": abs(signed_area(pts)),
                "source": "lwpolyline",
            })

    # Closed LINE chains (e.g. floor_clean.dxf).
    for pts in _line_contours(doc, scale, layer_names):
        contours.append({
            "points": pts,
            "area": abs(signed_area(pts)),
            "source": "lines",
        })

    contours = [c for c in contours if c["area"] > 1e-6]
    contours.sort(key=lambda c: c["area"], reverse=True)

    # A contour is an opening if a larger contour contains a point of it.
    # Otherwise it is an outer slab contour.
    is_hole = [False] * len(contours)
    for i, c in enumerate(contours):
        test_point = c["points"][0]
        for j, outer in enumerate(contours):
            if i == j or outer["area"] <= c["area"]:
                continue
            if point_in_polygon(test_point, outer["points"]):
                is_hole[i] = True
                break

    plates = []
    plate_contours = []
    for i, c in enumerate(contours):
        if not is_hole[i]:
            plate_contours.append((i, c))

    pid = 1000
    oid = 1

    for i, c in plate_contours:
        p = Plate(
            id=pid,
            contour=c["points"],
            z=0.0,
            thickness=thickness_mm * 0.001,
            material="slab",
        )
        pid += 1

        for j, hole in enumerate(contours):
            if not is_hole[j]:
                continue
            if point_in_polygon(hole["points"][0], c["points"]):
                p.add_hole(Opening(id=oid, contour=hole["points"]))
                oid += 1

        plates.append(p)

    return plates

def find_dxf():
    candidates = [
        f for f in os.listdir(".")
        if f.lower().endswith(".dxf")
        and not f.lower().endswith("_centerlines.dxf")
        and not f.lower().startswith("forum_ready")
    ]
    if len(candidates) == 1:
        return candidates[0]
    if "floor_clean.dxf" in candidates:
        return "floor_clean.dxf"
    return None

def process(input_file, floor_height_mm, slab_thickness_mm, log):
    base = os.path.splitext(os.path.basename(input_file))[0]
    work_dir = os.path.dirname(os.path.abspath(__file__))
    osi_file = os.path.join(work_dir, f"{base}_CENTERLINES.dxf")
    output_file = os.path.join(work_dir, f"{base}_CENTERLINES.sdnf")

    log(f"Исходный DXF: {input_file}")
    log("1/3  Строим оси стен...")
    subprocess.run(
        [sys.executable, os.path.join(work_dir, "centerlines.py"),
         input_file, osi_file],
        cwd=work_dir,
        check=True
    )

    src = ezdxf.readfile(input_file)
    scale = dxf_scale(src)

    log("2/3  Читаем объекты...")
    walls = read_walls_from_osi(scale, osi_file)
    columns = read_columns(src, floor_height_mm)
    plates = read_plates(src, slab_thickness_mm)

    log("3/3  Формируем единый SDNF...")
    UnifiedSDNFWriter(floor_height_mm * 0.001).write(
        output_file, walls, columns, plates
    )

    holes = sum(len(p.holes) for p in plates)
    log("")
    log("ГОТОВО")
    log(f"Стены: {len(walls)}")
    log(f"Колонны: {len(columns)}")
    log(f"Плиты: {len(plates)}")
    log(f"Отверстия: {holes}")
    log(f"Результат: {output_file}")
    return output_file, len(walls), len(columns), len(plates), holes

def main():
    root = tk.Tk()
    root.title("CENTERLINES — единый SDNF")
    root.geometry("620x500")
    root.resizable(False, False)

    selected = {"file": None}

    tk.Label(root, text="CENTERLINES — единый SDNF",
             font=("Arial", 14, "bold")).pack(pady=12)

    frame = tk.Frame(root)
    frame.pack(fill="x", padx=15)

    tk.Label(frame, text="DXF:").grid(row=0, column=0, sticky="w")
    file_var = tk.StringVar(value=find_dxf() or "")
    tk.Entry(frame, textvariable=file_var, width=58).grid(row=0, column=1, padx=6)

    def choose():
        p = filedialog.askopenfilename(
            title="Выберите исходный DXF",
            filetypes=[("AutoCAD DXF", "*.dxf"), ("Все файлы", "*.*")]
        )
        if p:
            selected["file"] = p
            file_var.set(p)

    tk.Button(frame, text="Обзор...", command=choose).grid(row=0, column=2)

    tk.Label(frame, text="Высота этажа, мм:").grid(row=1, column=0, sticky="w", pady=8)
    height_var = tk.StringVar(value=str(FLOOR_HEIGHT_DEFAULT))
    tk.Entry(frame, textvariable=height_var, width=12).grid(row=1, column=1, sticky="w")

    tk.Label(frame, text="Толщина плиты, мм:").grid(row=2, column=0, sticky="w", pady=4)
    slab_var = tk.StringVar(value=str(SLAB_THICKNESS_DEFAULT))
    tk.Entry(frame, textvariable=slab_var, width=12).grid(row=2, column=1, sticky="w")

    log_box = scrolledtext.ScrolledText(root, width=72, height=19,
                                        font=("Courier New", 9))
    log_box.pack(padx=15, pady=12)

    def log(msg):
        log_box.insert(tk.END, msg + "\n")
        log_box.see(tk.END)
        root.update_idletasks()

    def start():
        try:
            inp = selected["file"] or file_var.get().strip() or find_dxf()
            if not inp:
                raise FileNotFoundError("Не найден DXF. Выберите исходный файл.")
            if not os.path.isabs(inp):
                inp = os.path.abspath(inp)

            # Work in the directory containing the executable/script.
            # If the DXF is outside it, copy it there for the current run.
            work_dir = os.path.dirname(os.path.abspath(__file__))
            work_input = os.path.basename(inp)
            work_input_path = os.path.join(work_dir, work_input)
            if os.path.abspath(inp) != os.path.abspath(work_input_path):
                import shutil
                shutil.copy2(inp, work_input_path)

            process(
                work_input_path,
                float(height_var.get()),
                float(slab_var.get()),
                log,
            )
            messagebox.showinfo("CENTERLINES", "Единый SDNF успешно создан.")
        except Exception as e:
            log("ОШИБКА: " + str(e))
            messagebox.showerror("Ошибка", str(e))

    tk.Button(root, text="ЗАПУСТИТЬ CENTERLINES",
              font=("Arial", 11, "bold"),
              command=start, height=2, width=38).pack(pady=4)

    root.mainloop()

if __name__ == "__main__":
    main()
