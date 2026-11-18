"""Construit la scène Blender complète d'une variante du chalet à partir du JSON, puis
enregistre le .blend, exporte le .glb du bâtiment et calcule les rendus Cycles.

Usage : python blender_scene.py <traditionnel|contemporain> [--preview] [--cams sud,interieur,aerienne] [--no-render]
"""
import bpy, bmesh, json, math, os, sys, time
import numpy as np
from mathutils import Vector, Matrix
import shapely
from shapely.geometry import Polygon

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
args = sys.argv[1:]
VAR = args[0] if args else "traditionnel"
PREVIEW = "--preview" in args
NO_RENDER = "--no-render" in args
CAMS = None
if "--cams" in args: CAMS = args[args.index("--cams") + 1].split(",")
D = json.load(open(os.path.join(OUT, f"chalet_{VAR}.json"), encoding="utf-8"))
ST = D["style"]
TRAD = VAR == "traditionnel"
LV = {l["id"]: l for l in D["niveaux"]}
A1 = LV["R+1"]["altitude"]; BASE = A1 + LV["R+1"]["hauteur"]
CX, CY = 5.6, 3.4
rng = np.random.default_rng(7)

# ----------------------------------------------------------------- scène vierge
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

def coll(name, parent=None):
    c = bpy.data.collections.new(name)
    (parent or scene.collection).children.link(c)
    return c

C_BAT = coll("Bâtiment"); C_RDC = coll("RDC", C_BAT); C_R1 = coll("R+1", C_BAT)
C_TOIT = coll("Toiture", C_BAT); C_MENU = coll("Menuiseries", C_BAT); C_DECOR = coll("Détails de façade", C_BAT)
C_MOB = coll("Mobilier", C_BAT)
C_SITE = coll("Site"); C_TER = coll("Terrain", C_SITE); C_VEG = coll("Végétation", C_SITE); C_LIB = coll("Bibliothèque (modèles instanciés)", C_SITE)
C_CAM = coll("Caméras et lumières")
C_LEVEL = {"RDC": C_RDC, "R+1": C_R1}

# ----------------------------------------------------------------- matériaux (nœuds procéduraux)
def new_mat(name):
    m = bpy.data.materials.new(name)
    try: m.use_nodes = True
    except Exception: pass
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (900, 0)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled"); b.location = (600, 0)
    nt.links.new(b.outputs[0], out.inputs[0])
    return m, nt, b, out

def hexc(h, k=1.0):
    h = h.lstrip("#"); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c]   # sRGB → linéaire
    return (c[0] * k, c[1] * k, c[2] * k, 1)

class N:
    """Petit assistant pour câbler des nœuds."""
    def __init__(s, nt): s.nt = nt
    def n(s, t, **kw):
        node = s.nt.nodes.new(t)
        for k, v in kw.items():
            if k.startswith("i_"):
                key = k[2:].replace("__", " ")
                inp = node.inputs[int(key)] if key.isdigit() else node.inputs[key]
                inp.default_value = v
            else: setattr(node, k, v)
        return node
    def l(s, a, b): s.nt.links.new(a, b)
    def math(s, op, a=None, b=None, va=0.0, vb=0.0):
        m = s.n("ShaderNodeMath", operation=op)
        if a is not None: s.l(a, m.inputs[0])
        else: m.inputs[0].default_value = va
        if b is not None: s.l(b, m.inputs[1])
        else: m.inputs[1].default_value = vb
        return m.outputs[0]
    def mix(s, fac, c1, c2):
        m = s.n("ShaderNodeMix", data_type="RGBA")
        for i, v in ((0, fac), (6, c1), (7, c2)):
            if isinstance(v, (int, float, tuple)): m.inputs[i].default_value = v
            else: s.l(v, m.inputs[i])
        return m.outputs[2]
    def pos(s):
        g = s.n("ShaderNodeNewGeometry"); sep = s.n("ShaderNodeSeparateXYZ"); s.l(g.outputs["Position"], sep.inputs[0])
        return g, sep
    def bump(s, b, height, strength=0.3, dist=0.01):
        bp = s.n("ShaderNodeBump", i_Strength=strength, i_Distance=dist); s.l(height, bp.inputs["Height"]); s.l(bp.outputs[0], b.inputs["Normal"])

MATS = {}

