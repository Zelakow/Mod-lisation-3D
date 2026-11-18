"""Dessine les plans cotés (RDC, R+1) et une coupe à partir du JSON du projet."""
import json, math, os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MPoly, Arc, FancyArrowPatch
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from shapely import affinity

INK = "#1d232a"; GREY = "#8a939c"; ACC = "#b23a2b"

def wall_geom(w, all_ext):
    (x0, y0), (x1, y1) = w["de"], w["a"]
    L = math.hypot(x1 - x0, y1 - y0); t = w["epaisseur"]
    e0 = e1 = 0
    if not w.get("interieur"):
        e0 = e1 = t / 2
    solid = box(-e0, -t / 2, L + e1, t / 2)
    holes = [box(o["position"], -t, o["position"] + o["largeur"], t) for o in w.get("ouvertures", [])]
    ang = math.degrees(math.atan2(y1 - y0, x1 - x0))
    tr = lambda g: affinity.translate(affinity.rotate(g, ang, origin=(0, 0)), x0, y0)
    return tr(solid), [tr(h) for h in holes], (x0, y0, ang, L, t)

def draw_level(ax, data, niv, title):
    murs = [w for w in data["murs"] if w["niveau"] == niv]
    ext = [w for w in murs if not w.get("interieur")]
    solids, holes, frames = [], [], []
    for w in murs:
        s, h, fr = wall_geom(w, ext); solids.append(s); holes += h; frames.append((w, fr))
    walls = unary_union(solids).difference(unary_union(holes))
    # sols / pièces
    for p in data["pieces"]:
        if p["niveau"] != niv: continue
        poly = Polygon(p["contour"])
        ax.add_patch(MPoly(p["contour"], closed=True, fc="#f4f1ea", ec="none", zorder=1))
        c = poly.representative_point()
        ax.text(c.x, c.y + 0.12, p["nom"], ha="center", va="bottom", fontsize=7.2, color=INK, zorder=6)
        ax.text(c.x, c.y - 0.05, f"{poly.area:.2f} m²".replace(".", ","), ha="center", va="top", fontsize=6.6, color=GREY, zorder=6, family="monospace")
    geoms = getattr(walls, "geoms", [walls])
    for g in geoms:
        ax.add_patch(MPoly(list(g.exterior.coords), closed=True, fc=INK, ec=INK, lw=0.4, zorder=5))
        for hole in g.interiors:
            ax.add_patch(MPoly(list(hole.coords), closed=True, fc="white", ec="none", zorder=5))
    # ouvertures : fenêtres (traits fins) et portes (battant + arc)
    for w, (x0, y0, ang, L, t) in frames:
        a = math.radians(ang); ux, uy = math.cos(a), math.sin(a); nx, ny = -uy, ux
        P = lambda u, v: (x0 + ux * u + nx * v, y0 + uy * u + ny * v)
        for o in w.get("ouvertures", []):
            u0, u1 = o["position"], o["position"] + o["largeur"]
            if o["type"] == "porte":
                side = 1  # la normale gauche de chaque mur extérieur pointe vers l'intérieur
                hinge = P(u0, side * t / 2); tip = P(u0, side * (t / 2 + (u1 - u0)))
                ax.plot([hinge[0], tip[0]], [hinge[1], tip[1]], color=INK, lw=0.9, zorder=6)
                start = math.degrees(math.atan2(tip[1] - hinge[1], tip[0] - hinge[0]))
                end = math.degrees(math.atan2(P(u1, side * t / 2)[1] - hinge[1], P(u1, side * t / 2)[0] - hinge[0]))
                lo, hi = sorted([start, end])
                if hi - lo > 180: lo, hi = hi, lo + 360
                ax.add_patch(Arc(hinge, 2 * (u1 - u0), 2 * (u1 - u0), theta1=lo, theta2=hi, color=GREY, lw=0.6, zorder=6))
            else:
                for v in (-t / 2, -0.03, 0.03, t / 2):
                    p0, p1 = P(u0, v), P(u1, v)
                    ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=INK, lw=0.5 if abs(v) < 0.1 else 0.8, zorder=6)
    # escalier
    for s in data.get("escaliers", []):
        n, g, w = s["marches"], s["giron"], s["largeur"]; x, y = s["depart"]
        if niv == s["niveau"] or (niv == "R+1"):
            for i in range(n + 1):
                xx = x - i * g
                ax.plot([xx, xx], [y - w / 2, y + w / 2], color=GREY if niv == "R+1" else INK, lw=0.5, zorder=4)
            ax.plot([x, x - n * g], [y - w / 2, y - w / 2], color=INK, lw=0.6, zorder=4)
            ax.plot([x, x - n * g], [y + w / 2, y + w / 2], color=INK, lw=0.6, zorder=4)
            if niv == s["niveau"]:
                ax.add_patch(FancyArrowPatch((x - 0.15, y), (x - n * g * 0.55, y), arrowstyle="-|>", mutation_scale=8, color=ACC, lw=0.9, zorder=7))
                ax.text(x - n * g * 0.55 - 0.1, y, "monte", fontsize=6, color=ACC, va="center", ha="right", zorder=7)
            else:
                ax.text(x - n * g / 2, y, "vide sur escalier", fontsize=6, color=GREY, va="center", ha="center", zorder=7)
    # balcon (R+1) et terrasse (RDC)
    for d in data["dalles"]:
        if d.get("altitude") is None or d["niveau"] != niv: continue
        if d.get("nom") in ("Balcon", "Terrasse", "Parvis d'entrée"):
            ax.add_patch(MPoly(d["contour"], closed=True, fc="none", ec=GREY, lw=0.7, ls=(0, (4, 2)), zorder=2))
            c = Polygon(d["contour"]).centroid
            ax.text(c.x, c.y, d["nom"], fontsize=6.5, color=GREY, ha="center", va="center")
    # cotes extérieures
    xs = sorted({0, 11.2} | {round(o["position"] + k * o["largeur"], 3) for w in ext if w["facade"] == "sud" for o in w["ouvertures"] for k in (0, 1)})
    dim_chain(ax, xs, -2.3 if niv == "RDC" else -2.3, horiz=True)
    dim_chain(ax, [0, 11.2], -2.9, horiz=True, label_total=True)
    ys = sorted({0, 6.8} | {round(6.8 - o["position"] - k * o["largeur"], 3) for w in ext if w["facade"] == "ouest" for o in w["ouvertures"] for k in (0, 1)})
    dim_chain(ax, ys, -1.2, horiz=False)
    dim_chain(ax, [0, 6.8], -1.8, horiz=False, label_total=True)
    ax.set_title(title, loc="left", fontsize=11, color=INK, fontweight="bold")

