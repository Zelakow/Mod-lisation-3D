"""Épicéa procédural (modèle de hauteur 1, axe du tronc le long de +X pour l'instanciation).

Silhouette conique étroite, contour duveteux : chaque rameau est une chaîne de touffes
d'aiguilles irrégulières, avec des rameaux secondaires ; pointes claires, cœur sombre.
"""
import math
import bpy, bmesh
import numpy as np
from mathutils import Vector, Matrix


def _foliage_material():
    m = bpy.data.materials.get("Aiguilles d'épicéa")
    if m: return m
    m = bpy.data.materials.new("Aiguilles d'épicéa")
    try: m.use_nodes = True
    except Exception: pass
    nt = m.node_tree; nt.nodes.clear(); L = nt.links.new
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tc = nt.nodes.new("ShaderNodeTexCoord"); sep = nt.nodes.new("ShaderNodeSeparateXYZ"); L(tc.outputs["Object"], sep.inputs[0])
    # rayon local (axe du tronc = X) rapporté au rayon du cône à cette hauteur → 0 au cœur, 1 en surface
    def math_(op, a=None, b_=None, va=0.0, vb=0.0):
        n = nt.nodes.new("ShaderNodeMath"); n.operation = op
        if a is not None: L(a, n.inputs[0])
        else: n.inputs[0].default_value = va
        if b_ is not None: L(b_, n.inputs[1])
        else: n.inputs[1].default_value = vb
        return n.outputs[0]
    rad = math_("SQRT", math_("ADD", math_("MULTIPLY", sep.outputs[1], sep.outputs[1]), math_("MULTIPLY", sep.outputs[2], sep.outputs[2])))
    cone = math_("ADD", math_("MULTIPLY", math_("SUBTRACT", None, sep.outputs[0], va=1.0), None, vb=0.22), None, vb=0.02)
    outer = math_("MINIMUM", math_("DIVIDE", rad, cone), None, vb=1.0)
    ao = nt.nodes.new("ShaderNodeAmbientOcclusion"); ao.inputs["Distance"].default_value = 0.6; ao.samples = 6
    nz = nt.nodes.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 60; nz.inputs["Detail"].default_value = 10
    L(tc.outputs["Object"], nz.inputs["Vector"])
    oi = nt.nodes.new("ShaderNodeObjectInfo")
    ramp = nt.nodes.new("ShaderNodeValToRGB"); cr = ramp.color_ramp
    cr.elements[0].position = 0.0; cr.elements[0].color = (0.004, 0.011, 0.003, 1)
    cr.elements[1].position = 1.0; cr.elements[1].color = (0.10, 0.19, 0.03, 1)
    e = cr.elements.new(0.6); e.color = (0.025, 0.065, 0.012, 1)
    lit = math_("MULTIPLY", math_("POWER", outer, None, vb=1.6), ao.outputs["AO"])
    lit = math_("ADD", math_("MULTIPLY", lit, None, vb=0.85), math_("MULTIPLY", nz.outputs["Fac"], None, vb=0.25))
    L(lit, ramp.inputs[0])
    hue = nt.nodes.new("ShaderNodeHueSaturation"); L(ramp.outputs[0], hue.inputs["Color"])
    L(math_("ADD", math_("MULTIPLY", oi.outputs["Random"], None, vb=0.025), None, vb=0.465), hue.inputs["Hue"])
    L(math_("ADD", math_("MULTIPLY", oi.outputs["Random"], None, vb=0.35), None, vb=0.85), hue.inputs["Value"])
    L(hue.outputs[0], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.72
    bump = nt.nodes.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = 0.9; bump.inputs["Distance"].default_value = 0.02
    fine = nt.nodes.new("ShaderNodeTexNoise"); fine.inputs["Scale"].default_value = 400; fine.inputs["Detail"].default_value = 4
    L(tc.outputs["Object"], fine.inputs["Vector"]); L(fine.outputs["Fac"], bump.inputs["Height"]); L(bump.outputs[0], b.inputs["Normal"])
    tr = nt.nodes.new("ShaderNodeBsdfTranslucent"); L(hue.outputs[0], tr.inputs["Color"])
    mx = nt.nodes.new("ShaderNodeMixShader"); mx.inputs[0].default_value = 0.18
    L(b.outputs[0], mx.inputs[1]); L(tr.outputs[0], mx.inputs[2]); L(mx.outputs[0], out.inputs[0])
    return m


def make_spruce(name, seed, collection):
    r = np.random.default_rng(seed)
    bm = bmesh.new()
    # tronc + flèche
    bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.016, radius2=0.002, depth=1.02, matrix=Matrix.Translation((0, 0, 0.51)))
    for f in bm.faces: f.material_index = 0
    def puff(center, axis, length, radius, flat=0.55):
        q = Vector((1, 0, 0)).rotation_difference(axis)
        M = Matrix.Translation(center) @ q.to_matrix().to_4x4() @ Matrix.Diagonal((length, radius, radius * flat, 1.0))
        res = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0, matrix=M)
        for v in res["verts"]:
            v.co += Vector(r.normal(0, 0.28, 3)) * radius
        faces = {f for v in res["verts"] for f in v.link_faces}
        for f in faces: f.material_index = 1
    tiers = 40
    for k in range(tiers):
        z = 0.05 + 0.88 * k / tiers + r.normal() * 0.004
        Lb = 0.215 * (1 - z) ** 0.95 + 0.018
        nb = int(r.integers(6, 9)) if k < tiers - 6 else 5
        for j in range(nb):
            az = 2 * math.pi * (j + r.random() * 0.6) / nb + k * 2.39
            droop = math.radians(-8 - 18 * r.random() - 10 * (1 - z))
            d = Vector((math.cos(az) * math.cos(droop), math.sin(az) * math.cos(droop), math.sin(droop)))
            side = Vector((-math.sin(az), math.cos(az), 0))
            L_ = Lb * (0.8 + 0.4 * r.random())
            for t in np.linspace(0.18, 0.97, 11):
                # rameau qui descend puis relève légèrement la pointe
                p = Vector((0, 0, z)) + d * (L_ * t) + Vector((0, 0, L_ * (0.06 * t * t - 0.05 * t)))
                rr = L_ * (0.12 - 0.07 * t) * (0.8 + 0.4 * r.random())
                puff(p, d + Vector((0, 0, 0.15 * t)), L_ * 0.075, rr, 0.45)
                if 0.3 < t < 0.9:   # rameaux secondaires, en arête de poisson
                    for sgn in (-1, 1):
                        if r.random() < 0.8:
                            sd_ = (d * 0.6 + side * sgn).normalized()
                            for u in (1.0, 2.1):
                                ps = p + sd_ * rr * u * 1.2 + Vector((0, 0, -rr * 0.2 * u))
                                puff(ps, sd_, L_ * 0.05, rr * (0.75 - 0.2 * u), 0.45)
    # flèche terminale
    for t in np.linspace(0.93, 1.0, 6):
        puff(Vector((0, 0, t)), Vector((0, 0, 1)), 0.012, 0.004, 1.0)
    bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(90), 3, "Y"))  # Z → X
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    bark = bpy.data.materials.get("Écorce") or bpy.data.materials.new("Écorce")
    if bark.node_tree is None or "Principled BSDF" not in bark.node_tree.nodes:
        try: bark.use_nodes = True
        except Exception: pass
    pb = bark.node_tree.nodes.get("Principled BSDF")
    if pb: pb.inputs["Base Color"].default_value = (0.06, 0.04, 0.028, 1); pb.inputs["Roughness"].default_value = 0.9
    me.materials.append(bark); me.materials.append(_foliage_material())
    for p in me.polygons: p.use_smooth = True
    ob = bpy.data.objects.new(name, me); collection.objects.link(ob)
    return ob


