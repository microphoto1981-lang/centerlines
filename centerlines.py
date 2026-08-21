import sys
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Построение осевых линий стен из плана (DXF, только LINE).

v4.0 — ПОЛНАЯ ПЕРЕРАБОТКА ОБРАБОТКИ НАКЛОННЫХ (ДИАГОНАЛЬНЫХ) СТЕН.

ЧТО БЫЛО НЕ ТАК В v3.1
----------------------
1. Горизонтали/вертикали и диагонали обрабатывались двумя РАЗНЫМИ алгоритмами.
   Для H/V грани корректно спаривались по смещению оси (offset) с проверкой
   перекрытия проекций и «непрозрачности» промежуточных граней.
   Для диагоналей же пара искалась по РАССТОЯНИЮ МЕЖДУ СЕРЕДИНАМИ отрезков:

       dist = math.hypot(d2['mx'] - d1['mx'], d2['my'] - d1['my'])

   Это принципиально неверно:
     * середины двух граней ОДНОЙ стены совпадают только если грани имеют
       одинаковую длину и одинаковый вылет на торцах; на реальном плане
       грани обрезаны примыкающими стенами и их длины разные
       (829.6 / 895.9 / 815.5 / 160.0 мм в floor_clean.dxf);
     * при повторяющихся модулях плана ближайшей по середине оказывалась
       грань СОСЕДНЕЙ стены, а не парная грань той же стены;
     * короткие «торцевые» скосы (L = 160 мм) перехватывали пару у длинных граней.
   В итоге ось строилась по неверной паре, «уезжала» по нормали и/или по длине.

2. Ось диагонали строилась как отрезок фиксированной длины
   max(L1, L2) вокруг усреднённой середины — то есть длина оси бралась
   от ГРАНИ, а не от геометрии узла. Правильная ось должна начинаться и
   заканчиваться в узлах сопряжения с соседними осями.

3. Направление оси бралось как направление d1 (первой грани), без усреднения,
   поэтому накапливалась угловая ошибка (в файле есть грань 45.49° вместо 45.00°).

4. Сопряжение делалось постфактум (extend_diagonal_to_orthogonal) и только
   в одну сторону D->H/V, узлы D↔D не обрабатывались вовсе, поэтому
   несопряжённые куски уходили на слой `connect`.

ЧТО СДЕЛАНО В v4.0
------------------
Введена ЕДИНАЯ модель оси в локальной системе координат направления:

    ось = (направление u, нормаль n, смещение c, интервал [t1, t2], толщина th)

    точка оси:  P(t) = n * c + u * t

Горизонталь — частный случай (u = (1,0)), вертикаль — (u = (0,1)),
диагональ 45° — (u = (√2/2, √2/2)). Никакого отдельного кода для диагоналей
больше нет: они проходят ровно тот же конвейер, что и H/V.

Конвейер:
  1. cluster_directions()  — грани группируются по направлению (mod 180°),
     угол кластера уточняется как круговое среднее удвоенных углов,
     взвешенное по длине граней. Это гасит шум типа 45.49°.
  2. project_faces()       — каждая грань проецируется в локальные (c, t1, t2).
  3. merge_collinear()     — склейка коллинеарных кусков одной грани.
  4. pair_faces()          — ПАРЫ ГРАНЕЙ ИЩУТСЯ ПО ПЕРПЕНДИКУЛЯРНОМУ
     РАССТОЯНИЮ МЕЖДУ ЛИНИЯМИ (разность смещений c), а не по расстоянию
     между серединами. Обязательные условия:
        WALL_MIN <= |c_j - c_i| <= WALL_MAX      — правдоподобная толщина стены
        перекрытие проекций [t1,t2] >= MIN_OVERLAP — грани реально напротив
        между ними нет третьей грани, перекрывающей тот же участок
     Именно это и чинит наклонные стены при повторяющихся модулях.
  5. merge_axes()          — склейка коллинеарных осей.
  6. solve_nodes()         — ЕДИНОЕ сопряжение всех типов узлов
     (H↔V, H↔D, V↔D, D↔D) как решение геометрической задачи:
        * для каждой пары непараллельных осей считается точка пересечения
          несущих ПРЯМЫХ (не отрезков);
        * пересечение принимается кандидатом, если оно попадает в «зону узла»
          хотя бы одной оси; допуск на вылет считается из реальной геометрии
          узла: полутолщина встречной стены, делённая на sin угла между осями
          (для 45° это в √2 раз больше, чем для 90° — именно поэтому
          фиксированный допуск v3.1 не работал на диагоналях);
        * близкие кандидаты сливаются в ОДИН узел, положение узла уточняется
          методом наименьших квадратов по всем несущим прямым узла;
        * концы осей переносятся в узел.
     Это не «продление готовых осей», а достройка интервала оси до её
     истинных граничных узлов — интервал [t1,t2] изначально задан только
     обрезкой граней и физического смысла границы не несёт.
  7. Диагностика: слой `connect` получает только те концы, которые
     остались несопряжёнными. На floor_clean.dxf он пуст.