def dim_chain(ax, vals, off, horiz=True, label_total=False):
    vals = sorted(vals)
    for a, b in zip(vals, vals[1:]):
        if horiz:
            ax.plot([a, b], [off, off], color=INK, lw=0.5)
            for v in (a, b): ax.plot([v - 0.07, v + 0.07], [off - 0.07, off + 0.07], color=INK, lw=0.8)
            ax.text((a + b) / 2, off + 0.08, f"{b - a:.2f}".replace(".", ","), fontsize=5.6 if not label_total else 6.8, ha="center", va="bottom", color=INK, family="monospace")
        else:
            ax.plot([off, off], [a, b], color=INK, lw=0.5)
            for v in (a, b): ax.plot([off - 0.07, off + 0.07], [v - 0.07, v + 0.07], color=INK, lw=0.8)
            ax.text(off - 0.08, (a + b) / 2, f"{b - a:.2f}".replace(".", ","), fontsize=5.6 if not label_total else 6.8, ha="right", va="center", rotation=90, color=INK, family="monospace")

def north(ax, x, y):
    ax.add_patch(FancyArrowPatch((x, y), (x, y + 0.9), arrowstyle="-|>", mutation_scale=12, color=INK, lw=1))
    ax.text(x, y + 1.0, "N", ha="center", va="bottom", fontsize=9, fontweight="bold")