def mat_planks(name, d, axis="xy", width=None, vertical=True):
    m, nt, b, _ = new_mat(name); n = N(nt)
    w = width or {"bois": 0.13}.get(d["type"], 0.13) * d.get("echelle", 1.0)
    g, sep = n.pos()
    u = n.math("ADD", sep.outputs[0], sep.outputs[1]) if axis == "xy" else sep.outputs[0 if axis == "x" else 1]
    uu = n.math("DIVIDE", u, None, vb=w)
    fr = n.math("FRACT", uu); idx = n.math("FLOOR", uu)
    groove = n.math("LESS_THAN", fr, None, vb=0.06)
    wn = n.n("ShaderNodeTexWhiteNoise", noise_dimensions="1D"); n.l(idx, wn.inputs["W"])
    base = hexc(d["couleur"])
    c = n.mix(wn.outputs["Value"], hexc(d["couleur"], 0.78), hexc(d["couleur"], 1.18))
    mp = n.n("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (60, 60, 3) if vertical else (3, 3, 60)
    n.l(g.outputs["Position"], mp.inputs["Vector"])
    grain = n.n("ShaderNodeTexNoise", i_Scale=1.0, i_Detail=6.0, i_Roughness=0.6); n.l(mp.outputs[0], grain.inputs["Vector"])
    c2 = n.mix(n.math("MULTIPLY", grain.outputs["Fac"], None, vb=0.35), c, hexc(d["couleur"], 0.6))
    c3 = n.mix(n.math("MULTIPLY", groove, None, vb=0.85), c2, (0.02, 0.015, 0.01, 1))
    n.l(c3, b.inputs["Base Color"]); b.inputs["Roughness"].default_value = 0.72
    h = n.math("SUBTRACT", n.math("MULTIPLY", grain.outputs["Fac"], None, vb=0.15), groove)
    n.bump(b, h, 0.35, 0.006)
    return m

def mat_enduit(name, d, rough=0.92, scale=60, strength=0.12):
    m, nt, b, _ = new_mat(name); n = N(nt)
    g, sep = n.pos()
    nz = n.n("ShaderNodeTexNoise", i_Scale=scale, i_Detail=8.0); n.l(g.outputs["Position"], nz.inputs["Vector"])
    big = n.n("ShaderNodeTexNoise", i_Scale=0.8, i_Detail=3.0); n.l(g.outputs["Position"], big.inputs["Vector"])
    c = n.mix(n.math("MULTIPLY", big.outputs["Fac"], None, vb=0.5), hexc(d["couleur"], 1.03), hexc(d["couleur"], 0.9))
    n.l(c, b.inputs["Base Color"]); b.inputs["Roughness"].default_value = rough
    n.bump(b, nz.outputs["Fac"], strength, 0.004)
    return m

def mat_pierre(name, d):
    m, nt, b, _ = new_mat(name); n = N(nt)
    g, sep = n.pos()
    mp = n.n("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (1.0, 1.0, 1.7); n.l(g.outputs["Position"], mp.inputs["Vector"])
    vo = n.n("ShaderNodeTexVoronoi", feature="DISTANCE_TO_EDGE", i_Scale=3.2 / d.get("echelle", 1.0)); n.l(mp.outputs[0], vo.inputs["Vector"])
    vc = n.n("ShaderNodeTexVoronoi", i_Scale=3.2 / d.get("echelle", 1.0)); n.l(mp.outputs[0], vc.inputs["Vector"])
    joint = n.math("LESS_THAN", vo.outputs["Distance"], None, vb=0.035)
    nz = n.n("ShaderNodeTexNoise", i_Scale=25, i_Detail=8); n.l(g.outputs["Position"], nz.inputs["Vector"])
    sat = n.n("ShaderNodeHueSaturation", i_Saturation=0.25, i_Value=1.0); n.l(vc.outputs["Color"], sat.inputs["Color"])
    stone = n.mix(0.72, sat.outputs[0], hexc(d["couleur"]))
    stone = n.mix(n.math("MULTIPLY", nz.outputs["Fac"], None, vb=0.4), stone, hexc(d["couleur"], 0.65))
    c = n.mix(joint, stone, (0.33, 0.32, 0.30, 1))
    n.l(c, b.inputs["Base Color"]); b.inputs["Roughness"].default_value = 0.88
    h = n.math("ADD", n.math("MULTIPLY", vo.outputs["Distance"], None, vb=2.0), n.math("MULTIPLY", nz.outputs["Fac"], None, vb=0.3))
    n.bump(b, n.math("MINIMUM", h, None, vb=0.3), 0.7, 0.03)
    return m

def mat_zinc(name, d):
    m, nt, b, _ = new_mat(name); n = N(nt)
    g, sep = n.pos()
    uu = n.math("DIVIDE", sep.outputs[1], None, vb=0.5)
    fr = n.math("FRACT", uu)
    seam = n.math("LESS_THAN", fr, None, vb=0.035)
    wn = n.n("ShaderNodeTexWhiteNoise", noise_dimensions="1D"); n.l(n.math("FLOOR", uu), wn.inputs["W"])
    nz = n.n("ShaderNodeTexNoise", i_Scale=6, i_Detail=4); n.l(g.outputs["Position"], nz.inputs["Vector"])
    c = n.mix(n.math("MULTIPLY", wn.outputs["Value"], None, vb=0.25), hexc(d["couleur"]), hexc(d["couleur"], 1.2))
    c = n.mix(seam, c, hexc(d["couleur"], 1.25))
    n.l(c, b.inputs["Base Color"]); b.inputs["Metallic"].default_value = 0.75
    r = n.math("ADD", n.math("MULTIPLY", nz.outputs["Fac"], None, vb=0.15), None, vb=0.3); n.l(r, b.inputs["Roughness"])
    n.bump(b, seam, 0.6, 0.02)
    return m

def mat_brick_floor(name, d, w, h, mortar, rough):
    m, nt, b, _ = new_mat(name); n = N(nt)
    g, sep = n.pos()
    br = n.n("ShaderNodeTexBrick", offset=0.5 if d["type"] == "parquet" else 0.0, offset_frequency=1, squash=1.0, squash_frequency=1,
             i_Scale=1.0, i_Mortar__Size=mortar, i_Brick__Width=w, i_Row__Height=h, i_Bias=0.0)
    br.inputs["Color1"].default_value = hexc(d["couleur"], 0.85); br.inputs["Color2"].default_value = hexc(d["couleur"], 1.12)
    br.inputs["Mortar"].default_value = hexc(d["couleur"], 0.55 if d["type"] == "parquet" else 1.25)
    n.l(g.outputs["Position"], br.inputs["Vector"])
    mp = n.n("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (3, 60, 3); n.l(g.outputs["Position"], mp.inputs["Vector"])
    nz = n.n("ShaderNodeTexNoise", i_Scale=1, i_Detail=6); n.l(mp.outputs[0], nz.inputs["Vector"])
    k = 0.3 if d["type"] == "parquet" else 0.06
    c = n.mix(n.math("MULTIPLY", nz.outputs["Fac"], None, vb=k), br.outputs["Color"], hexc(d["couleur"], 0.7))
    n.l(c, b.inputs["Base Color"]); b.inputs["Roughness"].default_value = rough
    n.bump(b, n.math("SUBTRACT", None, br.outputs["Fac"], va=1.0), 0.25, 0.004)
    return m

def mat_simple(name, color, rough=0.5, metal=0.0, sheen=0.0):
    m, nt, b, _ = new_mat(name)
    b.inputs["Base Color"].default_value = color; b.inputs["Roughness"].default_value = rough; b.inputs["Metallic"].default_value = metal
    if sheen: b.inputs["Sheen Weight"].default_value = sheen
    return m

def mat_verre(name):
    m, nt, b, out = new_mat(name); n = N(nt)
    b.inputs["Base Color"].default_value = (0.93, 0.97, 0.98, 1); b.inputs["Roughness"].default_value = 0.0
    b.inputs["Transmission Weight"].default_value = 1.0; b.inputs["IOR"].default_value = 1.5
    try: b.inputs["Thin Wall"].default_value = True
    except Exception: pass
    lp = n.n("ShaderNodeLightPath"); tr = n.n("ShaderNodeBsdfTransparent"); tr.inputs[0].default_value = (0.9, 0.95, 0.95, 1)
    mx = n.n("ShaderNodeMixShader"); n.l(lp.outputs["Is Shadow Ray"], mx.inputs[0]); n.l(b.outputs[0], mx.inputs[1]); n.l(tr.outputs[0], mx.inputs[2])
    n.l(mx.outputs[0], out.inputs[0])
    return m

def mat(key):
    if key in MATS: return MATS[key]
    d = D["materiaux"].get(key) or {"type": "peinture", "couleur": "#cccccc"}
    t = d["type"]; name = key
    if t == "bois": m = mat_planks(name, d, axis="x" if key in ("chene", "escalier") else "xy", vertical=key not in ("chene", "escalier"))
    elif t in ("enduit",): m = mat_enduit(name, d)
    elif t == "peinture": m = mat_enduit(name, d, rough=0.8, scale=120, strength=0.04)
    elif t == "pierre": m = mat_pierre(name, d)
    elif t == "zinc": m = mat_zinc(name, d)
    elif t == "parquet": m = mat_brick_floor(name, d, 1.1, 0.16, 0.004, 0.42)
    elif t == "carrelage": m = mat_brick_floor(name, d, 0.6, 0.6, 0.006, 0.3)
    elif t == "metal": m = mat_simple(name, hexc(d["couleur"]), 0.38, 0.55)
    elif t == "tissu": m = mat_simple(name, hexc(d["couleur"]), 0.95, 0, 0.6)
    elif t == "beton": m = mat_enduit(name, d, rough=0.85, scale=30, strength=0.25)
    elif t == "verre": m = mat_verre(name)
    else: m = mat_simple(name, hexc(d.get("couleur", "#cccccc")), 0.6)
    MATS[key] = m
    return m

# ----------------------------------------------------------------- géométrie de base
def mesh_obj(name, verts, faces, mats, mat_idx=None, collection=None, smooth=False, bevel=0.0):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    me.update()
    for m in mats: me.materials.append(m)
    if mat_idx is not None:
        for p, i in zip(me.polygons, mat_idx): p.material_index = i
    if smooth:
        for p in me.polygons: p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    (collection or scene.collection).objects.link(ob)
    if bevel:
        bv = ob.modifiers.new("Chanfrein", "BEVEL"); bv.width = bevel; bv.segments = 2; bv.limit_method = "ANGLE"
    return ob

class MB:
    """Accumulateur de boîtes (repère local) avec matériau par face : ordre +x,-x,+y,-y,+z,-z."""
    def __init__(s): s.v, s.f, s.mi = [], [], []
    def box(s, x0, x1, y0, y1, z0, z1, m):
        if x1 - x0 < 1e-4 or y1 - y0 < 1e-4 or z1 - z0 < 1e-4: return
        if isinstance(m, int): m = [m] * 6
        o = len(s.v)
        s.v += [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        faces = [(1, 2, 6, 5), (0, 4, 7, 3), (2, 3, 7, 6), (0, 1, 5, 4), (4, 5, 6, 7), (0, 3, 2, 1)]
        for f, mm in zip(faces, m): s.f.append(tuple(o + i for i in f)); s.mi.append(mm)
    def beam(s, p0, p1, w, h, m, up=(0, 0, 1)):
        p0, p1 = Vector(p0), Vector(p1); d = (p1 - p0).normalized()
        a = d.cross(Vector(up)); a = a.normalized() if a.length > 1e-6 else Vector((1, 0, 0))
        b_ = a.cross(d).normalized()
        o = len(s.v)
        for p in (p0, p1):
            for sa, sb in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                s.v.append(tuple(p + a * sa * w / 2 + b_ * sb * h / 2))
        for f in ((0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)):
            s.f.append(tuple(o + i for i in f)); s.mi.append(m)
    def poly(s, verts, faces, m):
        o = len(s.v); s.v += list(verts)
        for f in faces: s.f.append(tuple(o + i for i in f)); s.mi.append(m)
    def obj(s, name, mats, coll_, bevel=0.0, smooth=False):
        if not s.f: return None
        return mesh_obj(name, s.v, s.f, mats, s.mi, coll_, smooth, bevel)

def place(ob, origin, angle):
    ob.location = origin; ob.rotation_euler = (0, 0, angle)

def cylinder(name, p0, p1, r, m, coll_, seg=16):
    p0, p1 = Vector(p0), Vector(p1); d = p1 - p0; L = d.length
    bm = bmesh.new(); bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r, depth=L)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for p in me.polygons: p.use_smooth = True
    me.materials.append(m)
    ob = bpy.data.objects.new(name, me); coll_.objects.link(ob)
    ob.location = (p0 + p1) / 2
    ob.rotation_mode = "QUATERNION"; ob.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d.normalized())
    return ob

# ----------------------------------------------------------------- murs + menuiseries
same = lambda p, q: math.hypot(p[0] - q[0], p[1] - q[1]) < 0.02
murs = D["murs"]
by_lvl = {}
for w in murs: by_lvl.setdefault(w["niveau"], []).append(w)
centers = {}
for niv, ws in by_lvl.items():
    ext = [w for w in ws if not w.get("interieur")]
    pts = [p for w in ext for p in (w["de"], w["a"])]
    centers[niv] = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    for w in ws:
        e0 = e1 = 0.0
        if not w.get("interieur"):
            for o in ext:
                if o is w: continue
                ot = o["epaisseur"] / 2
                if same(w["de"], o["a"]) or same(w["de"], o["de"]): e0 = ot
                if same(w["a"], o["de"]): e1 = -ot
                elif same(w["a"], o["a"]): e1 = ot
        w["_ext"] = (e0, e1)

M_MENU = mat("menuiserie"); M_VERRE = mat("verre"); M_LAQUE = mat("laque"); M_PORTE = mat("porte_entree")
M_APPUI = mat("soubassement") if TRAD else mat("menuiserie")
M_VOLET = mat("volet"); M_INT = mat("interieur")
M_POIGNEE = mat_simple("inox", (0.8, 0.8, 0.8, 1), 0.25, 1.0)

def build_wall(w, wi):
    lv = LV[w["niveau"]]; z = lv["altitude"]
    idx = [l["id"] for l in D["niveaux"]].index(w["niveau"])
    nxt = D["niveaux"][idx + 1] if idx + 1 < len(D["niveaux"]) else None
    H = lv["hauteur"] if w.get("interieur") else ((nxt["altitude"] - z) if nxt else lv["hauteur"])
    (x0, y0), (x1, y1) = w["de"], w["a"]
    L = math.hypot(x1 - x0, y1 - y0); t = w["epaisseur"]; ang = math.atan2(y1 - y0, x1 - x0)
    ux, uy = (x1 - x0) / L, (y1 - y0) / L; lx, ly = -uy, ux
    e0, e1 = w["_ext"]
    if w.get("interieur"):
        mats = [M_INT, mat(w.get("materiau", "interieur"))]; side_left, side_right = 1, 1
        ext_sign = 1
    else:
        c = centers[w["niveau"]]; mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        left_in = (c[0] - mx) * lx + (c[1] - my) * ly > 0
        mats = [M_INT, mat(w["materiau_ext"])]
        side_left, side_right = (0, 1) if left_in else (1, 0)
        ext_sign = -1 if left_in else 1
    mb = MB()
    fm = [0, 0, side_left, side_right, 0, 0] if not w.get("interieur") else [0, 0, 1, 1, 0, 0]
    ops = sorted(w.get("ouvertures", []), key=lambda o: o["position"])
    cur = -e0; z0, z1 = z, z + H
    menu = MB(); volets = MB(); deco = MB()
    MI = {"menu": 0, "verre": 1, "laque": 2, "porte": 3, "appui": 4, "poignee": 5}
    for k, o in enumerate(ops):
        typ = o["type"]; p0 = o["position"]; wd = o["largeur"]; p1 = p0 + wd
        al = o.get("allege", 0.9 if typ == "fenetre" else 0.0); h = o.get("hauteur", 2.15 if typ == "porte" else 1.25)
        sz0, sz1 = z + al, z + al + h
        mb.box(cur, p0, -t / 2, t / 2, z0, z1, fm); mb.box(p0, p1, -t / 2, t / 2, z0, sz0, fm); mb.box(p0, p1, -t / 2, t / 2, sz1, z1, fm)
        cur = p1
        f = 0.07 if not TRAD else 0.08; fd = 0.09
        yc = ext_sign * t * 0.12 if not w.get("interieur") else 0.0
        Y0, Y1 = yc - fd / 2, yc + fd / 2
        if typ == "porte":
            fr = MI["menu"] if not w.get("interieur") else MI["laque"]
            menu.box(p0, p0 + f, Y0, Y1, sz0, sz1, fr); menu.box(p1 - f, p1, Y0, Y1, sz0, sz1, fr); menu.box(p0 + f, p1 - f, Y0, Y1, sz1 - f, sz1, fr)
            lw = wd - 2 * f; lh = h - f
            if o.get("entree"):
                menu.box(p0 + f, p1 - f, yc - 0.03, yc + 0.03, sz0, sz0 + lh, MI["porte"])
                for gz in (0.5, 1.0, 1.5):  # cadres de porte en relief
                    menu.box(p0 + f + 0.1, p1 - f - 0.1, yc + ext_sign * 0.03, yc + ext_sign * 0.045, sz0 + gz, sz0 + gz + 0.04, MI["porte"])
                menu.box(p1 - f - 0.12, p1 - f - 0.09, yc + ext_sign * 0.04, yc + ext_sign * 0.1, sz0 + 1.0, sz0 + 1.25, MI["poignee"])
            else:
                s = 1  # battant ouvert à 90°
                menu.box(p0 + f, p0 + f + 0.04, t / 2 * s, t / 2 * s + lw, sz0, sz0 + lh, MI["laque"])
        else:
            menu.box(p0, p0 + f, Y0, Y1, sz0, sz1, MI["menu"]); menu.box(p1 - f, p1, Y0, Y1, sz0, sz1, MI["menu"])
            menu.box(p0 + f, p1 - f, Y0, Y1, sz1 - f, sz1, MI["menu"]); menu.box(p0 + f, p1 - f, Y0, Y1, sz0, sz0 + f, MI["menu"])
            menu.box(p0 + f, p1 - f, yc - 0.012, yc + 0.012, sz0 + f, sz1 - f, MI["verre"])
            nparts = max(1, round(wd / (0.75 if TRAD else 1.6)))
            for j in range(1, nparts):
                xm = p0 + wd * j / nparts; menu.box(xm - 0.035, xm + 0.035, Y0, Y1, sz0 + f, sz1 - f, MI["menu"])
            if TRAD:   # petits bois horizontaux
                rows = 3 if h > 1.6 else 2
                for j in range(1, rows):
                    zm = sz0 + f + (h - 2 * f) * j / rows
                    menu.box(p0 + f, p1 - f, yc - 0.02, yc + 0.02, zm - 0.015, zm + 0.015, MI["menu"])
            if not w.get("interieur") and al > 0.05:    # appui extérieur
                ya, yb = sorted((ext_sign * t * 0.05, ext_sign * (t / 2 + 0.06)))
                menu.box(p0 - 0.05, p1 + 0.05, ya, yb, sz0 - 0.05, sz0, MI["appui"])
            # volets battants (variante traditionnelle)
            if TRAD and not w.get("interieur") and typ in ("fenetre", "baie") and (typ == "fenetre" or o.get("porte_fenetre")):
                prev_end = ops[k - 1]["position"] + ops[k - 1]["largeur"] if k > 0 else -e0 + 0.15
                next_start = ops[k + 1]["position"] if k + 1 < len(ops) else L + e1 - 0.15
                lw = wd / 2 + 0.03
                yv0, yv1 = sorted((ext_sign * (t / 2 + 0.005), ext_sign * (t / 2 + 0.04)))
                for side, ok in ((-1, (p0 - prev_end) / (2 if k > 0 else 1) >= lw), (1, (next_start - p1) / (2 if k + 1 < len(ops) else 1) >= lw)):
                    if not ok: continue
                    xa, xb = (p0 - lw, p0 - 0.01) if side < 0 else (p1 + 0.01, p1 + lw)
                    volets.box(xa, xb, yv0, yv1, sz0 + 0.02, sz1 - 0.02, 0)
                    yb0, yb1 = sorted((ext_sign * (t / 2 + 0.04), ext_sign * (t / 2 + 0.06)))
                    for zb in (0.18, h - 0.28):  # barres
                        volets.box(xa + 0.04, xb - 0.04, yb0, yb1, sz0 + zb, sz0 + zb + 0.1, 0)
                    # écharpe
                    zz0, zz1 = sz0 + 0.28, sz0 + h - 0.28
                    n_ = 10; dx = (xb - xa - 0.12) / n_; dz = (zz1 - zz0) / n_
                    for q in range(n_):
                        volets.box(xa + 0.06 + q * dx, xa + 0.06 + (q + 1) * dx, yb0, yb1, zz0 + q * dz, zz0 + q * dz + 0.09, 0)
    mb.box(cur, L + e1, -t / 2, t / 2, z0, z1, fm)
    nom = ("Cloison" if w.get("interieur") else f"Mur {w.get('facade')}") + f" {w['niveau']} #{wi}"
    ob = mb.obj(nom, mats, C_LEVEL[w["niveau"]], bevel=0.006)
    place(ob, (x0, y0, 0), ang)
    for part, mats_, cname, cl in ((menu, [M_MENU, M_VERRE, M_LAQUE, M_PORTE, M_APPUI, M_POIGNEE], "Menuiseries", C_MENU), (volets, [M_VOLET], "Volets", C_DECOR)):
        o2 = part.obj(f"{cname} — {nom}", mats_, cl, bevel=0.004)
        if o2: o2.parent = ob
    return ob

for i, w in enumerate(murs): build_wall(w, i)

# ----------------------------------------------------------------- dalles
def slab(poly, holes, z_top, ep, m_top, m_bot, m_side, name, coll_):
    P = Polygon(poly, holes or [])
    tris = shapely.constrained_delaunay_triangles(P)
    V, F, MI = [], [], []
    idx = {}
    def vid(x, y, z):
        k = (round(x, 5), round(y, 5), round(z, 5))
        if k not in idx: idx[k] = len(V); V.append((x, y, z))
        return idx[k]
    for tri in tris.geoms:
        c = list(tri.exterior.coords)[:3]
        a = [vid(x, y, z_top) for x, y in c]; b = [vid(x, y, z_top - ep) for x, y in c]
        area = (c[1][0] - c[0][0]) * (c[2][1] - c[0][1]) - (c[2][0] - c[0][0]) * (c[1][1] - c[0][1])
        if area < 0: a, b = a[::-1], b[::-1]
        F.append(a); MI.append(0); F.append(b[::-1]); MI.append(1)
    for ring in [P.exterior] + list(P.interiors):
        cs = list(ring.coords)[:-1]
        ccw = ring.is_ccw
        for i in range(len(cs)):
            p, q = cs[i], cs[(i + 1) % len(cs)]
            if ring is not P.exterior: ccw_ok = not ccw
            else: ccw_ok = ccw
            if not ccw_ok: p, q = q, p
            F.append([vid(p[0], p[1], z_top - ep), vid(q[0], q[1], z_top - ep), vid(q[0], q[1], z_top), vid(p[0], p[1], z_top)]); MI.append(2)
    return mesh_obj(name, V, F, [m_top, m_bot, m_side], MI, coll_, bevel=0.004)

M_PLAF = mat("plafond"); M_SOUB = mat("soubassement")
for d in D["dalles"]:
    lv = LV[d["niveau"]]; top = d.get("altitude", lv["altitude"]); ep = d.get("epaisseur", 0.2)
    bot = M_PLAF if (d["niveau"] != "RDC" and "altitude" not in d) else (mat("balcon") if d.get("balcon") else M_SOUB)
    slab(d["contour"], d.get("tremies"), top, ep, mat(d["materiau"]), bot, M_SOUB if not d.get("balcon") else mat("balcon"),
         d.get("nom") or f"Plancher {d['niveau']}", C_LEVEL[d["niveau"]])
# plancher du comble (plafond de l'étage)
slab([[-0.2, -0.2], [11.4, -0.2], [11.4, 7.0], [-0.2, 7.0]], None, BASE + 0.22, 0.22, M_SOUB, M_PLAF, mat("mur_r1"), "Plancher de comble", C_R1)

# ----------------------------------------------------------------- escalier
for s in D["escaliers"]:
    n_ = s["marches"]; r = A1 / n_; g = s["giron"]; wdt = s["largeur"]; x, y = s["depart"]
    mb = MB()
    for i in range(n_):
        xa = x - (i + 1) * g; xb = x - i * g
        mb.box(xa, xb + (0.03 if i else 0), y - wdt / 2, y + wdt / 2, (i * r) if i else 0, (i + 1) * r, 0)
    mb.obj("Escalier droit 16 marches", [mat(s["materiau"])], C_RDC, bevel=0.006)
    cylinder("Main courante escalier", (x, y - wdt / 2 + 0.05, 0.95), (x - n_ * g, y - wdt / 2 + 0.05, A1 + 0.95), 0.022, mat("chene"), C_RDC)
    for k in range(0, n_ + 1, 4):
        xx = x - k * g; cylinder(f"Poteau rampe {k}", (xx, y - wdt / 2 + 0.05, k * r), (xx, y - wdt / 2 + 0.05, k * r + 0.95), 0.015, M_MENU, C_RDC, 8)

# ----------------------------------------------------------------- toiture
R = D["toiture"]
ext1 = [w for w in by_lvl["R+1"] if not w.get("interieur")]
tmax = max(w["epaisseur"] for w in ext1)
bx0, bx1, by0, by1 = -tmax / 2, 11.2 + tmax / 2, -tmax / 2, 6.8 + tmax / 2
P_ = math.radians(R["pente"]); tp = math.tan(P_); deb = R["debord"]; dp = R["debord_pignon"]; ep = R["epaisseur"]
zb = BASE + 0.22; half = (bx1 - bx0) / 2; mid = (bx0 + bx1) / 2; rise = half * tp; zr = zb + rise
ev = ep / math.cos(P_); y0r, y1r = by0 - dp, by1 + dp
M_ZINC = mat("zinc"); M_SOFF = mat("balcon")
for s in (-1, 1):
    xe = mid + s * (half + deb); ze = zb - deb * tp
    sec = [(xe, ze), (mid, zr), (mid, zr + ev), (xe, ze + ev)]
    V = [(x, y0r, z) for x, z in sec] + [(x, y1r, z) for x, z in sec]
    # faces : dessous (0-1), faîtage (1-2), dessus (2-3), égout (3-0), pignons
    F = [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7), (0, 3, 2, 1), (4, 5, 6, 7)]
    if s < 0: F = [f[::-1] for f in F]
    mesh_obj(f"Pan de toiture {'ouest' if s < 0 else 'est'} (zinc joints debout)", V, F, [M_ZINC, M_SOFF], [1, 0, 0, 0, 0, 0], C_TOIT, bevel=0.01)
    # barres à neige
    for frac in (0.12, 0.32):
        xs_ = xe + (mid - xe) * frac; zs_ = ze + ev + (zr - ze) * frac + 0.08
        cylinder(f"Barre à neige {s}{frac}", (xs_, y0r + 0.3, zs_), (xs_, y1r - 0.3, zs_), 0.022, mat_simple("acier galva", (0.55, 0.56, 0.57, 1), 0.35, 0.9), C_TOIT, 10)
    # gouttière
    cylinder(f"Gouttière {'ouest' if s < 0 else 'est'}", (xe + s * 0.06, y0r, ze - 0.02), (xe + s * 0.06, y1r, ze - 0.02), 0.075, M_ZINC, C_TOIT, 18)
cylinder("Faîtière", (mid, y0r - 0.02, zr + ev - 0.02), (mid, y1r + 0.02, zr + ev - 0.02), 0.07, M_ZINC, C_TOIT, 16)
# pignons
M_PIGNON = mat("mur_r1")
for yc_, nom in ((0.0, "sud"), (6.8, "nord")):
    tri = [(bx0, zb - 0.22), (bx1, zb - 0.22), (bx1, zb), (mid, zr), (bx0, zb)]
    n5 = len(tri)
    V = [(x, yc_ - tmax / 2, z) for x, z in tri] + [(x, yc_ + tmax / 2, z) for x, z in tri]
    F = [list(range(n5)), list(range(n5, 2 * n5))[::-1]] + [[i, (i + 1) % n5, n5 + (i + 1) % n5, n5 + i] for i in range(n5)]
    F[0] = F[0][::-1]; F[1] = F[1][::-1]
    mesh_obj(f"Pignon {nom}", V, F, [M_PIGNON], None, C_TOIT, bevel=0.005)
# planches de rive + lambrequins + ferme décorative
M_LAMB = mat("lambrequin")
for yfront, sgn in ((y0r, -1), (y1r, 1)):
    for s in (-1, 1):
        xe = mid + s * (half + deb); ze = zb - deb * tp
        p0 = Vector((xe, yfront, ze)); p1 = Vector((mid, yfront, zr))
        d = (p1 - p0); Lr = d.length; dn = d.normalized()
        down = Vector((0, 0, -1)) - dn * Vector((0, 0, -1)).dot(dn); down.normalize()
        # planche de rive (bandeau 25 cm)
        hb = 0.26 if TRAD else 0.30
        pts = [p0, p1, p1 + down * hb, p0 + down * hb]
        if TRAD:
            # bord inférieur festonné : dents arrondies tous les 15 cm
            n_ = int(Lr / 0.15); pts = [p0, p1]
            for k in range(n_, -1, -1):
                u = k / n_ * Lr
                for a in np.linspace(0, math.pi, 7):
                    uu = u - 0.075 + 0.075 * (1 - math.cos(a)) if k > 0 else u
                    hh = hb + 0.07 * math.sin(a)
                    q = p0 + dn * min(max(uu, 0), Lr) + down * hh
                    pts.append(q)
            mat_ = M_LAMB
        else:
            mat_ = M_ZINC
        V = [tuple(p) for p in pts] + [tuple(p + Vector((0, sgn * 0.03, 0))) for p in pts]
        n_ = len(pts)
        F = [list(range(n_))[::-sgn], list(range(n_, 2 * n_))[::sgn]] + [[i, (i + 1) % n_, n_ + (i + 1) % n_, n_ + i] for i in range(n_)]
        mesh_obj(f"{'Lambrequin' if TRAD else 'Rive zinc'} pignon {'sud' if sgn < 0 else 'nord'} {s}", V, F, [mat_], None, C_DECOR)
if TRAD:
    for yc_, sg in ((0.0 - tmax / 2 - 0.04, -1), (6.8 + tmax / 2 + 0.04, 1)):
        mb = MB()
        ztie = zb + rise * 0.30
        xt = (zr - ztie) / tp
        mb.box(mid - xt, mid + xt, yc_ - 0.04, yc_ + 0.04, ztie - 0.09, ztie + 0.09, 0)           # entrait
        mb.box(mid - 0.07, mid + 0.07, yc_ - 0.045, yc_ + 0.045, ztie, zr - 0.05, 0)               # poinçon
        for s in (-1, 1):                                                                         # contrefiches
            mb.beam((mid, yc_, ztie + 0.35), (mid + s * xt * 0.62, yc_, ztie + 0.35 + xt * 0.62 * tp * 0.98), 0.07, 0.11, 0, up=(0, 1, 0))
            mb.beam((mid + s * xt * 0.5, yc_, ztie), (mid + s * xt * 0.5, yc_, ztie + (xt * 0.5) * tp), 0.06, 0.08, 0, up=(0, 1, 0))
        mb.obj(f"Ferme décorative pignon {'sud' if sg < 0 else 'nord'}", [M_LAMB], C_DECOR, bevel=0.005)
        # œil-de-bœuf
        zo = ztie + 0.7
        cylinder(f"Œil-de-bœuf {'sud' if sg < 0 else 'nord'} (cadre)", (mid, yc_ - 0.05 * sg, zo), (mid, yc_ + 0.06 * sg, zo), 0.36, M_LAMB, C_DECOR, 32)
        cylinder(f"Œil-de-bœuf {'sud' if sg < 0 else 'nord'} (vitre)", (mid, yc_ - 0.07 * sg, zo), (mid, yc_ + 0.065 * sg, zo), 0.28, mat_simple("vitre sombre", (0.02, 0.03, 0.04, 1), 0.05, 0.0), C_DECOR, 32)
    # bandeau entre RDC et étage
    mb = MB()
    mb.box(-0.24, 11.44, -0.24, -0.2, A1 - 0.25, A1 - 0.05, 0); mb.box(-0.24, 11.44, 7.0, 7.04, A1 - 0.25, A1 - 0.05, 0)
    mb.box(-0.24, -0.2, -0.24, 7.04, A1 - 0.25, A1 - 0.05, 0); mb.box(11.4, 11.44, -0.24, 7.04, A1 - 0.25, A1 - 0.05, 0)
    for xx in (-0.24, 11.24):
        for yy in (-0.24, 6.84): mb.box(xx, xx + 0.2, yy, yy + 0.2 if yy > 0 else yy + 0.04, A1, BASE + 0.2, 0)
    mb.obj("Bandeau et planches d'angle", [M_LAMB], C_DECOR, bevel=0.004)
# soubassement en pierre (hauteur 40 cm) sur la variante traditionnelle
if TRAD:
    mb = MB(); hs = 0.45
    mb.box(-0.23, 11.43, -0.23, -0.2, -0.3, hs, 0); mb.box(-0.23, 11.43, 7.0, 7.03, -0.3, hs, 0)
    mb.box(-0.23, -0.2, -0.23, 7.03, -0.3, hs, 0); mb.box(11.4, 11.43, -0.23, 7.03, -0.3, hs, 0)
    mb.obj("Soubassement pierre", [mat_pierre("pierre_soubassement", {"type": "pierre", "couleur": "#8d8a84", "echelle": 0.7})], C_DECOR)

# conduit de cheminée (poêle à bois)
chx, chy = 4.9, 1.6
zroof = zb + (chx - bx0) * tp
mb = MB(); mb.box(chx - 0.3, chx + 0.3, chy - 0.3, chy + 0.3, BASE, zr + 0.9, 0)
mb.box(chx - 0.38, chx + 0.38, chy - 0.38, chy + 0.38, zr + 0.9, zr + 0.98, 1)
mb.obj("Souche de cheminée", [mat("mur_rdc") if TRAD else mat_simple("acier noir", (0.03, 0.03, 0.03, 1), 0.5, 0.6), M_ZINC], C_TOIT, bevel=0.01)

# ----------------------------------------------------------------- balcon : garde-corps et consoles
bal = [d for d in D["dalles"] if d.get("balcon")][0]
bxs = [p[0] for p in bal["contour"]]; bys = [p[1] for p in bal["contour"]]
xa, xb_, ya = min(bxs), max(bxs), min(bys); zt = bal["altitude"]
M_BAL = mat("balcon")
mb = MB()
segs = [("x", xa, xb_, ya + 0.04), ("y", ya, -0.2, xa + 0.04), ("y", ya, -0.2, xb_ - 0.04)]
for axis_, a, b, c in segs:
    if axis_ == "x": mb.box(a, b, c - 0.04, c + 0.04, zt + 0.95, zt + 1.02, 0); mb.box(a, b, c - 0.03, c + 0.03, zt + 0.08, zt + 0.14, 0)
    else: mb.box(c - 0.04, c + 0.04, a, b, zt + 0.95, zt + 1.02, 0); mb.box(c - 0.03, c + 0.03, a, b, zt + 0.08, zt + 0.14, 0)
    Ls = b - a
    if TRAD:
        n_ = int(Ls / 0.14)
        for k in range(n_):
            u = a + (k + 0.5) * Ls / n_
            if axis_ == "x": mb.box(u - 0.05, u + 0.05, c - 0.012, c + 0.012, zt + 0.14, zt + 0.95, 0)
            else: mb.box(c - 0.012, c + 0.012, u - 0.05, u + 0.05, zt + 0.14, zt + 0.95, 0)
    else:
        n_ = max(2, int(Ls / 1.4))
        for k in range(n_ + 1):
            u = a + k * Ls / n_
            if axis_ == "x": mb.box(u - 0.02, u + 0.02, c - 0.02, c + 0.02, zt, zt + 0.95, 1)
            else: mb.box(c - 0.02, c + 0.02, u - 0.02, u + 0.02, zt, zt + 0.95, 1)
mb.obj("Garde-corps balcon", [M_BAL, M_MENU], C_R1, bevel=0.003)
if not TRAD:
    gl = MB()
    gl.box(xa + 0.05, xb_ - 0.05, ya + 0.03, ya + 0.05, zt + 0.15, zt + 0.93, 0)
    gl.box(xa + 0.03, xa + 0.05, ya + 0.05, -0.22, zt + 0.15, zt + 0.93, 0); gl.box(xb_ - 0.05, xb_ - 0.03, ya + 0.05, -0.22, zt + 0.15, zt + 0.93, 0)
    gl.obj("Garde-corps balcon — verre", [M_VERRE], C_R1)
# consoles / poteaux
mb = MB()
for xp in (0.2, 3.9, 7.3, 11.0):
    if TRAD:   # jambes de force bois
        mb.beam((xp, -0.26, 1.6), (xp, ya + 0.35, zt - 0.22), 0.12, 0.12, 0, up=(1, 0, 0))
        mb.box(xp - 0.07, xp + 0.07, ya, -0.2, zt - 0.4, zt - 0.2, 0)
    else:
        mb.box(xp - 0.05, xp + 0.05, ya + 0.1, ya + 0.2, -0.1, zt - 0.2, 1)
mb.obj("Consoles du balcon", [M_BAL, M_MENU], C_R1, bevel=0.004)

# ----------------------------------------------------------------- mobilier
M_TISSU = mat("tissu"); M_LINGE = mat("linge"); M_ACIER = mat_simple("acier noir mat", (0.02, 0.02, 0.02, 1), 0.45, 0.7)
for f in D["mobilier"]:
    lv = LV[f["niveau"]]; W, Dp, H = f["dimensions"]; rot = -math.radians(f.get("rotation", 0))
    m0 = M_ACIER if "Poêle" in f.get("nom", "") else mat(f["materiau"]); mb = MB()
    t_ = f["type"]
    if t_ == "lit":
        mb.box(-W / 2, W / 2, -Dp / 2, Dp / 2, 0, 0.3, 0); mb.box(-W / 2 + .02, W / 2 - .02, -Dp / 2 + .03, Dp / 2 - .03, 0.3, 0.52, 1)
        mb.box(-W / 2, W / 2, Dp / 2 - 0.08, Dp / 2, 0, 1.0, 0)
        for sx in (-1, 1): mb.box(sx * W * .22 - W * .19, sx * W * .22 + W * .19, Dp / 2 - .5, Dp / 2 - .12, 0.52, 0.64, 1)
        mb.box(-W / 2 + .01, W / 2 - .01, -Dp / 2 + .02, Dp * .15, 0.52, 0.56, 2)
        mats_ = [m0, M_LINGE, M_TISSU]
    elif t_ == "canape":
        mb.box(-W / 2, W / 2, -Dp / 2, Dp / 2, 0.05, 0.43, 0); mb.box(-W / 2, W / 2, Dp / 2 - 0.22, Dp / 2, 0.43, 0.82, 0)
        for sx in (-1, 1): mb.box(sx * W / 2 - (0.18 if sx > 0 else 0), sx * W / 2 + (0.18 if sx < 0 else 0), -Dp / 2, Dp / 2, 0.05, 0.62, 0)
        mats_ = [m0]
    elif t_ == "table":
        mb.box(-W / 2, W / 2, -Dp / 2, Dp / 2, H - 0.045, H, 0)
        for sx in (-1, 1):
            for sy in (-1, 1): mb.box(sx * (W / 2 - .1) - .035, sx * (W / 2 - .1) + .035, sy * (Dp / 2 - .1) - .035, sy * (Dp / 2 - .1) + .035, 0, H - .045, 1)
        mats_ = [m0, M_MENU]
    else:
        mb.box(-W / 2, W / 2, -Dp / 2, Dp / 2, 0, H, 0); mats_ = [m0]
    ob = mb.obj(f.get("nom") or {"lit": "Lit", "canape": "Canapé", "table": "Table"}.get(t_, "Meuble"), mats_, C_MOB, bevel=0.012)
    place(ob, (f["position"][0], f["position"][1], lv["altitude"]), -rot if False else rot)
    if f.get("rotation", 0) == 180: ob.rotation_euler[2] = math.pi
# tapis + suspensions + poêle (conduit)
mb = MB(); mb.box(0.8, 4.0, 1.0, 3.6, 0.0, 0.012, 0); mb.obj("Tapis", [mat_simple("laine", (0.42, 0.36, 0.3, 1), 1.0, 0, 0.5)], C_MOB)
cylinder("Conduit du poêle", (5.2, 1.0, 1.1), (5.2, 1.0, A1 - 0.25), 0.08, M_ACIER, C_MOB)
lamp_m = bpy.data.materials.new("abat-jour émissif")
try: lamp_m.use_nodes = True
except Exception: pass
em = lamp_m.node_tree.nodes.get("Principled BSDF")
em.inputs["Base Color"].default_value = (0.9, 0.8, 0.6, 1); em.inputs["Emission Color"].default_value = (1.0, 0.75, 0.45, 1); em.inputs["Emission Strength"].default_value = 6.0
for (lx, ly) in ((5.0, 3.6), (6.2, 3.6), (2.4, 4.9)):
    cylinder("Câble suspension", (lx, ly, A1 - 0.25), (lx, ly, 1.75), 0.004, M_MENU, C_MOB, 6)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.13, location=(lx, ly, 1.68)); sph = bpy.context.active_object
    sph.name = "Suspension"; sph.data.materials.append(lamp_m)
    for c in sph.users_collection: c.objects.unlink(sph)
    C_MOB.objects.link(sph)
    for p in sph.data.polygons: p.use_smooth = True

