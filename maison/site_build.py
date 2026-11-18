"""Assemble le dossier de publication maison/site/ à partir de maison/out/ et de la visionneuse."""
import os, shutil, glob
HERE = os.path.dirname(os.path.abspath(__file__))
OUT, SITE = os.path.join(HERE, "out"), os.path.join(HERE, "site")
os.makedirs(os.path.join(SITE, "img"), exist_ok=True)
import json
rendus = {}
for v in ("traditionnel", "contemporain"):
    for k in ("sud", "aerienne", "nord", "interieur"):
        final, apercu = os.path.join(OUT, f"rendu_{v}_{k}.jpg"), os.path.join(OUT, f"rendu_{v}_{k}_apercu.jpg")
        if os.path.exists(final):
            shutil.copy(final, os.path.join(SITE, "img", os.path.basename(final))); etat = "final"; nom = os.path.basename(final)
        elif os.path.exists(apercu) and not (v == "contemporain" and k == "sud"):
            shutil.copy(apercu, os.path.join(SITE, "img", os.path.basename(apercu))); etat = "apercu"; nom = os.path.basename(apercu)
        else:
            etat, nom = "en_cours", None
        rendus.setdefault(v, {})[k] = {"etat": etat, "src": f"img/{nom}" if nom else None}
json.dump(rendus, open(os.path.join(SITE, "rendus.json"), "w"), indent=1)
for p in ("avant_traditionnel_sud.jpg", "preuve_photorealisme_avant_apres.jpg", "preuve_sapin.png"):
    if os.path.exists(os.path.join(OUT, p)): shutil.copy(os.path.join(OUT, p), os.path.join(SITE, "img", p))
for p in glob.glob(os.path.join(OUT, "plans_*.png")) + glob.glob(os.path.join(OUT, "preuve_ifc_*.png")):
    shutil.copy(p, os.path.join(SITE, "img", os.path.basename(p)))
for p in glob.glob(os.path.join(OUT, "chalet_*.json")):
    shutil.copy(p, os.path.join(SITE, os.path.basename(p)))
viewer = open(os.path.join(HERE, "..", "viewer", "index.html"), encoding="utf-8").read()
page = ('<!doctype html>\n<html lang="fr">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<style>html,body{margin:0;height:100%}body{font:14px system-ui,sans-serif}[hidden]{display:none!important}</style>\n'
        '</head>\n<body>\n' + viewer + '\n</body>\n</html>\n')
open(os.path.join(SITE, "visite.html"), "w", encoding="utf-8").write(page)
print(sorted(os.listdir(SITE)), sorted(os.listdir(os.path.join(SITE, "img"))))
