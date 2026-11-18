"""Export IFC4 du projet (ouvrable dans Revit, Archicad, Bonsai/Blender, FreeCAD).

Chaque élément est un objet IFC typé, rangé dans son niveau :
IfcWall (+ IfcOpeningElement, IfcWindow, IfcDoor), IfcSlab, IfcRoof/IfcSlab ROOF,
IfcStair, IfcRailing, IfcSpace (pièces avec surface), IfcFurniture.
"""
import json, math, os, sys
import numpy as np
import ifcopenshell
import ifcopenshell.api as api
from ifcopenshell.api import root, unit, context, project, spatial, aggregate, geometry, feature, material, style, pset
from shapely.geometry import Polygon


def hex_rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def mat4(origin, xdir, zdir=(0, 0, 1)):
    x = np.array(xdir, float); x /= np.linalg.norm(x)
    z = np.array(zdir, float); z /= np.linalg.norm(z)
    y = np.cross(z, x)
    m = np.eye(4); m[:3, 0] = x; m[:3, 1] = y; m[:3, 2] = z; m[:3, 3] = origin
    return m


def box_mesh(cx, cy, cz, sx, sy, sz, rot=0.0):
    """Boîte centrée en (cx,cy) avec base en cz, tournée de rot (rad) autour de z."""
    c, s = math.cos(rot), math.sin(rot)
    vs = []
    for dz in (0, sz):
        for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            x, y = dx * sx / 2, dy * sy / 2
            vs.append((cx + x * c - y * s, cy + x * s + y * c, cz + dz))
    f = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    return vs, f


def merge(meshes):
    V, Fs = [], []
    for v, f in meshes:
        o = len(V); V += v; Fs += [[i + o for i in face] for face in f]
    return V, Fs


def prism(poly2d, z0, z1):
    """Prisme vertical à partir d'un polygone (x,y)."""
    n = len(poly2d)
    V = [(x, y, z0) for x, y in poly2d] + [(x, y, z1) for x, y in poly2d]
    F = [list(range(n))[::-1], list(range(n, 2 * n))] + [[i, (i + 1) % n, n + (i + 1) % n, n + i] for i in range(n)]
    return V, F