# ----------------------------------------------------------------- terrain et montagnes
def vnoise(x, y, seed):
    xi = np.floor(x).astype(np.int64); yi = np.floor(y).astype(np.int64)
    xf = x - xi; yf = y - yi
    def h(i, j):
        n = (i * 374761393 + j * 668265263 + seed * 144269504) & 0xFFFFFFFF
        n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
        return ((n ^ (n >> 16)) & 0xFFFF) / 65535.0
    u = xf * xf * xf * (xf * (xf * 6 - 15) + 10); v = yf * yf * yf * (yf * (yf * 6 - 15) + 10)
    return (h(xi, yi) * (1 - u) + h(xi + 1, yi) * u) * (1 - v) + (h(xi, yi + 1) * (1 - u) + h(xi + 1, yi + 1) * u) * v

def fbm(x, y, oct_=6, seed=1):
    a, f, s, t = 1.0, 1.0, 0.0, 0.0
    for o in range(oct_):
        s += a * vnoise(x * f, y * f, seed + o); t += a; a *= 0.5; f *= 2.03
    return s / t

def ridged(x, y, oct_=7, seed=11):
    a, f, s, t, w = 1.0, 1.0, 0.0, 0.0, 1.0
    for o in range(oct_):
        n = 1 - abs(2 * vnoise(x * f, y * f, seed + o) - 1); n = n * n * w
        w = np.clip(n * 1.6, 0, 1)
        s += a * n; t += a; a *= 0.5; f *= 2.1
    return s / t

def smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1); return t * t * (3 - 2 * t)

def height(x, y):
    dx, dy = x - CX, y - CY
    r = np.sqrt(dx * dx + dy * dy)
    slope = 70 * np.tanh(dy / 900.0)                              # le terrain monte vers le nord, descend vers la vallée au sud
    hills = (fbm(x / 260, y / 260, 6, 3) - 0.5) * 90 * smooth(30, 300, r) + (fbm(x / 70, y / 70, 4, 5) - 0.5) * 8 * smooth(25, 90, r)
    ry = np.where(dy < 0, dy / 1.9, dy)                            # vallée plus large au sud
    re = np.sqrt(dx * dx + ry * ry)
    mount = ridged(x / 2600 + 3.1, y / 2600 + 1.7) ** 1.6 * 2200 * smooth(700, 3400, re)
    near = (fbm(x / 40, y / 40, 4, 9) - 0.5) * 1.2
    h = slope + hills + mount + near * smooth(18, 60, r)
    plat = -0.15 + 0.012 * dy
    return np.where(r < 60, plat + (h - plat) * smooth(13, 45, r), h)

def grid_mesh(name, xs, ys, coll_, hole=None):
    X, Y = np.meshgrid(xs, ys); Z = height(X, Y)
    nx, ny = len(xs), len(ys)
    V = np.stack([X, Y, Z], -1).reshape(-1, 3)
    F = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            if hole is not None:
                cxm, cym = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
                if abs(cxm - CX) < hole and abs(cym - CY) < hole: continue
            a = j * nx + i; F.append((a, a + 1, a + nx + 1, a + nx))
    me = bpy.data.meshes.new(name); me.from_pydata(V.tolist(), [], F); me.update()
    for p in me.polygons: p.use_smooth = True
    ob = bpy.data.objects.new(name, me); coll_.objects.link(ob)
    return ob, X, Y, Z

