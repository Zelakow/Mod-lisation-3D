"""Définition du projet : maison R+1 de montagne, 125 m² habitables, deux variantes de style.

Repère : mètres, x vers l'est, y vers le nord, z vers le haut.
Les murs sont décrits par leur axe ; les pièces par leur contour intérieur (nu des murs),
ce qui donne directement la surface habitable (hors cloisons, escalier et trémie).
"""
import json, os
from shapely.geometry import Polygon

L, P = 11.2, 6.8          # axes des murs extérieurs
TE, TI = 0.40, 0.10       # épaisseurs : extérieur (béton + isolant + parement), cloisons
ALT1, H0, H1 = 2.75, 2.50, 2.50   # altitude du R+1, hauteurs sous plafond
DALLE = 0.25
STAIR = dict(depart=[9.8, 6.1], direction="ouest", largeur=1.0, marches=16, giron=0.26)
STAIR_X0 = STAIR["depart"][0] - STAIR["marches"] * STAIR["giron"]   # 5.64

def ext_walls(niv, op):
    return [
        dict(niveau=niv, de=[0, 0], a=[L, 0], epaisseur=TE, facade="sud", ouvertures=op["S"]),
        dict(niveau=niv, de=[L, 0], a=[L, P], epaisseur=TE, facade="est", ouvertures=op["E"]),
        dict(niveau=niv, de=[L, P], a=[0, P], epaisseur=TE, facade="nord", ouvertures=op["N"]),
        dict(niveau=niv, de=[0, P], a=[0, 0], epaisseur=TE, facade="ouest", ouvertures=op["O"]),
    ]

def F(pos, w, h=1.25, al=1.0, **k):  return dict(type="fenetre", position=pos, largeur=w, hauteur=h, allege=al, **k)
def B(pos, w, h=2.25, **k):          return dict(type="baie", position=pos, largeur=w, hauteur=h, allege=0, **k)
def PO(pos, w=0.83, h=2.04, **k):    return dict(type="porte", position=pos, largeur=w, hauteur=h, **k)

def ouvertures(style):
    contemporain = style == "contemporain"
    rdc = dict(
        S=([B(0.7, 6.4, 2.3)] if contemporain else [B(0.9, 2.6), B(4.4, 2.6)]) + [F(9.0, 1.0, 1.1, 1.0)],
        E=[F(1.0, 0.8, 1.1, 1.0), F(3.3, 0.5, 0.6, 1.5), F(5.0, 0.8, 1.2, 1.0)],
        N=[PO(0.5, 1.0, 2.2, entree=True), F(7.6, 1.4, 1.0, 1.1), F(9.6, 1.0, 1.0, 1.1)],
        O=[F(1.2, 1.2, 1.25, 1.0), (B(3.6, 2.4) if contemporain else B(3.8, 1.8))],
    )
    r1 = dict(
        S=[B(1.3, 1.6, 2.2, porte_fenetre=True), B(5.0, 1.6, 2.2, porte_fenetre=True), B(8.5, 1.6, 2.2, porte_fenetre=True)],
        E=[F(2.0, 1.0), F(5.0, 0.8)],
        N=[F(3.5, 1.0, 1.0, 1.2), F(6.9, 0.4, 0.6, 1.5), F(9.0, 1.0, 0.9, 1.3)],
        O=[F(1.5, 0.8), F(4.6, 1.0)],
    )
    return rdc, r1

def cloisons():
    w = lambda niv, de, a, op=None: dict(niveau=niv, de=de, a=a, epaisseur=TI, interieur=True, ouvertures=op or [])
    return [
        # RDC
        w("RDC", [7.8, 0], [7.8, 4.45]),
        w("RDC", [7.8, 2.6], [L, 2.6], [PO(0.4, 0.83)]),
        w("RDC", [9.6, 2.6], [9.6, 4.45], [PO(0.5, 0.73)]),
        w("RDC", [9.6, 4.45], [L, 4.45]),
        # R+1
        w("R+1", [0, 3.95], [L, 3.95], [PO(2.6, 0.83), PO(4.3, 0.83), PO(8.0, 0.83)]),
        w("R+1", [4.0, 0], [4.0, 3.95]),
        w("R+1", [7.6, 0], [7.6, 3.95]),
        w("R+1", [3.6, 3.95], [3.6, P], [PO(0.15, 0.83)]),
        w("R+1", [3.6, 5.05], [4.7, 5.05], [PO(0.15, 0.73)]),
        w("R+1", [4.7, 5.05], [4.7, P]),
    ]