class IFCWriter:
    def __init__(self, data):
        self.d = data
        self.m = project.create_file(version="IFC4")
        self.proj = root.create_entity(self.m, ifc_class="IfcProject", name=data["projet"]["nom"])
        unit.assign_unit(self.m, length={"is_metric": True, "raw": "METERS"}, area={"is_metric": True, "raw": "SQUARE_METERS"})
        model = context.add_context(self.m, context_type="Model")
        self.body = context.add_context(self.m, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model)
        self.site = root.create_entity(self.m, ifc_class="IfcSite", name="Terrain")
        self.bldg = root.create_entity(self.m, ifc_class="IfcBuilding", name="Chalet")
        aggregate.assign_object(self.m, products=[self.site], relating_object=self.proj)
        aggregate.assign_object(self.m, products=[self.bldg], relating_object=self.site)
        self.storeys = {}
        for lv in data["niveaux"]:
            st = root.create_entity(self.m, ifc_class="IfcBuildingStorey", name=lv["nom"])
            st.Elevation = lv["altitude"]
            geometry.edit_object_placement(self.m, product=st, matrix=mat4((0, 0, lv["altitude"]), (1, 0, 0)))
            aggregate.assign_object(self.m, products=[st], relating_object=self.bldg)
            self.storeys[lv["id"]] = st
        self.levels = {lv["id"]: lv for lv in data["niveaux"]}
        self._mats, self._styles = {}, {}
        self.count = {}

    # ---------- matériaux ----------
    def mat(self, key):
        if key in self._mats: return self._mats[key]
        d = self.d["materiaux"].get(key, {"type": "peinture", "couleur": "#cccccc"})
        nom = f"{key} ({d.get('type', '')})"
        m = material.add_material(self.m, name=nom, category=d.get("type"))
        st = style.add_style(self.m, name=key)
        rgb = hex_rgb(d.get("couleur", "#c2d8e0" if d.get("type") == "verre" else "#cccccc"))
        attrs = {"SurfaceColour": {"Name": None, "Red": rgb[0], "Green": rgb[1], "Blue": rgb[2]}, "ReflectanceMethod": "NOTDEFINED"}
        if d.get("type") == "verre": attrs["Transparency"] = 0.75
        style.add_surface_style(self.m, style=st, ifc_class="IfcSurfaceStyleRendering", attributes=attrs)
        style.assign_material_style(self.m, material=m, style=st, context=self.body)
        self._mats[key] = m; self._styles[key] = st
        return m

    def finish(self, el, rep, matkey, storey, placement=None):
        if placement is not None: geometry.edit_object_placement(self.m, product=el, matrix=placement)
        geometry.assign_representation(self.m, product=el, representation=rep)
        if matkey:
            material.assign_material(self.m, products=[el], material=self.mat(matkey))
            style.assign_representation_styles(self.m, shape_representation=rep, styles=[self._styles[matkey]])
        if storey is not None: spatial.assign_container(self.m, products=[el], relating_structure=storey)
        self.count[el.is_a()] = self.count.get(el.is_a(), 0) + 1
        return el

    def mesh_el(self, ifc_class, name, mesh, matkey, storey, predef=None):
        el = root.create_entity(self.m, ifc_class=ifc_class, name=name, predefined_type=predef)
        V, F = mesh
        rep = geometry.add_mesh_representation(self.m, context=self.body, vertices=[V], faces=[F])
        return self.finish(el, rep, matkey, storey, mat4((0, 0, 0), (1, 0, 0)))

    # ---------- murs ----------
    def walls(self):
        murs = self.d["murs"]
        by = {}
        for w in murs: by.setdefault(w["niveau"], []).append(w)
        same = lambda p, q: math.hypot(p[0] - q[0], p[1] - q[1]) < 0.02
        for niv, ws in by.items():
            ext = [w for w in ws if not w.get("interieur")]
            for w in ws:
                e0 = e1 = 0.0
                if not w.get("interieur"):
                    for o in ext:
                        if o is w: continue
                        ot = o["epaisseur"] / 2
                        if same(w["de"], o["a"]) or same(w["de"], o["de"]): e0 = ot
                        if same(w["a"], o["de"]): e1 = -ot
                        elif same(w["a"], o["a"]): e1 = ot
                self.wall(w, e0, e1)

    def wall(self, w, e0, e1):
        lv = self.levels[w["niveau"]]; st = self.storeys[w["niveau"]]
        (x0, y0), (x1, y1) = w["de"], w["a"]
        L = math.hypot(x1 - x0, y1 - y0); t = w["epaisseur"]
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        nx_, ny_ = -uy, ux
        idx = [i for i, l in enumerate(self.d["niveaux"]) if l["id"] == w["niveau"]][0]
        nxt = self.d["niveaux"][idx + 1] if idx + 1 < len(self.d["niveaux"]) else None
        H = lv["hauteur"] if w.get("interieur") else ((nxt["altitude"] - lv["altitude"]) if nxt else lv["hauteur"])
        z = lv["altitude"]
        nom = ("Cloison" if w.get("interieur") else f"Mur façade {w.get('facade', '')}") + f" — {lv['id']}"
        el = root.create_entity(self.m, ifc_class="IfcWall", name=nom, predefined_type="PARTITIONING" if w.get("interieur") else "SOLIDWALL")
        rep = geometry.add_wall_representation(self.m, context=self.body, length=L + e0 + e1, height=H, thickness=t, offset=-t / 2)
        place = mat4((x0 - ux * e0, y0 - uy * e0, z), (ux, uy, 0))
        mk = w.get("materiau_ext") if not w.get("interieur") else w.get("materiau", "interieur")
        self.finish(el, rep, mk, st, place)
        # composition (lisible dans Revit : Type de mur → Structure)
        if not w.get("interieur"):
            ls = material.add_material_set(self.m, name=f"Mur extérieur 40 cm — {w['materiau_ext']}", set_type="IfcMaterialLayerSet")
            for mkey, ep in ((w["materiau_ext"], 0.04), ("isolant_laine_bois", 0.16), ("beton_banche", 0.18), (w["materiau_int"], 0.02)):
                if mkey not in self.d["materiaux"]:
                    self.d["materiaux"][mkey] = {"type": "beton" if "beton" in mkey else "isolant", "couleur": "#b8b4ad" if "beton" in mkey else "#d9c79a"}
                lay = material.add_layer(self.m, layer_set=ls, material=self.mat(mkey))
                material.edit_layer(self.m, layer=lay, attributes={"LayerThickness": ep})
            material.unassign_material(self.m, products=[el])
            material.assign_material(self.m, products=[el], type="IfcMaterialLayerSet", material=ls)
        pset.edit_pset(self.m, pset=pset.add_pset(self.m, product=el, name="Pset_WallCommon"),
                       properties={"IsExternal": not w.get("interieur"), "LoadBearing": not w.get("interieur")})
        # ouvertures + menuiseries
        for o in w.get("ouvertures", []):
            typ = o["type"]
            al = o.get("allege", 0.9 if typ == "fenetre" else 0.0)
            h = o.get("hauteur", 2.15 if typ == "porte" else 1.25)
            wd = o["largeur"]
            ox, oy = x0 + ux * o["position"], y0 + uy * o["position"]
            op = root.create_entity(self.m, ifc_class="IfcOpeningElement", name="Ouverture")
            orep = geometry.add_wall_representation(self.m, context=self.body, length=wd, height=h, thickness=t + 0.2, offset=-(t + 0.2) / 2)
            geometry.edit_object_placement(self.m, product=op, matrix=mat4((ox, oy, z + al), (ux, uy, 0)))
            geometry.assign_representation(self.m, product=op, representation=orep)
            feature.add_feature(self.m, feature=op, element=el)
            depth = 0.08
            fpl = mat4((ox + nx_ * depth / 2, oy + ny_ * depth / 2, z + al), (ux, uy, 0))
            if typ == "porte":
                dr = root.create_entity(self.m, ifc_class="IfcDoor", name="Porte d'entrée" if o.get("entree") else "Porte intérieure",
                                        predefined_type="DOOR")
                dr.OverallHeight, dr.OverallWidth = h, wd
                drep = geometry.add_door_representation(self.m, context=self.body, overall_height=h, overall_width=wd,
                                                        operation_type="SINGLE_SWING_LEFT",
                                                        lining_properties={"LiningDepth": depth, "LiningThickness": 0.05})
                self.finish(dr, drep, o.get("materiau", "laque"), st, fpl)
                feature.add_filling(self.m, opening=op, element=dr)
            else:
                win = root.create_entity(self.m, ifc_class="IfcWindow",
                                         name=("Porte-fenêtre" if o.get("porte_fenetre") else "Baie vitrée" if typ == "baie" else "Fenêtre"),
                                         predefined_type="WINDOW")
                win.OverallHeight, win.OverallWidth = h, wd
                parts = "DOUBLE_PANEL_VERTICAL" if wd > 1.2 else "SINGLE_PANEL"
                if wd > 3.2: parts = "TRIPLE_PANEL_VERTICAL"
                wrep = geometry.add_window_representation(self.m, context=self.body, overall_height=h, overall_width=wd,
                                                          partition_type=parts,
                                                          panel_properties=[{"FrameDepth": 0.06, "FrameThickness": 0.05}] * {"SINGLE_PANEL": 1, "DOUBLE_PANEL_VERTICAL": 2, "TRIPLE_PANEL_VERTICAL": 3}[parts],
                                                          lining_properties={"LiningDepth": depth, "LiningThickness": 0.06})
                self.finish(win, wrep, "menuiserie", st, fpl)
                feature.add_filling(self.m, opening=op, element=win)

    # ---------- dalles ----------
    def slabs(self):
        for dl in self.d["dalles"]:
            lv = self.levels[dl["niveau"]]; st = self.storeys[dl["niveau"]]
            ep = dl.get("epaisseur", 0.2); top = dl.get("altitude", lv["altitude"])
            nom = dl.get("nom") or f"Plancher {lv['id']}"
            pre = "LANDING" if dl.get("balcon") else ("BASESLAB" if lv["altitude"] == 0 and "altitude" not in dl else "FLOOR")
            el = root.create_entity(self.m, ifc_class="IfcSlab", name=nom, predefined_type=pre)
            rep = geometry.add_slab_representation(self.m, context=self.body, depth=ep, polyline=[tuple(p) for p in dl["contour"]])
            self.finish(el, rep, dl.get("materiau"), st, mat4((0, 0, top - ep), (1, 0, 0)))
            for h in dl.get("tremies", []):
                op = root.create_entity(self.m, ifc_class="IfcOpeningElement", name="Trémie d'escalier")
                orep = geometry.add_slab_representation(self.m, context=self.body, depth=ep + 0.2, polyline=[tuple(p) for p in h])
                geometry.edit_object_placement(self.m, product=op, matrix=mat4((0, 0, top - ep - 0.1), (1, 0, 0)))
                geometry.assign_representation(self.m, product=op, representation=orep)
                feature.add_feature(self.m, feature=op, element=el)

    # ---------- toiture ----------
    def roof(self):
        r = self.d["toiture"]; lv = self.levels[r["niveau"]]; st = self.storeys[r["niveau"]]
        ext = [w for w in self.d["murs"] if w["niveau"] == r["niveau"] and not w.get("interieur")]
        xs = [p[0] for w in ext for p in (w["de"], w["a"])]; ys = [p[1] for w in ext for p in (w["de"], w["a"])]
        t = max(w["epaisseur"] for w in ext)
        bx0, bx1, by0, by1 = min(xs) - t / 2, max(xs) + t / 2, min(ys) - t / 2, max(ys) + t / 2
        base = lv["altitude"] + lv["hauteur"] + 0.22
        p = math.radians(r["pente"]); tp = math.tan(p); deb = r["debord"]; dp = r.get("debord_pignon", deb); ep = r["epaisseur"]
        roof = root.create_entity(self.m, ifc_class="IfcRoof", name="Toiture deux pans", predefined_type="GABLE_ROOF")
        geometry.edit_object_placement(self.m, product=roof, matrix=mat4((0, 0, 0), (1, 0, 0)))
        spatial.assign_container(self.m, products=[roof], relating_structure=st)
        half = (bx1 - bx0) / 2; mid = (bx0 + bx1) / 2; rise = half * tp
        y0, y1 = by0 - dp, by1 + dp
        ev = ep / math.cos(p)
        parts = []
        for s in (-1, 1):
            xe = mid + s * (half + deb); ze = base - deb * tp
            # section : égout bas, faîtage bas, faîtage haut, égout haut
            sec = [(xe, ze), (mid, base + rise), (mid, base + rise + ev), (xe, ze + ev)]
            V = [(x, y0, z) for x, z in sec] + [(x, y1, z) for x, z in sec]
            F = [[0, 1, 2, 3][::s], [4, 5, 6, 7][::-s], [0, 4, 5, 1], [1, 5, 6, 2], [2, 6, 7, 3], [3, 7, 4, 0]]
            el = self.mesh_el("IfcSlab", f"Pan de toiture {'ouest' if s < 0 else 'est'} — zinc", (V, F), r["materiau"], None, "ROOF")
            parts.append(el)
        aggregate.assign_object(self.m, products=parts, relating_object=roof)
        # pignons sud et nord (triangles) : murs
        for ycen, nom in ((min(ys), "sud"), (max(ys), "nord")):
            tri = [(bx0, base - 0.22), (bx1, base - 0.22), (bx1, base), (mid, base + rise), (bx0, base)]
            V = [(x, ycen - t / 2, z) for x, z in tri] + [(x, ycen + t / 2, z) for x, z in tri]
            n = len(tri)
            F = [list(range(n)), list(range(n, 2 * n))[::-1]] + [[i, n + i, n + (i + 1) % n, (i + 1) % n] for i in range(n)]
            self.mesh_el("IfcWall", f"Pignon {nom}", (V, F), ext[0]["materiau_ext"], st, "SOLIDWALL")
        # plancher de comble
        self.count["comble"] = 1

    # ---------- escalier, garde-corps, pièces, mobilier ----------
    def stairs(self):
        for s in self.d.get("escaliers", []):
            lv = self.levels[s["niveau"]]; st = self.storeys[s["niveau"]]
            nxt = [l for l in self.d["niveaux"] if l["altitude"] > lv["altitude"]][0]
            H = nxt["altitude"] - lv["altitude"]; n = s["marches"]; r = H / n; g = s["giron"]; w = s["largeur"]
            dx, dy = {"nord": (0, 1), "sud": (0, -1), "est": (1, 0), "ouest": (-1, 0)}[s["direction"]]
            meshes = []
            for i in range(n):
                cx = s["depart"][0] + dx * (i + .5) * g; cy = s["depart"][1] + dy * (i + .5) * g
                sx, sy = (g, w) if dx else (w, g)
                meshes.append(box_mesh(cx, cy, lv["altitude"] + i * r, sx, sy, r + (0.04 if i else 0)))
                # limon : on laisse les marches pleines (escalier massif) — sous-face visible depuis le séjour
            el = self.mesh_el("IfcStair", f"Escalier droit {n} marches ({r * 100:.1f} × {g * 100:.0f} cm)", merge(meshes), s["materiau"], st, "STRAIGHT_RUN_STAIR")
            pset.edit_pset(self.m, pset=pset.add_pset(self.m, product=el, name="Pset_StairCommon"),
                           properties={"NumberOfRiser": n, "NumberOfTreads": n - 1, "RiserHeight": r, "TreadLength": g})

    def railings(self):
        st = self.storeys["R+1"]; a1 = self.levels["R+1"]["altitude"]
        bal = [d for d in self.d["dalles"] if d.get("balcon")]
        style_gc = self.d["style"]["garde_corps"]
        for b in bal:
            xs = [p[0] for p in b["contour"]]; ys = [p[1] for p in b["contour"]]
            x0, x1, y0 = min(xs), max(xs), min(ys)
            segs = [((x0 + x1) / 2, y0 + 0.03, x1 - x0, 0.06, 0.0), (x0 + 0.03, (y0 - 0.2) / 2, 0.06, abs(y0 + 0.2), 0.0), (x1 - 0.03, (y0 - 0.2) / 2, 0.06, abs(y0 + 0.2), 0.0)]
            meshes = []
            for cx, cy, sx, sy, _ in segs:
                meshes.append(box_mesh(cx, cy, a1 + 0.97, sx + 0.02, max(sy, 0.08), 0.06))          # main courante
                if style_gc == "bois":
                    n = int(max(sx, sy) / 0.11)
                    for k in range(n):
                        f = (k + .5) / n
                        px = cx - sx / 2 + f * sx if sx > sy else cx; py = cy - sy / 2 + f * sy if sy > sx else cy
                        meshes.append(box_mesh(px, py, a1, 0.05 if sx > sy else 0.025, 0.025 if sx > sy else 0.05, 0.97))
            el = self.mesh_el("IfcRailing", "Garde-corps balcon", merge(meshes), "balcon" if style_gc == "bois" else "menuiserie", st, "GUARDRAIL")
            if style_gc == "verre":
                gl = merge([box_mesh(cx, cy, a1 + 0.05, sx, max(sy, 0.02) if sy < sx else sy, 0.9) for cx, cy, sx, sy, _ in [(s[0], s[1], s[2], 0.02 if s[2] > s[3] else 0.02, 0) if s[2] > s[3] else (s[0], s[1], 0.02, s[3], 0) for s in segs]])
                self.mesh_el("IfcRailing", "Garde-corps balcon — remplissage verre", gl, "verre", st, "GUARDRAIL")

    def spaces(self):
        for p in self.d["pieces"]:
            lv = self.levels[p["niveau"]]; st = self.storeys[p["niveau"]]
            sp = root.create_entity(self.m, ifc_class="IfcSpace", name=p["nom"], predefined_type="INTERNAL")
            sp.LongName = p["nom"]
            rep = geometry.add_slab_representation(self.m, context=self.body, depth=lv["hauteur"], polyline=[tuple(q) for q in p["contour"]])
            geometry.edit_object_placement(self.m, product=sp, matrix=mat4((0, 0, lv["altitude"]), (1, 0, 0)))
            geometry.assign_representation(self.m, product=sp, representation=rep)
            aggregate.assign_object(self.m, products=[sp], relating_object=st)
            area = Polygon(p["contour"]).area
            q = pset.add_qto(self.m, product=sp, name="Qto_SpaceBaseQuantities")
            pset.edit_qto(self.m, qto=q, properties={"NetFloorArea": round(area, 2), "Height": lv["hauteur"]})
            self.count["IfcSpace"] = self.count.get("IfcSpace", 0) + 1

    def furniture(self):
        for f in self.d.get("mobilier", []):
            lv = self.levels[f["niveau"]]; st = self.storeys[f["niveau"]]
            W, D, H = f["dimensions"]; rot = -math.radians(f.get("rotation", 0))
            cls = "IfcRailing" if "Garde-corps" in f.get("nom", "") else "IfcFurniture"
            name = f.get("nom") or {"lit": "Lit", "canape": "Canapé", "table": "Table"}.get(f["type"], "Mobilier")
            self.mesh_el(cls, name, box_mesh(f["position"][0], f["position"][1], lv["altitude"], W, D, H, rot), f.get("materiau"), st)

    def write(self, path):
        self.walls(); self.slabs(); self.roof(); self.stairs(); self.railings(); self.spaces(); self.furniture()
        self.m.write(path)
        return self.count


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    for style_ in ("traditionnel", "contemporain"):
        with open(os.path.join(here, "out", f"chalet_{style_}.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        out = os.path.join(here, "out", f"chalet_{style_}.ifc")
        c = IFCWriter(data).write(out)
        print(style_, os.path.getsize(out) // 1024, "Ko", c)
