# Modélisation 3D

Prototype : générer une maquette 3D navigable à partir des données d'un plan d'architecte (JSON).

- `viewer/index.html` : visionneuse three.js autonome (ouvrir dans un navigateur). Vue orbitale, coupes de niveau à 1,20 m, ensoleillement, visite à pied (ZQSD/WASD + souris, ou tactile), édition et import du JSON.

## Format JSON (mètres ; x vers l'est, y vers le nord)

| Clé | Contenu |
|---|---|
| `niveaux` | `{ id, nom, altitude, hauteur }` |
| `materiaux` | `nom: { type, couleur, echelle? }` — types : enduit, peinture, beton, brique, pierre, bois, parquet, carrelage, zinc, tuile, ardoise, gazon, gravier, metal, tissu, verre |
| `murs` | `{ niveau, de:[x,y], a:[x,y], epaisseur, interieur?, materiau_ext, materiau_int, ouvertures:[{ type: porte\|fenetre\|baie, position, largeur, hauteur, allege }] }` |
| `dalles` | `{ niveau, contour:[[x,y]…], epaisseur, materiau, tremies?, altitude? }` |
| `escaliers` | `{ niveau, depart:[x,y], direction: nord\|sud\|est\|ouest, largeur, marches, giron, materiau }` |
| `toiture` | `{ type: deux_pans\|plate, niveau, pente, debord, epaisseur, materiau, materiau_sous_face, faitage? }` |
| `mobilier` | `{ niveau, type: boite\|lit\|canape\|table, position:[x,y], dimensions:[l,p,h], rotation?, materiau }` |
| `visite` | `{ depart:[x,y], orientation (° depuis le nord), niveau }` |

Un exemple complet est intégré à la visionneuse (bouton « Exemple »).