def mat_terrain():
    m, nt, b, out = new_mat("Terrain alpin (prairie, roche, neige)"); n = N(nt)
    g, sep = n.pos()
    z = sep.outputs[2]
    sepn = n.n("ShaderNodeSeparateXYZ"); n.l(g.outputs["Normal"], sepn.inputs[0]); nz_ = sepn.outputs[2]
    noise = n.n("ShaderNodeTexNoise", i_Scale=0.02, i_Detail=8); n.l(g.outputs["Position"], noise.inputs["Vector"])
    fine = n.n("ShaderNodeTexNoise", i_Scale=1.5, i_Detail=10); n.l(g.outputs["Position"], fine.inputs["Vector"])
    patch = n.n("ShaderNodeTexNoise", i_Scale=0.004, i_Detail=4); n.l(g.outputs["Position"], patch.inputs["Vector"])
    grass = n.mix(fine.outputs["Fac"], (0.045, 0.10, 0.012, 1), (0.16, 0.20, 0.035, 1))
    grass = n.mix(n.math("MULTIPLY", noise.outputs["Fac"], None, vb=0.45), grass, (0.22, 0.19, 0.07, 1))
    forest = n.mix(fine.outputs["Fac"], (0.012, 0.03, 0.012, 1), (0.03, 0.06, 0.025, 1))
    fmask = n.math("MULTIPLY", n.math("GREATER_THAN", patch.outputs["Fac"], None, vb=0.5),
                   n.math("LESS_THAN", z, None, vb=650))
    fmask = n.math("MULTIPLY", fmask, n.math("GREATER_THAN", sep.outputs[1], None, vb=300.0))  # forêts lointaines (pas au premier plan)
    c = n.mix(fmask, grass, forest)
    rock = n.mix(fine.outputs["Fac"], (0.09, 0.085, 0.08, 1), (0.24, 0.22, 0.2, 1))
    steep = n.math("SUBTRACT", None, nz_, va=1.0)
    rmask = n.math("ADD", n.math("MULTIPLY", n.math("GREATER_THAN", steep, None, vb=0.28), None, vb=1.0),
                   n.math("GREATER_THAN", z, None, vb=1100))
    c = n.mix(n.math("MINIMUM", rmask, None, vb=1.0), c, rock)
    snowline = n.math("ADD", n.math("MULTIPLY", noise.outputs["Fac"], None, vb=600), None, vb=1350)
    smask = n.math("MULTIPLY", n.math("GREATER_THAN", z, snowline), n.math("GREATER_THAN", nz_, None, vb=0.55))
    c = n.mix(smask, c, (0.85, 0.88, 0.92, 1))
    # perspective atmosphérique
    cam = n.n("ShaderNodeCameraData")
    haze = n.n("ShaderNodeMapRange", i_From__Min=600.0, i_From__Max=16000.0, i_To__Min=0.0, i_To__Max=0.6)
    n.l(cam.outputs["View Distance"], haze.inputs[0])
    n.l(c, b.inputs["Base Color"]); b.inputs["Roughness"].default_value = 0.95
    n.bump(b, fine.outputs["Fac"], 0.6, 0.08)
    em = n.n("ShaderNodeEmission", i_Strength=1.0); em.inputs["Color"].default_value = (0.42, 0.55, 0.75, 1)
    mx = n.n("ShaderNodeMixShader"); n.l(haze.outputs[0], mx.inputs[0]); n.l(b.outputs[0], mx.inputs[1]); n.l(em.outputs[0], mx.inputs[2])
    n.l(mx.outputs[0], out.inputs[0])
    return m

