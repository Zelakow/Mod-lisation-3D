#!/bin/bash
# Rendus définitifs des deux variantes + post-traitement photo
cd "$(dirname "$0")"
PY=/opt/bvenv/bin/python
for v in traditionnel contemporain; do
  $PY blender_scene.py $v --cams sud,aerienne,nord,interieur 2>&1 | grep --line-buffered -E "rendu |enregistr|Error|Traceback|line [0-9]"
  for k in sud aerienne nord interieur; do
    flag=""; [ $k = interieur ] && flag="--interieur"
    $PY post.py out/brut_${v}_${k}.png out/rendu_${v}_${k}.jpg $flag
  done
done
echo FINI
