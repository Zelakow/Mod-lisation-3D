"""Relit un IFC, le valide contre le schéma et dessine sa géométrie (preuve indépendante du générateur)."""
import sys, os, numpy as np, ifcopenshell, ifcopenshell.geom, ifcopenshell.validate, ifcopenshell.util.element as ue
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
path, out = sys.argv[1], sys.argv[2]
f = ifcopenshell.open(path)
log = ifcopenshell.validate.json_logger(); ifcopenshell.validate.validate(f, log)
print(os.path.basename(path), "| schéma", f.schema, "| erreurs de validation :", len(log.statements))
for s in log.statements[:5]: print("  ", str(s)[:160])
for st in f.by_type("IfcBuildingStorey"):
    els = ue.get_decomposition(st)
    kinds = {}
    for e in els: kinds[e.is_a()] = kinds.get(e.is_a(), 0) + 1
    print(f"  {st.Name} (+{st.Elevation:.2f} m) :", dict(sorted(kinds.items())))
sp = f.by_type("IfcSpace"); tot = 0
for s in sp:
    q = ue.get_psets(s).get("Qto_SpaceBaseQuantities", {}); tot += q.get("NetFloorArea", 0)
print(f"  Pièces (IfcSpace) : {len(sp)} — somme NetFloorArea = {tot:.2f} m²")
w = f.by_type("IfcWall")[0]; print("  Exemple de composition :", [ (l.Material.Name, l.LayerThickness) for l in ue.get_material(w, should_skip_usage=True).MaterialLayers ] if ue.get_material(w, should_skip_usage=True) and ue.get_material(w, should_skip_usage=True).is_a("IfcMaterialLayerSet") else ue.get_material(w))
settings = ifcopenshell.geom.settings(); settings.set("use-world-coords", True)
it = ifcopenshell.geom.iterator(settings, f, os.cpu_count())
polys, cols = [], []
if it.initialize():
    while True:
        sh = it.get(); el = f.by_id(sh.id)
        if not el.is_a("IfcSpace") and not el.is_a("IfcOpeningElement"):
            v = np.array(sh.geometry.verts).reshape(-1, 3); fa = np.array(sh.geometry.faces).reshape(-1, 3)
            mats = sh.geometry.materials; mids = np.array(sh.geometry.material_ids)
            for k, tri in enumerate(fa):
                c = (0.7, 0.7, 0.7, 1)
                if len(mats) and mids[k] >= 0:
                    m = mats[mids[k]]; d = m.diffuse
                    c = (d.r(), d.g(), d.b(), 1 - (m.transparency if m.transparency == m.transparency else 0))
                polys.append(v[tri]); cols.append(c)
        if not it.next(): break
P = np.array(polys); C = np.array(cols)
L = np.array([0.4, -0.6, 0.7]); L /= np.linalg.norm(L)
n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]); n /= (np.linalg.norm(n, axis=1)[:, None] + 1e-9)
shade = 0.55 + 0.45 * np.abs(n @ L)
C[:, :3] *= shade[:, None]
fig = plt.figure(figsize=(14, 7), dpi=110)
for i, (el, az) in enumerate(((22, -58), (22, 132))):
    ax = fig.add_subplot(1, 2, i + 1, projection="3d")
    ax.add_collection3d(Poly3DCollection(P, facecolors=C, edgecolors=(0, 0, 0, 0.08), linewidths=0.2))
    ax.set_xlim(-2, 13); ax.set_ylim(-4.5, 10.5); ax.set_zlim(-1, 10); ax.set_box_aspect((15, 15, 11))
    ax.view_init(el, az); ax.axis("off")
    ax.set_title(["Vue sud-ouest", "Vue nord-est"][i], fontsize=10)
fig.suptitle(f"Géométrie relue depuis {os.path.basename(path)} ({len(P)} triangles)", fontsize=12)
plt.tight_layout(); fig.savefig(out, facecolor="white")