M_TER = mat_terrain()
near_xs = np.linspace(CX - 600, CX + 600, 241); near_ys = np.linspace(CY - 600, CY + 600, 241)
near, NX, NY, NZ = grid_mesh("Terrain proche (1,2 km)", near_xs, near_ys, C_TER)
near.data.materials.append(M_TER)
u = np.linspace(-1, 1, 461); far_c = np.sign(u) * np.abs(u) ** 1.9 * 16000
far, *_ = grid_mesh("Montagnes (14 km)", far_c + CX, far_c + CY, C_TER, hole=598)
far.data.materials.append(M_TER)
# petite zone fine autour de la maison (herbe rase) : subdivision locale
fine_xs = np.linspace(CX - 40, CX + 40, 161); fine_ys = np.linspace(CY - 40, CY + 40, 161)

# ----------------------------------------------------------------- végétation : sapins (instances) et rochers
def make_pine(name, h, seed):
    """Épicéa : tronc + ~150 rameaux tombants ; modélisé le long de +X (axe des particules), hauteur 1."""
    r_ = np.random.default_rng(seed)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=7, radius1=0.022, radius2=0.004, depth=1.0, matrix=Matrix.Translation((0, 0, 0.5)))
    for f in bm.faces: f.material_index = 0
    tiers = 24
    for k in range(tiers):
        z = 0.1 + 0.86 * k / tiers + r_.normal() * 0.006
        Lb = 0.30 * (1 - z) ** 0.85 + 0.03
        nb = 7 if k < tiers - 4 else 5
        for j in range(nb):
            az = 2 * math.pi * (j + r_.random() * 0.5) / nb + k * 0.7
            droop = math.radians(-18 - 22 * r_.random())
            d = Vector((math.cos(az) * math.cos(droop), math.sin(az) * math.cos(droop), math.sin(droop)))
            q = Vector((0, 0, 1)).rotation_difference(d)
            M = Matrix.Translation((0, 0, z)) @ q.to_matrix().to_4x4() @ Matrix.Translation((0, 0, Lb * 0.5))
            new = bmesh.ops.create_cone(bm, cap_ends=False, segments=6, radius1=Lb * (0.30 + 0.1 * r_.random()), radius2=Lb * 0.06, depth=Lb, matrix=M)
            for v in new["verts"]:
                v.co.z -= 0.25 * Lb * ((v.co.xy.length) ** 1.0)  # rameaux qui retombent
            for f in {f for v in new["verts"] for f in v.link_faces}: f.material_index = 1
    bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(90), 3, "Y"))   # Z → X
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    m1 = bpy.data.materials.get("Écorce") or mat_simple("Écorce", (0.07, 0.045, 0.03, 1), 0.9)
    m2 = bpy.data.materials.get("Aiguilles de sapin")
    if not m2:
        m2, nt, b, _ = new_mat("Aiguilles de sapin"); n = N(nt)
        g, sep = n.pos()
        nz = n.n("ShaderNodeTexNoise", i_Scale=14, i_Detail=12, i_Roughness=0.75); n.l(g.outputs["Position"], nz.inputs["Vector"])
        oi = n.n("ShaderNodeObjectInfo")
        c = n.mix(nz.outputs["Fac"], (0.006, 0.022, 0.009, 1), (0.035, 0.07, 0.022, 1))
        c = n.mix(n.math("MULTIPLY", oi.outputs["Random"], None, vb=0.6), c, (0.045, 0.055, 0.02, 1))
        n.l(c, b.inputs["Base Color"]); b.inputs["Roughness"].default_value = 0.8
        try: b.inputs["Subsurface Weight"].default_value = 0.08
        except Exception: pass
        n.bump(b, nz.outputs["Fac"], 1.0, 0.05)
    me.materials.append(m1); me.materials.append(m2)
    for p in me.polygons: p.use_smooth = True
    ob = bpy.data.objects.new(name, me); C_LIB.objects.link(ob)
    return ob