def pieces():
    x0 = STAIR_X0
    return [
        dict(niveau="RDC", nom="Séjour – cuisine", contour=[[0.2,0.2],[7.75,0.2],[7.75,5.6],[x0,5.6],[x0,6.6],[0.2,6.6]]),
        dict(niveau="RDC", nom="Entrée", contour=[[7.85,2.65],[9.55,2.65],[9.55,4.5],[11.0,4.5],[11.0,6.6],[9.8,6.6],[9.8,5.6],[7.75,5.6],[7.75,4.45],[7.85,4.45]]),
        dict(niveau="RDC", nom="Buanderie – local skis", contour=[[7.85,0.2],[11.0,0.2],[11.0,2.55],[7.85,2.55]]),
        dict(niveau="RDC", nom="WC", contour=[[9.65,2.65],[11.0,2.65],[11.0,4.4],[9.65,4.4]]),
        dict(niveau="R+1", nom="Chambre 1 (parents)", contour=[[0.2,0.2],[3.95,0.2],[3.95,3.9],[0.2,3.9]]),
        dict(niveau="R+1", nom="Chambre 2", contour=[[4.05,0.2],[7.55,0.2],[7.55,3.9],[4.05,3.9]]),
        dict(niveau="R+1", nom="Chambre 3", contour=[[7.65,0.2],[11.0,0.2],[11.0,3.9],[7.65,3.9]]),
        dict(niveau="R+1", nom="Salle de bain", contour=[[0.2,4.0],[3.55,4.0],[3.55,6.6],[0.2,6.6]]),
        dict(niveau="R+1", nom="WC", contour=[[3.65,5.1],[4.65,5.1],[4.65,6.6],[3.65,6.6]]),
        dict(niveau="R+1", nom="Palier", contour=[[3.65,4.0],[11.0,4.0],[11.0,6.6],[STAIR['depart'][0],6.6],[STAIR['depart'][0],5.6],[x0,5.6],[x0,6.6],[4.75,6.6],[4.75,5.05],[3.65,5.05]]),
    ]

STYLES = {
    "traditionnel": dict(
        nom="Variante A — Traditionnelle",
        resume="Socle enduit blanc, étage et pignon en bardage bois peint rouge oxyde, lambrequins blancs découpés, volets battants, balcon bois, zinc naturel.",
        materiaux=dict(
            mur_rdc=dict(type="enduit", couleur="#efebe3"),
            mur_r1=dict(type="bois", couleur="#8f2f24", echelle=1.0),
            interieur=dict(type="peinture", couleur="#f3f1ec"),
            zinc=dict(type="zinc", couleur="#a9adb0"),
            menuiserie=dict(type="peinture", couleur="#f4f2ee"),
            volet=dict(type="bois", couleur="#2f4a3a", echelle=0.8),
            lambrequin=dict(type="peinture", couleur="#f6f4ef"),
            balcon=dict(type="bois", couleur="#f2efe8", echelle=0.8),
            sol_jour=dict(type="parquet", couleur="#c49a6c"),
            sol_eau=dict(type="carrelage", couleur="#c9c4bb"),
            soubassement=dict(type="pierre", couleur="#8d8a84"),
        ),
        volets=True, lambrequins=True, garde_corps="bois", oeil_de_boeuf=True, toit_couleur="zinc naturel",
    ),
    "contemporain": dict(
        nom="Variante B — Contemporaine",
        resume="Socle en pierre de montagne, étage en mélèze grisé à claire-voie, grandes baies, menuiseries anthracite, garde-corps verre, zinc anthracite à joints debout.",
        materiaux=dict(
            mur_rdc=dict(type="pierre", couleur="#7f7c76", echelle=1.6),
            mur_r1=dict(type="bois", couleur="#8a8178", echelle=1.4),
            interieur=dict(type="peinture", couleur="#f2f1ee"),
            zinc=dict(type="zinc", couleur="#45494d"),
            menuiserie=dict(type="metal", couleur="#2e3236"),
            volet=dict(type="metal", couleur="#2e3236"),
            lambrequin=dict(type="metal", couleur="#2e3236"),
            balcon=dict(type="bois", couleur="#7e756b", echelle=1.0),
            sol_jour=dict(type="parquet", couleur="#b99a78"),
            sol_eau=dict(type="carrelage", couleur="#8f8c86"),
            soubassement=dict(type="beton", couleur="#9a978f"),
        ),
        volets=False, lambrequins=False, garde_corps="verre", oeil_de_boeuf=False, toit_couleur="zinc anthracite",
    ),
}