def coupe(ax, data):
    """Coupe AA transversale (est-ouest) à y = 2,00 m : séjour, buanderie, chambres 1-2-3, comble."""
    lv = data["niveaux"]; a1 = lv[1]["altitude"]; base = a1 + lv[1]["hauteur"]; d = 0.25; t = 0.4; L = 11.2
    roof = data["toiture"]; tp = math.tan(math.radians(roof["pente"])); deb = roof["debord"]; ep = roof["epaisseur"]
    ax.fill_between([-4, L + 4], -1.0, -0.12, color="#e9e4d8", zorder=0); ax.plot([-4, L + 4], [-0.12, -0.12], color=INK, lw=0.8)
    blk = lambda pts, c=INK, z=5: ax.add_patch(MPoly(pts, closed=True, fc=c, ec="none", zorder=z))
    for x0 in (-t / 2, L - t / 2): blk([[x0, -0.3], [x0 + t, -0.3], [x0 + t, base], [x0, base]])
    for top in (0, a1): blk([[-t / 2, top - d], [L + t / 2, top - d], [L + t / 2, top], [-t / 2, top]])
    blk([[-t / 2, base], [L + t / 2, base], [L + t / 2, base + 0.22], [-t / 2, base + 0.22]])          # plancher du comble
    blk([[7.75, 0], [7.85, 0], [7.85, a1 - d], [7.75, a1 - d]])                                          # cloison RDC
    for xc in (4.0, 7.6): blk([[xc - 0.05, a1], [xc + 0.05, a1], [xc + 0.05, base], [xc - 0.05, base]])  # cloisons R+1
    # toiture : deux rampants 30° posés sur l'arase des murs, débords d'égout
    half = L / 2 + t / 2; rise = half * tp; z0 = base + 0.22
    for s in (-1, 1):
        xe = L / 2 + s * (half + deb); ze = z0 - deb * tp
        xr = L / 2
        blk([[xe, ze], [xr, z0 + rise], [xr, z0 + rise + ep / math.cos(math.radians(roof["pente"]))], [xe, ze + ep / math.cos(math.radians(roof["pente"]))]], "#8f969c", 4)
    ax.text(L / 2, z0 + rise * 0.35, "comble perdu isolé", ha="center", fontsize=7, color=GREY)
    zf = z0 + rise + ep / math.cos(math.radians(roof["pente"]))
    # niveaux
    for z, lab in ((0, "±0,00 RDC"), (a1, f"+{a1:.2f} R+1"), (base, f"+{base:.2f} plafond R+1"), (zf, f"+{zf:.2f} faîtage")):
        ax.plot([L + 0.5, L + 1.4], [z, z], color=ACC, lw=0.7)
        ax.text(L + 1.45, z, lab.replace(".", ","), fontsize=7, color=ACC, va="center", family="monospace")
    for z0_, z1_ in ((0, a1 - d), (a1, base)):
        ax.annotate("", (2.6, z0_), (2.6, z1_), arrowprops=dict(arrowstyle="<->", color=INK, lw=0.6))
        ax.text(2.7, (z0_ + z1_) / 2, "HSP 2,50", fontsize=6.5, va="center", family="monospace")
    ax.text(4.2, 0.35, "Séjour – cuisine", fontsize=7, ha="center"); ax.text(9.4, 0.35, "Buanderie – local skis", fontsize=7, ha="center")
    for x, n in ((2.0, "Chambre 1"), (5.8, "Chambre 2"), (9.4, "Chambre 3")): ax.text(x, a1 + 0.35, n, fontsize=7, ha="center")
    ax.text(-2.6, 0.2, "OUEST", fontsize=8, fontweight="bold", color=GREY); ax.text(L + 1.6, -0.6, "EST", fontsize=8, fontweight="bold", color=GREY)
    ax.text(L / 2, -0.75, f"Pente 30° · débords d'égout {deb:.2f} m".replace(".", ","), fontsize=7, ha="center", color=GREY)
    ax.set_title("Coupe AA (transversale est-ouest, y = 2,00 m)", loc="left", fontsize=11, color=INK, fontweight="bold")
    ax.set_xlim(-3, L + 4.6); ax.set_ylim(-1.0, zf + 0.6); ax.set_aspect("equal"); ax.axis("off")