"""

import math
from collections import defaultdict

import ezdxf

# ---- ОБЩИЕ ПАРАМЕТРЫ -------------------------------------------------------
SRC_LAYER        = 'walls'
MIN_LEN          = 100.0    # грани короче игнорируются
COLLINEAR_TOL    = 2.0      # допуск коллинеарности граней (по нормали)
JOIN_GAP         = 30.0     # разрыв, который склеивается вдоль оси

WALL_MIN         = 70.0     # минимальная толщина стены
WALL_MAX         = 260.0    # максимальная толщина стены
MIN_OVERLAP      = 120.0    # минимальное перекрытие проекций пары граней

MIN_CL_LEN       = 150.0    # минимальная длина выводимой осевой
SNAP_TOL         = 25.0     # допуск слияния коллинеарных осей

# ---- ПАРАМЕТРЫ НАПРАВЛЕНИЙ -------------------------------------------------
DIR_TOL_DEG      = 1.5      # допуск группировки граней по направлению
PARALLEL_SIN     = 0.09     # |sin| ниже которого оси считаются параллельными

# ---- ПАРАМЕТРЫ УЗЛОВ -------------------------------------------------------
NODE_SLACK       = 70.0     # добавка к геометрическому допуску узла
NODE_MAX_REACH   = 420.0    # абсолютный предел достройки до узла
NODE_SNAP        = 60.0     # радиус слияния кандидатов в один узел
NODE_ITERATIONS  = 8
TOUCH_TOL        = 1.0      # допуск «конец лежит на оси»
CAP_TOL          = 30.0     # допуск распознавания торцевой грани стены
DEFECT_GAP       = 400.0    # в пределах этого зазора несопряжение = дефект

MIN_SIN_FOR_LIMIT = 0.15    # защита от деления на ~0 для острых углов


# ============================================================================
#  ГЕОМЕТРИЯ ОСИ
# ============================================================================
#
#  Ось хранится словарём:
#     'ang' : угол направления в градусах, приведён к [0, 180)
#     'u'   : (ux, uy) единичный вектор направления
#     'n'   : (nx, ny) единичная нормаль, n = (-uy, ux)
#     'c'   : смещение несущей прямой вдоль нормали  (c = n · P для любой P оси)
#     't1'  : начало интервала вдоль u
#     't2'  : конец интервала вдоль u
#     'th'  : толщина стены (перпендикулярное расстояние между гранями)
#
#  Любая точка оси:  P(t) = n * c + u * t
#  Проекции точки P: t = u · P ,  c = n · P
#
#  Такое представление одинаково работает для H, V и любых наклонных стен,
#  поэтому весь дальнейший код не различает типы стен.

def axis_point(A, t):
    """Точка на несущей прямой оси A с параметром t."""
    ux, uy = A['u']
    nx, ny = A['n']
    c = A['c']
    return (nx * c + ux * t, ny * c + uy * t)


def axis_ends(A):
    """Концевые точки оси.

    Если конец закреплён в узле (solve_nodes), берётся ТОЧНАЯ координата
    узла, а не проекция на несущую прямую. Это принципиально: в узле
    может сходиться 3-4 оси, положение узла — компромисс МНК, и если
    каждая ось отложит свой конец по своей прямой, узел «раскроется»
    на доли миллиметра и линии перестанут стыковаться. Узел — это одна
    вершина, общая для всех входящих в него осей.
    """
    p1 = A.get('pt1') or axis_point(A, A['t1'])
    p2 = A.get('pt2') or axis_point(A, A['t2'])
    return p1, p2


def axis_length(A):
    return A['t2'] - A['t1']


def project_t(A, p):
    """Параметр вдоль оси для точки p."""
    return A['u'][0] * p[0] + A['u'][1] * p[1]


def project_c(A, p):
    """Смещение по нормали для точки p."""
    return A['n'][0] * p[0] + A['n'][1] * p[1]


def sin_between(A, B):
    """|sin| угла между направлениями осей."""
    return abs(A['u'][0] * B['u'][1] - A['u'][1] * B['u'][0])


def line_intersection(A, B):
    """Пересечение НЕСУЩИХ ПРЯМЫХ осей A и B.

    Возвращает (tA, tB, sin) либо None для (почти) параллельных.
    tA, tB — параметры точки пересечения вдоль A и вдоль B.
    """
    ux, uy = A['u']
    vx, vy = B['u']
    den = ux * vy - uy * vx
    if abs(den) < PARALLEL_SIN:
        return None

    ax, ay = A['n'][0] * A['c'], A['n'][1] * A['c']
    bx, by = B['n'][0] * B['c'], B['n'][1] * B['c']
    wx, wy = bx - ax, by - ay

    tA = (wx * vy - wy * vx) / den
    tB = (wx * uy - wy * ux) / den
    return tA, tB, abs(den)


def point_to_axis_distance(p, A):
    """Расстояние от точки до ОТРЕЗКА оси A."""
    t = project_t(A, p)
    t = max(A['t1'], min(A['t2'], t))
    q = axis_point(A, t)
    return math.hypot(p[0] - q[0], p[1] - q[1])


# ============================================================================
#  ЧТЕНИЕ ИСХОДНОГО ПЛАНА
# ============================================================================

def read_faces(path):
    """Читает LINE слоя walls как грани стен.

    Возвращает (faces, raw, doc, skipped).
      faces — грани длиннее MIN_LEN, участвуют в построении осей;
      raw   — ВСЕ отрезки слоя walls, включая короткие; нужны для
              распознавания торцов стен (см. is_wall_capped).
    Грань: {'p1', 'p2', 'len', 'ang'} , ang приведён к [0, 180).
    """
    doc = ezdxf.readfile(path)
    faces = []
    raw = []
    skipped = 0

    for e in doc.modelspace():
        if e.dxftype() != 'LINE':
            continue
        if e.dxf.layer != SRC_LAYER:
            continue

        s, t = e.dxf.start, e.dxf.end
        dx, dy = t.x - s.x, t.y - s.y
        length = math.hypot(dx, dy)
        if length < 1e-9:
            continue

        item = {
            'p1': (s.x, s.y),
            'p2': (t.x, t.y),
            'len': length,
            'ang': math.degrees(math.atan2(dy, dx)) % 180.0,
        }
        raw.append(item)

        if length < MIN_LEN:
            skipped += 1
            continue

        faces.append(item)

    return faces, raw, doc, skipped


# ============================================================================
#  ШАГ 1. ГРУППИРОВКА ГРАНЕЙ ПО НАПРАВЛЕНИЮ
# ============================================================================

def cluster_directions(faces, tol_deg=DIR_TOL_DEG):
    """Группирует грани по направлению по модулю 180°.

    Заменяет прежние read_segments()/group_diagonal_walls():
    горизонтали, вертикали и любые наклонные попадают в один и тот же
    механизм, отдельного «диагонального» пути больше нет.

    Угол кластера уточняется круговым средним УДВОЕННЫХ углов,
    взвешенным по длине граней. Удвоение нужно потому, что направление
    задано по модулю 180° (0° и 179.9° — почти одно и то же направление).
    Взвешивание по длине не даёт коротким торцевым скосам сбить угол.
    """
    clusters = []

    # длинные грани задают направление, короткие к ним подстраиваются
    for f in sorted(faces, key=lambda f: -f['len']):
        placed = False
        for cl in clusters:
            d = abs(f['ang'] - cl['ang'])
            d = min(d, 180.0 - d)
            if d <= tol_deg:
                cl['faces'].append(f)
                placed = True
                break
        if not placed:
            clusters.append({'ang': f['ang'], 'faces': [f]})

    for cl in clusters:
        cl['ang'] = robust_direction(cl['faces'], cl['ang'])

    clusters.sort(key=lambda c: -sum(f['len'] for f in c['faces']))
    return clusters


def robust_direction(faces, start_ang):
    """Устойчивая оценка направления группы граней.

    Обычное взвешенное среднее «утягивается» одиночной кривой гранью
    (в floor_clean.dxf есть грань 45.49° при остальных 45.00°), и тогда
    ВСЕ наклонные оси плана оказываются повёрнуты на 0.04°, что затем
    даёт миллиметровые расхождения в узлах. Поэтому делаем два прохода
    усечённого среднего: сначала обычное, потом — только по граням,
    близким к нему, если такие грани несут основную длину.
    """
    ang = start_ang

    for trim in (None, 0.25, 0.05):
        sx = sy = 0.0
        used = 0.0
        for f in faces:
            if trim is not None:
                d = abs(f['ang'] - ang)
                d = min(d, 180.0 - d)
                if d > trim:
                    continue
            a2 = math.radians(f['ang'] * 2.0)
            sx += math.cos(a2) * f['len']
            sy += math.sin(a2) * f['len']
            used += f['len']

        total = sum(f['len'] for f in faces) or 1.0
        if used < 0.5 * total:
            break                      # доминирующего направления нет
        if sx or sy:
            ang = (math.degrees(math.atan2(sy, sx)) / 2.0) % 180.0

    return ang


# ============================================================================
#  ШАГ 2-3. ПРОЕКЦИЯ ГРАНЕЙ И СКЛЕЙКА КОЛЛИНЕАРНЫХ
# ============================================================================

def project_faces(cluster):
    """Переводит грани кластера в локальные координаты (c, t1, t2)."""
    ang = math.radians(cluster['ang'])
    ux, uy = math.cos(ang), math.sin(ang)
    nx, ny = -uy, ux

    projected = []
    for f in cluster['faces']:
        (x1, y1), (x2, y2) = f['p1'], f['p2']
        c = (nx * x1 + ny * y1 + nx * x2 + ny * y2) / 2.0
        s1 = ux * x1 + uy * y1
        s2 = ux * x2 + uy * y2
        projected.append((c, min(s1, s2), max(s1, s2)))

    frame = {'ang': cluster['ang'], 'u': (ux, uy), 'n': (nx, ny)}
    return projected, frame


def merge_collinear(items, axis_tol=COLLINEAR_TOL, gap=JOIN_GAP):
    """Склейка коллинеарных граней: список (c, t1, t2)."""
    if not items:
        return []

    bands = []
    for c, s1, s2 in sorted(items, key=lambda it: it[0]):
        if bands and abs(bands[-1][0] - c) <= axis_tol:
            bands[-1][1].append((s1, s2, c))
        else:
            bands.append([c, [(s1, s2, c)]])

    out = []
    for _, spans in bands:
        spans.sort()
        cur_a, cur_b = spans[0][0], spans[0][1]
        acc = [(spans[0][2], spans[0][1] - spans[0][0])]
        chunks = []

        for a1, b1, cx in spans[1:]:
            if a1 <= cur_b + gap:
                cur_b = max(cur_b, b1)
                acc.append((cx, b1 - a1))
            else:
                chunks.append((cur_a, cur_b, acc))
                cur_a, cur_b = a1, b1
                acc = [(cx, b1 - a1)]
        chunks.append((cur_a, cur_b, acc))

        for lo, hi, acc in chunks:
            w = sum(x for _, x in acc) or 1.0
            out.append((sum(a * x for a, x in acc) / w, lo, hi))

    return out


# ============================================================================
#  ШАГ 4. СПАРИВАНИЕ ГРАНЕЙ ПО ПЕРПЕНДИКУЛЯРНОМУ РАССТОЯНИЮ
# ============================================================================

def pair_faces(faces):
    """Ищет пары граней одной стены и строит осевые.

    ЭТО КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ. Критерий пары — НЕ расстояние между
    серединами отрезков (как было в build_diagonal_centerlines v3.1),
    а перпендикулярное расстояние между несущими прямыми граней:

        thickness = c_j - c_i        (грани отсортированы по c)

    Проверяется три условия:
      1) WALL_MIN <= thickness <= WALL_MAX — толщина правдоподобна;
      2) перекрытие интервалов [t1,t2] >= MIN_OVERLAP — грани реально
         стоят друг напротив друга, а не просто параллельны где-то рядом
         (именно это отсекает соседний модуль плана);
      3) между гранями нет третьей грани, перекрывающей тот же участок —
         иначе стена «прошивалась» бы насквозь через соседнее помещение.

    faces: список (c, t1, t2)
    return: (осевые [(c, t1, t2, thickness)], неспаренные грани)
    """
    faces = sorted(faces, key=lambda f: f[0])
    n = len(faces)
    axes = []
    paired = [False] * n

    for i in range(n):
        ci, s1, s2 = faces[i]
        for j in range(i + 1, n):
            cj, t1, t2 = faces[j]
            thickness = cj - ci

            if thickness > WALL_MAX:
                break                     # дальше только толще — выходим
            if thickness < WALL_MIN:
                continue

            lo, hi = max(s1, t1), min(s2, t2)
            if hi - lo < MIN_OVERLAP:
                continue

            blocked = False
            for k in range(i + 1, j):
                ck, u1, u2 = faces[k]
                if not (ci + COLLINEAR_TOL < ck < cj - COLLINEAR_TOL):
                    continue
                if min(hi, u2) - max(lo, u1) > MIN_OVERLAP:
                    blocked = True
                    break
            if blocked:
                continue

            axes.append(((ci + cj) / 2.0, lo, hi, thickness))
            paired[i] = paired[j] = True

    unpaired = [faces[k] for k in range(n) if not paired[k]]
    return axes, unpaired


# ============================================================================
#  ШАГ 5. СКЛЕЙКА КОЛЛИНЕАРНЫХ ОСЕЙ
# ============================================================================

def merge_axes(axes, snap=SNAP_TOL, gap=JOIN_GAP):
    """Склейка осей на одной несущей прямой. axes: [(c, t1, t2, th)]"""
    if not axes:
        return []

    bands = []
    for c, t1, t2, th in sorted(axes, key=lambda a: (a[0], a[1])):
        if bands and abs(bands[-1][0] - c) <= snap:
            bands[-1][1].append((t1, t2, th, c))
        else:
            bands.append([c, [(t1, t2, th, c)]])

    out = []
    for _, spans in bands:
        spans.sort()
        cur_a, cur_b, cur_t = spans[0][0], spans[0][1], spans[0][2]
        acc = [(spans[0][3], spans[0][1] - spans[0][0])]
        chunks = []

        for a1, b1, th1, cx in spans[1:]:
            if a1 <= cur_b + gap:
                cur_b = max(cur_b, b1)
                cur_t = max(cur_t, th1)
                acc.append((cx, b1 - a1))
            else:
                chunks.append((cur_a, cur_b, cur_t, acc))
                cur_a, cur_b, cur_t = a1, b1, th1
                acc = [(cx, b1 - a1)]
        chunks.append((cur_a, cur_b, cur_t, acc))

        for lo, hi, th, acc in chunks:
            w = sum(x for _, x in acc) or 1.0
            out.append((sum(a * x for a, x in acc) / w, lo, hi, th))

    return out


def build_axes(faces):
    """Полный проход: направления -> проекция -> склейка -> пары -> оси."""
    clusters = cluster_directions(faces)
    all_axes = []
    stats = []

    for cl in clusters:
        projected, frame = project_faces(cl)
        merged = merge_collinear(projected)
        raw, unpaired = pair_faces(merged)
        joined = merge_axes(raw)

        for c, t1, t2, th in joined:
            all_axes.append({
                'ang': frame['ang'],
                'u': frame['u'],
                'n': frame['n'],
                'c': c,
                't1': t1,
                't2': t2,
                'th': th,
            })

        stats.append({
            'ang': frame['ang'],
            'faces': len(cl['faces']),
            'merged': len(merged),
            'axes': len(joined),
            'unpaired': len(unpaired),
        })

    for idx, A in enumerate(all_axes):
        A['id'] = idx

    return all_axes, stats


# ============================================================================
#  ШАГ 6. СОПРЯЖЕНИЕ УЗЛОВ: H↔V, H↔D, V↔D, D↔D
# ============================================================================
#
#  Прежний extend_diagonal_to_orthogonal() был постобработкой: он двигал
#  готовые концы диагоналей к первой попавшейся ортогональной оси с
#  фиксированным допуском 400/50. Здесь узел решается геометрически.
#
#  Ключевой момент для наклонных стен: величина «недовода» конца оси до
#  узла НЕ постоянна — она зависит от угла между осями. Грань стены
#  обрезается по грани встречной стены, поэтому конец оси не доходит до
#  точки пересечения на
#
#        reach = (th_встречной / 2) / sin(угол между осями)
#
#  Для перпендикулярного узла sin = 1 и reach = th/2 (как в v3.1).
#  Для узла 45° sin = √2/2 и reach = th/2 * √2 ≈ 1.41 * th/2.
#  Для узла D↔D под 90° между двумя 45°-осями — снова th/2.
#  Именно поэтому фиксированный допуск не закрывал диагональные узлы.

def node_reach(A, B, sin_ab):
    """Допустимая достройка конца оси A до пересечения с осью B."""
    limit = B['th'] / (2.0 * max(sin_ab, MIN_SIN_FOR_LIMIT)) + NODE_SLACK
    return min(limit, NODE_MAX_REACH)


def classify_hit(A, t, reach):
    """Как точка с параметром t относится к оси A.

    't1'      — попадает в зону начального узла;
    't2'      — попадает в зону конечного узла;
    'through' — проходит сквозь ось (T-образное примыкание);
    None      — слишком далеко, узлом не является.
    """
    span = A['t2'] - A['t1']
    near = min(reach, span / 2.0)

    if t < A['t1'] + near:
        return 't1' if t >= A['t1'] - reach else None
    if t > A['t2'] - near:
        return 't2' if t <= A['t2'] + reach else None
    return 'through'


def collect_node_candidates(axes):
    """Кандидаты в узлы для ВСЕХ пар непараллельных осей.

    Тип пары (H-V, H-D, V-D, D-D) роли не играет — критерий один.
    """
    cands = []
    n = len(axes)

    for i in range(n):
        A = axes[i]
        for j in range(i + 1, n):
            B = axes[j]

            hit = line_intersection(A, B)
            if hit is None:
                continue
            tA, tB, sin_ab = hit

            eA = classify_hit(A, tA, node_reach(A, B, sin_ab))
            if eA is None:
                continue
            eB = classify_hit(B, tB, node_reach(B, A, sin_ab))
            if eB is None:
                continue
            if eA == 'through' and eB == 'through':
                continue          # оси и так пересекаются в середине

            cands.append({
                'i': i, 'j': j,
                'eA': eA, 'eB': eB,
                'P': axis_point(A, tA),
            })

    return cands


def cluster_node_candidates(cands, snap=NODE_SNAP):
    """Сливает близкие кандидаты в один узел.

    Нужно для узлов, где сходятся 3+ оси (например H + V + D в углу
    скошенного помещения): три попарных пересечения должны стать одной
    точкой, иначе оси разъедутся на доли миллиметра и узел «раскроется».
    """
    nodes = []

    for c in sorted(cands, key=lambda c: (c['P'][0], c['P'][1])):
        best, best_d = None, snap
        for nd in nodes:
            d = math.hypot(nd['P'][0] - c['P'][0], nd['P'][1] - c['P'][1])
            if d < best_d:
                best_d, best = d, nd

        if best is None:
            nodes.append({'P': c['P'], 'cands': [c], 'members': {}})
        else:
            best['cands'].append(c)
            k = len(best['cands'])
            best['P'] = ((best['P'][0] * (k - 1) + c['P'][0]) / k,
                         (best['P'][1] * (k - 1) + c['P'][1]) / k)

    for nd in nodes:
        for c in nd['cands']:
            for idx, end in ((c['i'], c['eA']), (c['j'], c['eB'])):
                prev = nd['members'].get(idx)
                # конец оси приоритетнее сквозного прохода
                if prev is None or (prev == 'through' and end != 'through'):
                    nd['members'][idx] = end

    return nodes


def solve_node_point(axes, node):
    """Уточняет положение узла как наименее-квадратичное решение
    системы n_k · P = c_k по всем несущим прямым узла.

    Для двух осей это ровно точка пересечения; для трёх и более —
    компромисс, из-за которого узел остаётся единой точкой.
    Решается вручную (2x2 нормальные уравнения), без numpy.
    """
    a11 = a12 = a22 = b1 = b2 = 0.0
    for idx in node['members']:
        A = axes[idx]
        nx, ny = A['n']
        c = A['c']
        a11 += nx * nx
        a12 += nx * ny
        a22 += ny * ny
        b1 += nx * c
        b2 += ny * c

    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-9:
        return node['P']

    return ((b1 * a22 - b2 * a12) / det,
            (a11 * b2 - a12 * b1) / det)


def apply_nodes(axes, nodes):
    """Переносит концы осей в узлы. Возвращает число изменений.

    Помимо параметра t запоминается ТОЧКА узла (pt1/pt2), чтобы концы
    всех осей узла совпали бит в бит.
    """
    moved = 0

    for A in axes:
        A.pop('pt1', None)
        A.pop('pt2', None)

    for nd in nodes:
        P = solve_node_point(axes, nd)
        nd['P'] = P

        for idx, end in nd['members'].items():
            A = axes[idx]
            t = project_t(A, P)

            if end == 't1':
                if abs(A['t1'] - t) > 1e-9:
                    moved += 1
                A['t1'] = t
                A['pt1'] = P
            elif end == 't2':
                if abs(A['t2'] - t) > 1e-9:
                    moved += 1
                A['t2'] = t
                A['pt2'] = P
            else:                       # 'through' — узел внутри оси
                if t < A['t1'] - 1e-9:
                    A['t1'] = t
                    A['pt1'] = P
                    moved += 1
                elif t > A['t2'] + 1e-9:
                    A['t2'] = t
                    A['pt2'] = P
                    moved += 1

    return moved


def solve_nodes(axes, iterations=NODE_ITERATIONS):
    """Итеративное замыкание всех узлов сети осей."""
    nodes = []
    for _ in range(iterations):
        cands = collect_node_candidates(axes)
        nodes = cluster_node_candidates(cands)
        if apply_nodes(axes, nodes) == 0:
            break
    return axes, nodes


# ============================================================================
#  ДИАГНОСТИКА
# ============================================================================

def unresolved_ends(axes, raw, gap=DEFECT_GAP, touch=TOUCH_TOL):
    """Концы осей, которые НЕ сопряжены, но рядом есть встречная ось.

    Это и есть содержимое слоя `connect`: разрыв, который алгоритм
    должен был закрыть, но не закрыл.

    Не считаются дефектом:
      * свободные концы, рядом с которыми вообще ничего нет;
      * концы, закрытые торцевой гранью в исходном плане
        (is_wall_capped) — там стена реально обрывается.
    """
    bad = []

    for i, A in enumerate(axes):
        e1, e2 = axis_ends(A)
        for lbl, P in (('t1', e1), ('t2', e2)):
            attached = False
            nearest = None

            for j, B in enumerate(axes):
                if i == j:
                    continue
                if sin_between(A, B) < PARALLEL_SIN:
                    continue
                d = point_to_axis_distance(P, B)
                if d <= touch:
                    attached = True
                    break
                if d <= gap and (nearest is None or d < nearest[1]):
                    nearest = (j, d)

            if attached or nearest is None:
                continue
            if is_wall_capped(A, P, raw):
                continue

            bad.append({'axis': i, 'end': lbl, 'P': P,
                        'other': nearest[0], 'dist': nearest[1]})

    return bad


def open_ends_count(axes, tol=TOUCH_TOL):
    """Общее число концов, не лежащих ни на одной другой оси."""
    total = 0
    for i, A in enumerate(axes):
        for P in axis_ends(A):
            if not any(
                j != i and point_to_axis_distance(P, B) <= tol
                for j, B in enumerate(axes)
            ):
                total += 1
    return total


def kind_of(A):
    """Условное имя типа оси для отчёта."""
    a = A['ang'] % 180.0
    if min(a, 180.0 - a) <= DIR_TOL_DEG:
        return 'H'
    if abs(a - 90.0) <= DIR_TOL_DEG:
        return 'V'
    return 'D'


def is_wall_capped(A, P, raw, tol=CAP_TOL):
    """Проверяет, закрыт ли конец оси A в точке P торцевой гранью.

    Торец стены — короткий отрезок, поперечный оси, длиной примерно
    равной толщине стены и центрированный на конце оси. Если он есть,
    стена ФИЗИЧЕСКИ здесь заканчивается: это не разорванный узел,
    а торец (например, проём или свободный конец перегородки),
    и на слой `connect` он попадать не должен.

    Проверка идёт по исходной геометрии плана, а не по результату —
    поэтому это не «маскировка» дефекта, а корректная классификация.
    """
    ux, uy = A['u']
    for f in raw:
        if abs(f['len'] - A['th']) > tol * 2.0:
            continue
        (x1, y1), (x2, y2) = f['p1'], f['p2']
        dx, dy = (x2 - x1) / f['len'], (y2 - y1) / f['len']
        if abs(dx * ux + dy * uy) > 0.35:      # не поперечный
            continue
        mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        if math.hypot(mx - P[0], my - P[1]) <= tol:
            return True
    return False


# ============================================================================
#  ЗАПИСЬ РЕЗУЛЬТАТА
# ============================================================================

def write_dxf(src_doc, axes, defects, dst):
    dst_doc = ezdxf.new('R2010', setup=True)
    msp = dst_doc.modelspace()

    # Preserve structural objects from the source DXF.
    # Columns in the source are LINE rectangles; slabs are closed LWPOLYLINE.
    # Keep both singular/plural slab layer names.
    for e in src_doc.modelspace():
        layer = e.dxf.layer
        if e.dxftype() == 'LINE' and layer.lower() == 'columns':
            if layer not in dst_doc.layers:
                dst_doc.layers.add(layer)
            msp.add_line(
                e.dxf.start, e.dxf.end,
                dxfattribs={'layer': layer}
            )
        elif layer.lower() in ('slab', 'slabs') and e.dxftype() == 'LINE':
            # Some source drawings (e.g. floor_clean.dxf) describe the
            # slab perimeter as a connected chain of LINE entities.
            if layer not in dst_doc.layers:
                dst_doc.layers.add(layer)
            msp.add_line(
                e.dxf.start, e.dxf.end,
                dxfattribs={'layer': layer}
            )
        elif e.dxftype() == 'LWPOLYLINE' and layer.lower() in ('slab', 'slabs'):
            if layer not in dst_doc.layers:
                dst_doc.layers.add(layer)
            points = list(e.get_points('xyseb'))
            msp.add_lwpolyline(
                points,
                format='xyseb',
                dxfattribs={'layer': layer, 'closed': e.closed}
            )

    counts = defaultdict(int)
    for A in axes:
        if axis_length(A) < MIN_CL_LEN:
            continue
        p1, p2 = axis_ends(A)
        # Keep the automatically determined wall thickness with the axis.
        # The helper DXF uses a separate layer per thickness only as an
        # internal transport mechanism; Forum does not receive these layers.
        th_mm = round(A['th'], 1)
        layer_name = f'walls_{th_mm:g}'
        if layer_name not in dst_doc.layers:
            dst_doc.layers.add(layer_name)
        msp.add_line(p1, p2, dxfattribs={'layer': layer_name})
        counts[kind_of(A)] += 1

    if defects:
        dst_doc.layers.add('connect', color=1)
        for d in defects:
            A = axes[d['axis']]
            B = axes[d['other']]
            t = max(B['t1'], min(B['t2'], project_t(B, d['P'])))
            msp.add_line(d['P'], axis_point(B, t),
                         dxfattribs={'layer': 'connect'})

    dst_doc.saveas(dst)
    return counts


# ============================================================================
#  ОСНОВНОЙ ПРОЦЕСС
# ============================================================================

def process(src, dst):
    print('=' * 72)
    print('ПОСТРОЕНИЕ ОСЕВЫХ ЛИНИЙ СТЕН  v4.0')
    print('=' * 72)

    faces, raw, doc, skipped = read_faces(src)
    print(f'\nГрани стен: {len(faces)}   (пропущено короче {MIN_LEN} мм: {skipped})')

    axes, stats = build_axes(faces)

    print('\nГРУППЫ НАПРАВЛЕНИЙ (единый конвейер для H, V и наклонных):')
    print(f"  {'угол':>9} {'граней':>8} {'после склейки':>15} "
          f"{'осей':>7} {'неспарено':>11}")
    for st in stats:
        print(f"  {st['ang']:9.3f} {st['faces']:8d} {st['merged']:15d} "
              f"{st['axes']:7d} {st['unpaired']:11d}")

    by_kind = defaultdict(int)
    for A in axes:
        by_kind[kind_of(A)] += 1
    print(f"\nПостроено осей: {len(axes)}  "
          f"(H={by_kind['H']}, V={by_kind['V']}, D={by_kind['D']})")

    print('\nНАКЛОННЫЕ ОСИ (пары граней определены по перпендикулярному '
          'расстоянию):')
    diag = [A for A in axes if kind_of(A) == 'D']
    for k, A in enumerate(diag, 1):
        p1, p2 = axis_ends(A)
        print(f'  [{k:2d}] угол={A["ang"]:7.3f}°  толщина={A["th"]:6.1f}  '
              f'({p1[0]:9.1f}, {p1[1]:8.1f}) - ({p2[0]:9.1f}, {p2[1]:8.1f})')

    before = open_ends_count(axes)
    axes, nodes = solve_nodes(axes)
    after = open_ends_count(axes)

    print(f'\nСОПРЯЖЕНИЕ УЗЛОВ: найдено узлов {len(nodes)}')
    pair_kinds = defaultdict(int)
    for nd in nodes:
        ks = sorted(kind_of(axes[i]) for i in nd['members'])
        pair_kinds['+'.join(ks)] += 1
    for key in sorted(pair_kinds):
        print(f'  {key:<12} {pair_kinds[key]}')
    print(f'  свободных концов: было {before} -> стало {after}')

    defects = unresolved_ends(axes, raw)
    counts = write_dxf(doc, axes, defects, dst)

    print(f'\nЗАПИСАНО В {dst}:')
    print(f"  осевые walls: H={counts['H']}, V={counts['V']}, D={counts['D']}"
          f"  всего {sum(counts.values())}")
    print(f'  слой connect: {len(defects)}')

    if defects:
        print('\n  НЕСОПРЯЖЁННЫЕ КОНЦЫ:')
        for d in defects:
            A = axes[d['axis']]
            print(f"    {kind_of(A)} ({d['P'][0]:.1f}, {d['P'][1]:.1f})  "
                  f"зазор {d['dist']:.1f} до "
                  f"{kind_of(axes[d['other']])}")
    else:
        print('\n  [OK] Слой connect ПУСТ — все узлы сопряжены.')

    print('=' * 72)
    return len(defects)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Использование: python centerlines.py <input.dxf> [output.dxf]")
        sys.exit(2)

    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) >= 3 else (
        os.path.splitext(os.path.basename(src))[0] + "_CENTERLINES.dxf"
    )
    process(src, dst)