def projet(style):
    S = STYLES[style]
    rdc_op, r1_op = ouvertures(style)
    mat = dict(S["materiaux"])
    mat.update(
        plafond=dict(type="peinture", couleur="#f7f6f2"),
        verre=dict(type="verre"),
        neige=dict(type="enduit", couleur="#f4f7fa"),
        prairie=dict(type="gazon", couleur="#6f7f45"),
        escalier=dict(type="bois", couleur="#a9825a", echelle=0.6),
        tissu=dict(type="tissu", couleur="#c7bfb1"),
        linge=dict(type="tissu", couleur="#efede8"),
        chene=dict(type="bois", couleur="#b88b5e", echelle=0.6),
        laque=dict(type="peinture", couleur="#ecebe6"),
        porte_entree=dict(type="bois", couleur="#5b3d29", echelle=0.6),
    )
    murs = []
    for w in ext_walls("RDC", rdc_op): w.update(materiau_ext="mur_rdc", materiau_int="interieur"); murs.append(w)
    for w in ext_walls("R+1", r1_op):  w.update(materiau_ext="mur_r1", materiau_int="interieur"); murs.append(w)
    for w in cloisons(): w["materiau"] = "interieur"; murs.append(w)
    for w in murs:
        for o in w["ouvertures"]:
            if o.get("entree"): o["materiau"] = "porte_entree"
    x0 = STAIR_X0
    data = dict(
        projet=dict(nom=f"Chalet R+1 — {S['nom'].split('— ')[1]}", variante=S["nom"], description=S["resume"],
                    site="Montagne, altitude ~1 400 m, façade principale plein sud face à la vallée",
                    surface_habitable_cible=125),
        unite="m",
        niveaux=[dict(id="RDC", nom="Rez-de-chaussée", altitude=0, hauteur=H0),
                 dict(id="R+1", nom="Étage", altitude=ALT1, hauteur=H1)],
        defauts=dict(cadre="menuiserie", porte="laque", plafond="plafond", sol="prairie", chant="soubassement"),
        materiaux=mat,
        murs=murs,
        dalles=[
            dict(niveau="RDC", contour=[[0,0],[7.8,0],[7.8,P],[0,P]], epaisseur=DALLE, materiau="sol_jour"),
            dict(niveau="RDC", contour=[[7.8,0],[L,0],[L,P],[7.8,P]], epaisseur=DALLE, materiau="sol_eau"),
            dict(niveau="RDC", nom="Terrasse", contour=[[-0.2,-3.2],[7.6,-3.2],[7.6,-0.2],[-0.2,-0.2]], altitude=-0.05, epaisseur=0.4, materiau="soubassement"),
            dict(niveau="RDC", nom="Parvis d'entrée", contour=[[9.4,6.8],[11.0,6.8],[11.0,8.2],[9.4,8.2]], altitude=-0.05, epaisseur=0.3, materiau="soubassement"),
            dict(niveau="R+1", contour=[[0,0],[L,0],[L,P],[0,P]], epaisseur=DALLE, materiau="sol_jour",
                 tremies=[[[x0,5.6],[STAIR['depart'][0],5.6],[STAIR['depart'][0],6.6],[x0,6.6]]]),
            dict(niveau="R+1", nom="Sol salle de bain", contour=[[0.2,4.0],[3.55,4.0],[3.55,6.6],[0.2,6.6]], altitude=ALT1+0.006, epaisseur=0.01, materiau="sol_eau"),
            dict(niveau="R+1", nom="Balcon", contour=[[-0.6,-1.6],[L+0.6,-1.6],[L+0.6,-0.2],[-0.6,-0.2]], altitude=ALT1-0.03, epaisseur=0.2, materiau="balcon", balcon=True),
        ],
        escaliers=[dict(niveau="RDC", materiau="escalier", **STAIR)],
        toiture=dict(type="deux_pans", niveau="R+1", faitage="y", pente=30, debord=0.9, debord_pignon=1.2,
                     epaisseur=0.3, materiau="zinc", materiau_sous_face="balcon"),
        pieces=pieces(),
        mobilier=[
            dict(niveau="RDC", type="canape", position=[2.4, 2.8], dimensions=[2.6, 1.0, 0.8], rotation=180, materiau="tissu"),
            dict(niveau="RDC", type="boite", nom="Table basse", position=[2.4, 1.7], dimensions=[1.2, 0.6, 0.38], materiau="chene"),
            dict(niveau="RDC", type="boite", nom="Poêle à bois", position=[5.2, 1.0], dimensions=[0.55, 0.5, 1.1], materiau="menuiserie"),
            dict(niveau="RDC", type="table", position=[5.6, 3.6], dimensions=[2.2, 1.0, 0.75], materiau="chene"),
            dict(niveau="RDC", type="boite", nom="Cuisine linéaire", position=[2.4, 6.27], dimensions=[4.0, 0.65, 0.9], materiau="laque"),
            dict(niveau="RDC", type="boite", nom="Îlot", position=[2.4, 4.9], dimensions=[2.4, 0.9, 0.92], materiau="chene"),
            dict(niveau="RDC", type="boite", nom="Banc d'entrée", position=[10.6, 5.6], dimensions=[0.45, 1.4, 0.45], materiau="chene"),
            dict(niveau="R+1", type="lit", position=[2.1, 2.7], dimensions=[1.6, 2.0, 0.55], rotation=0, materiau="chene"),
            dict(niveau="R+1", type="lit", position=[5.8, 2.8], dimensions=[1.4, 1.9, 0.55], materiau="chene"),
            dict(niveau="R+1", type="lit", position=[9.3, 2.8], dimensions=[1.4, 1.9, 0.55], materiau="chene"),
            dict(niveau="R+1", type="boite", nom="Baignoire", position=[1.05, 5.5], dimensions=[0.75, 1.7, 0.55], materiau="laque"),
            dict(niveau="R+1", type="boite", nom="Double vasque", position=[2.2, 6.35], dimensions=[1.4, 0.5, 0.85], materiau="chene"),
            dict(niveau="R+1", type="boite", nom="Garde-corps trémie", position=[(x0+9.8)/2, 5.58], dimensions=[9.8-x0, 0.03, 1.0], materiau="verre"),
        ],
        style={k: v for k, v in S.items() if k not in ("materiaux",)},
        visite=dict(depart=[10.2, 13.0], orientation=180, niveau="RDC"),
    )
    return data

def surfaces(data):
    out = {}
    for p in data["pieces"]:
        a = Polygon(p["contour"]).area
        out.setdefault(p["niveau"], []).append((p["nom"], a))
    return out

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    for style in STYLES:
        d = projet(style)
        with open(os.path.join(here, "out", f"chalet_{style}.json"), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    s = surfaces(projet("traditionnel"))
    tot = 0
    for niv, rows in s.items():
        sub = sum(a for _, a in rows); tot += sub
        print(f"--- {niv} : {sub:.2f} m²")
        for n, a in rows: print(f"  {n:28s} {a:6.2f} m²")
    print(f"=== Surface habitable totale : {tot:.2f} m²")