if __name__ == "__main__":
    # banc d'essai : un épicéa de 9 m dans une prairie, comparable à la photo de référence
    import os, sys
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    lib = bpy.data.collections.new("lib"); sc.collection.children.link(lib)
    t = make_spruce("Épicéa", 101, lib); t.location = (0, 0, -1000)
    for k, (x, y, h) in enumerate(((0, 0, 9), (-9, 14, 7), (8, 16, 8), (-16, 30, 10), (14, 34, 9), (2, 40, 11))):
        e = bpy.data.objects.new(f"inst{k}", None); e.instance_type = "COLLECTION"
        c = bpy.data.collections.new(f"c{k}") if k == 0 else bpy.data.collections["c0"]
        if k == 0:
            c.objects.link(t); lib.objects.unlink(t); t.location = (0, 0, 0)
            sc.collection.children.link(c); vl = bpy.context.view_layer.layer_collection.children[c.name]; vl.exclude = True
        e.instance_collection = c; e.location = (x, y, 0); e.scale = (h,) * 3; e.rotation_euler = (k * 1.7, math.radians(-90), 0)
        sc.collection.objects.link(e)
    bpy.ops.mesh.primitive_plane_add(size=400); g = bpy.context.active_object
    gm = bpy.data.materials.new("sol"); gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.06, 0.1, 0.02, 1); g.data.materials.append(gm)
    w = bpy.data.worlds.new("w"); sc.world = w; nt = w.node_tree; nt.nodes.clear()
    sky = nt.nodes.new("ShaderNodeTexSky"); sky.sky_type = "MULTIPLE_SCATTERING"; sky.sun_disc = False; sky.sun_elevation = math.radians(40); sky.aerosol_density = 0.3
    bg = nt.nodes.new("ShaderNodeBackground"); bg.inputs[1].default_value = 0.45; o = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(sky.outputs[0], bg.inputs[0]); nt.links.new(bg.outputs[0], o.inputs[0])
    sd = bpy.data.lights.new("s", "SUN"); sd.energy = 4.6; sd.angle = math.radians(0.8); so = bpy.data.objects.new("s", sd); sc.collection.objects.link(so)
    so.rotation_euler = (math.radians(50), 0, math.radians(30))
    cd = bpy.data.cameras.new("c"); cd.lens = 35; co = bpy.data.objects.new("c", cd); sc.collection.objects.link(co)
    co.location = (0, -15, 3.2); co.rotation_euler = (math.radians(92), 0, 0); sc.camera = co
    sc.render.engine = "CYCLES"; sc.cycles.samples = 48; sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y = 800, 800
    sc.view_settings.view_transform = "AgX"
    sc.render.filepath = sys.argv[-1]; bpy.ops.render.render(write_still=True)