pines = [make_pine(f"Sapin type {k}", 1.0, 100 + k) for k in range(3)]
for p_ in pines: p_.location = (0, 0, -500)
# groupe de densité de forêt sur le terrain proche
dist = np.sqrt((NX - CX) ** 2 + (NY - CY) ** 2)
forest = fbm(NX / 140 + 5, NY / 140 + 2, 4, 21)
w_ = np.clip((forest - 0.48) * 6, 0, 1) * smooth(28, 70, dist)
# dégager la vue au sud (vallée) devant la façade principale
view = np.where((NY < CY - 10) & (np.abs(NX - CX) < (CY - NY) * 0.9), 0.15, 1.0)
w_ = w_ * view
vg = near.vertex_groups.new(name="densité forêt")
for i, val in enumerate(w_.ravel()):
    if val > 0.01: vg.add([i], float(val), "REPLACE")
psm = near.modifiers.new("Forêt de sapins", "PARTICLE_SYSTEM")
ps = psm.particle_system; s_ = ps.settings
s_.type = "HAIR"; s_.count = 900 if PREVIEW else 9000; s_.emit_from = "FACE"; s_.distribution = "RAND"; s_.use_advanced_hair = True
s_.render_type = "COLLECTION"
cpine = coll("Sapins", C_LIB)
for p_ in pines:
    C_LIB.objects.unlink(p_); cpine.objects.link(p_); p_.location = (0, 0, 0)
s_.instance_collection = cpine; s_.use_collection_pick_random = True
s_.particle_size = 14.0; s_.size_random = 0.6
s_.use_rotations = False
s_.hair_length = 1.0
ps.vertex_group_density = "densité forêt"; ps.seed = 3
def layer_coll(lc, name):
    if lc.collection.name == name: return lc
    for ch in lc.children:
        r_ = layer_coll(ch, name)
        if r_: return r_
layer_coll(bpy.context.view_layer.layer_collection, C_LIB.name).exclude = True   # modèles source exclus, instances rendues
# pelouse alpine en brins (rayon ~45 m)
gx = np.linspace(CX - 45, CX + 45, 181); gy = np.linspace(CY - 45, CY + 45, 181)
pel, GX, GY, GZ = grid_mesh("Prairie (brins d'herbe)", gx, gy, C_VEG)
pel.location.z = 0.005
pel.data.materials.append(M_TER)
gd = np.sqrt((GX - CX) ** 2 + (GY - CY) ** 2)
inside = (GX > -1.2) & (GX < 12.4) & (GY > -3.5) & (GY < 8.5)
gw = np.where(inside, 0.0, 1.0) * (1 - smooth(32, 45, gd))
vg2 = pel.vertex_groups.new(name="densité herbe")
for i, val in enumerate(gw.ravel()):
    if val > 0.01: vg2.add([i], float(val), "REPLACE")
# touffe d'herbe modélisée (brins triangulaires), le long de +X comme les sapins
def make_tuft(name, seed):
    r_ = np.random.default_rng(seed); V, F = [], []
    for k in range(14):
        a_ = r_.random() * 6.28; lean = 0.15 + r_.random() * 0.35; hgt = 0.6 + r_.random() * 0.5; w = 0.025
        bx, by = r_.normal() * 0.06, r_.normal() * 0.06
        ca, sa = math.cos(a_), math.sin(a_)
        o = len(V)
        V += [(bx - sa * w, by + ca * w, 0), (bx + sa * w, by - ca * w, 0), (bx + ca * lean, by + sa * lean, hgt)]
        F.append((o, o + 1, o + 2))
    V = [(z, y, -x) for x, y, z in V]  # Z → X
    me = bpy.data.meshes.new(name); me.from_pydata(V, [], F); me.update()
    gm = bpy.data.materials.get("Herbe (brins)")
    if not gm:
        gm, gnt, gb, _ = new_mat("Herbe (brins)"); gnn = N(gnt)
        g_, sep_ = gnn.n("ShaderNodeNewGeometry"), None
        oi = gnn.n("ShaderNodeObjectInfo")
        cc = gnn.mix(oi.outputs["Random"], (0.03, 0.075, 0.01, 1), (0.17, 0.21, 0.04, 1))
        gnn.l(cc, gb.inputs["Base Color"]); gb.inputs["Roughness"].default_value = 0.7
        try: gb.inputs["Subsurface Weight"].default_value = 0.15
        except Exception: pass
    me.materials.append(gm)
    ob = bpy.data.objects.new(name, me); C_LIB.objects.link(ob); return ob
ctuft = coll("Touffes d'herbe", C_LIB)
for k in range(4):
    t_ = make_tuft(f"Touffe {k}", 300 + k); C_LIB.objects.unlink(t_); ctuft.objects.link(t_)