def render(data, path_png, path_svg=None):
    fig = plt.figure(figsize=(16.5, 11.7), dpi=110)
    fig.patch.set_facecolor("white")
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 0.62], hspace=0.12, wspace=0.05, left=0.03, right=0.97, top=0.93, bottom=0.04)
    for i, (niv, title) in enumerate((("RDC", "Plan du rez-de-chaussée"), ("R+1", "Plan de l'étage"))):
        ax = fig.add_subplot(gs[0, i]); draw_level(ax, data, niv, title)
        ax.set_xlim(-2.6, 12.6); ax.set_ylim(-3.3, 9.0); ax.set_aspect("equal"); ax.axis("off")
        north(ax, 12.1, 7.5)
        ax.plot([-1.5, 3.5], [8.4, 8.4], color=INK, lw=0.8)
        for k in range(6): ax.plot([-1.5 + k, -1.5 + k], [8.33, 8.47], color=INK, lw=0.8)
        ax.text(1.0, 8.55, "0          5 m", fontsize=6.5, ha="center", family="monospace")
    ax = fig.add_subplot(gs[1, 0]); coupe(ax, data)
    ax = fig.add_subplot(gs[1, 1]); ax.axis("off")
    rows = {}
    for p in data["pieces"]: rows.setdefault(p["niveau"], []).append((p["nom"], Polygon(p["contour"]).area))
    y = 0.95; tot = 0
    ax.text(0.02, y, "Tableau des surfaces habitables", fontsize=11, fontweight="bold", transform=ax.transAxes); y -= 0.08
    for niv, lst in rows.items():
        sub = sum(a for _, a in lst); tot += sub
        ax.text(0.02, y, {"RDC": "Rez-de-chaussée", "R+1": "Étage"}[niv], fontsize=8.5, fontweight="bold", transform=ax.transAxes)
        ax.text(0.62, y, f"{sub:6.2f} m²".replace(".", ","), fontsize=8.5, fontweight="bold", family="monospace", ha="right", transform=ax.transAxes); y -= 0.055
        for n, a in lst:
            ax.text(0.05, y, n, fontsize=8, transform=ax.transAxes)
            ax.text(0.62, y, f"{a:6.2f} m²".replace(".", ","), fontsize=8, family="monospace", ha="right", transform=ax.transAxes); y -= 0.048
        y -= 0.02
    ax.plot([0.02, 0.62], [y + 0.03, y + 0.03], color=INK, lw=0.8, transform=ax.transAxes)
    ax.text(0.02, y - 0.02, "Total habitable", fontsize=9.5, fontweight="bold", transform=ax.transAxes)
    ax.text(0.62, y - 0.02, f"{tot:6.2f} m²".replace(".", ","), fontsize=9.5, fontweight="bold", family="monospace", ha="right", transform=ax.transAxes)
    st = data["style"]
    ax.text(0.68, 0.95, st["nom"], fontsize=10, fontweight="bold", transform=ax.transAxes, color=ACC)
    import textwrap
    ax.text(0.68, 0.88, "\n".join(textwrap.wrap(st["resume"], 42)), fontsize=8, va="top", transform=ax.transAxes, linespacing=1.5)
    ax.text(0.68, 0.45, "Murs ext. 40 cm · cloisons 10 cm\nHSP 2,50 m · dalles 25 cm\nToiture 2 pans 30°, zinc, débords 0,90 / 1,20 m\nSurfaces au nu intérieur des murs,\nhors cloisons, escalier et trémie.\nProjet fictif d'exemple, non réglementaire.",
            fontsize=7.5, va="top", transform=ax.transAxes, color=GREY, linespacing=1.6)
    fig.suptitle(data["projet"]["nom"], x=0.03, ha="left", fontsize=15, fontweight="bold", color=INK)
    fig.savefig(path_png, facecolor="white")
    if path_svg: fig.savefig(path_svg, facecolor="white")
    plt.close(fig)

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    for style in ("traditionnel", "contemporain"):
        with open(os.path.join(here, "out", f"chalet_{style}.json"), encoding="utf-8") as f:
            data = json.load(f)
        render(data, os.path.join(here, "out", f"plans_{style}.png"), os.path.join(here, "out", f"plans_{style}.svg"))
        print("ok", style)