pm = pel.modifiers.new("Herbe", "PARTICLE_SYSTEM"); gs = pm.particle_system.settings
gs.type = "HAIR"; gs.count = 6000 if PREVIEW else 90000; gs.hair_length = 1.0; gs.emit_from = "FACE"; gs.distribution = "RAND"
gs.render_type = "COLLECTION"; gs.instance_collection = ctuft; gs.use_collection_pick_random = True
gs.particle_size = 0.32; gs.size_random = 0.7; gs.use_rotations = False
pm.particle_system.vertex_group_density = "densité herbe"; pm.particle_system.seed = 5
# arbres isolés près de la maison (composition)
for k, (x_, y_, hh) in enumerate(((-16, 9, 15), (-19, 14, 18), (-12, 18, 13), (27, 15, 16), (31, 9, 19), (24, 22, 14), (-22, -4, 12), (33, -2, 13), (16, 26, 17), (-5, 26, 15))):
    inst = bpy.data.objects.new(f"Sapin isolé {k}", None); inst.instance_type = "COLLECTION"; inst.instance_collection = cpine
    z_ = float(height(np.array([x_ + CX]), np.array([y_ + CY]))[0]); inst.location = (x_ + CX, y_ + CY, z_ - 0.2)
    inst.scale = (hh,) * 3; inst.rotation_euler = (0, math.radians(-90), 0); inst.rotation_mode = "XYZ"
    inst.rotation_euler = (rng.random() * 6.28, math.radians(-90), 0); C_VEG.objects.link(inst)
# rochers et tas de bois
M_ROCK = mat_simple("Roche", (0.24, 0.23, 0.22, 1), 0.9)
for k in range(14):
    a = rng.random() * 6.28; rr = 16 + rng.random() * 25
    x_, y_ = CX + math.cos(a) * rr, CY + math.sin(a) * rr
    if y_ < CY - 4 and abs(x_ - CX) < 14: continue
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.4 + rng.random() * 0.9, location=(x_, y_, float(height(np.array([x_]), np.array([y_]))[0])))
    ob = bpy.context.active_object; ob.name = f"Rocher {k}"; ob.scale = (1, 0.8 + rng.random() * 0.5, 0.55)
    dm = ob.modifiers.new("Relief", "DISPLACE"); tx = bpy.data.textures.new(f"roche{k}", "CLOUDS"); tx.noise_scale = 0.5; dm.texture = tx; dm.strength = 0.35
    ob.data.materials.append(M_ROCK)
    for c in ob.users_collection: c.objects.unlink(ob)
    C_VEG.objects.link(ob)
M_LOG = mat_simple("Bûches", (0.25, 0.15, 0.08, 1), 0.85)
for i in range(7):
    for j in range(5):
        cylinder(f"Bûche {i}-{j}", (11.45 + 0.02, 1.0 + i * 0.22 + (j % 2) * 0.11, 0.12 + j * 0.2), (11.45 + 0.42, 1.0 + i * 0.22 + (j % 2) * 0.11, 0.12 + j * 0.2), 0.1, M_LOG, C_DECOR, 10)

# ----------------------------------------------------------------- ciel, soleil, rendu
world = bpy.data.worlds.new("Ciel de montagne"); scene.world = world
try: world.use_nodes = True
except Exception: pass
wn = world.node_tree; wn.nodes.clear()
sky = wn.nodes.new("ShaderNodeTexSky")
for t_ in ("MULTIPLE_SCATTERING", "SINGLE_SCATTERING", "HOSEK_WILKIE"):
    try: sky.sky_type = t_; break
    except Exception: pass
SUN_EL, SUN_AZ = math.radians(24), math.radians(238)    # milieu d'après-midi, soleil sud-sud-ouest
try:
    sky.sun_disc = False; sky.sun_elevation = SUN_EL; sky.sun_rotation = math.radians(90) - SUN_AZ + math.pi; sky.altitude = 1400
except Exception: pass
bg = wn.nodes.new("ShaderNodeBackground"); bg.inputs["Strength"].default_value = 0.32
wo = wn.nodes.new("ShaderNodeOutputWorld")
wn.links.new(sky.outputs[0], bg.inputs[0]); wn.links.new(bg.outputs[0], wo.inputs[0])

sun_d = bpy.data.lights.new("Soleil", "SUN"); sun_d.energy = 4.2; sun_d.angle = math.radians(0.6); sun_d.color = (1.0, 0.94, 0.86)
sun = bpy.data.objects.new("Soleil", sun_d); C_CAM.objects.link(sun)
# direction : le soleil vient de l'azimut SUN_AZ (depuis le nord, sens horaire), hauteur SUN_EL
dirv = Vector((math.sin(SUN_AZ) * math.cos(SUN_EL), math.cos(SUN_AZ) * math.cos(SUN_EL), math.sin(SUN_EL)))
sun.rotation_mode = "QUATERNION"; sun.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(dirv)
# éclairage intérieur d'appoint
for (lx, ly, lz, e) in ((3.5, 3.5, 2.4, 60), (9.3, 5.5, 2.4, 25), (2.0, 2.0, A1 + 2.4, 30), (5.8, 2.0, A1 + 2.4, 30), (9.3, 2.0, A1 + 2.4, 30)):
    ld = bpy.data.lights.new("Plafonnier", "AREA"); ld.energy = e; ld.size = 1.2; ld.color = (1.0, 0.86, 0.7)
    lo = bpy.data.objects.new("Plafonnier", ld); lo.location = (lx, ly, lz); C_CAM.objects.link(lo)

def ground(x, y): return float(height(np.array([x]), np.array([y]))[0])

def camera(name, loc, target, lens):
    cd = bpy.data.cameras.new(name); cd.lens = lens; cd.clip_end = 30000; cd.clip_start = 0.05
    co = bpy.data.objects.new(name, cd); C_CAM.objects.link(co); co.location = loc
    d = Vector(target) - Vector(loc); co.rotation_mode = "QUATERNION"; co.rotation_quaternion = d.to_track_quat("-Z", "Y")
    # verticales droites (correction de perspective architecturale)
    cd.shift_y = 0.0
    return co

cams = {
    "sud": camera("Caméra façade sud", (-7.5, -15.5, ground(-7.5, -15.5) + 1.65), (6.2, 3.0, 3.6), 24),
    "nord": camera("Caméra entrée nord-est", (21.0, 17.5, ground(21.0, 17.5) + 1.65), (6.5, 4.5, 3.0), 26),
    "aerienne": camera("Caméra aérienne", (58.0, -70.0, ground(58, -70) + 30.0), (4.0, 12.0, 6.0), 30),
    "interieur": camera("Caméra séjour", (7.3, 5.2, 1.35), (1.2, 0.0, 1.25), 16),
}
for k, co in cams.items():
    if k != "aerienne" and k != "interieur":  # verticales parfaitement droites : caméra horizontale + décentrement
        loc = co.location; tgt = Vector((6.0, 3.4, 0)); d = Vector((tgt.x - loc.x, tgt.y - loc.y, 0))
        co.rotation_quaternion = d.to_track_quat("-Z", "Y"); co.data.shift_y = 0.12
cams["interieur"].rotation_quaternion = Vector((1.2 - 7.3, 0.0 - 5.2, 0)).to_track_quat("-Z", "Y"); cams["interieur"].data.shift_y = 0.03
scene.camera = cams["sud"]

r = scene.render; r.engine = "CYCLES"
scene.cycles.device = "CPU"
r.resolution_x, r.resolution_y = (960, 540) if PREVIEW else (1600, 900)
r.resolution_percentage = 100
scene.cycles.samples = 24 if PREVIEW else 160
scene.cycles.use_adaptive_sampling = True; scene.cycles.adaptive_threshold = 0.02
scene.cycles.use_denoising = True
try: scene.cycles.denoiser = "OPENIMAGEDENOISE"
except Exception: pass
scene.cycles.max_bounces = 6; scene.cycles.caustics_reflective = False; scene.cycles.caustics_refractive = False
scene.cycles.blur_glossy = 1.0
r.use_persistent_data = True
try: scene.view_settings.view_transform = "AgX"; scene.view_settings.look = "AgX - Medium High Contrast"
except Exception: pass
scene.view_settings.exposure = 0.0
r.image_settings.file_format = "JPEG"; r.image_settings.quality = 92

# ----------------------------------------------------------------- enregistrement + exports
blend = os.path.join(OUT, f"chalet_{VAR}.blend")
if not PREVIEW:
    bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True)
    # glb du bâtiment seul (modificateurs appliqués)
    for ob in bpy.context.view_layer.objects: ob.select_set(False)
    def sel(c):
        for ob in c.objects: ob.select_set(True)
        for ch in c.children: sel(ch)
    sel(C_BAT)
    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, f"chalet_{VAR}.glb"), export_format="GLB", use_selection=True, export_apply=True)
    print("blend + glb enregistrés")

if not NO_RENDER:
    for k in (CAMS or ["sud", "aerienne", "interieur", "nord"]):
        scene.camera = cams[k]
        if k == "interieur": scene.cycles.samples = 48 if PREVIEW else 110; scene.view_settings.exposure = 0.9
        else: scene.cycles.samples = 24 if PREVIEW else 96; scene.view_settings.exposure = 0.0
        r.filepath = os.path.join(OUT, f"rendu_{VAR}_{k}{'_apercu' if PREVIEW else ''}.jpg")
        t0 = time.time(); bpy.ops.render.render(write_still=True)
        print(f"rendu {k} : {time.time() - t0:.0f} s → {r.filepath}", flush=True)
