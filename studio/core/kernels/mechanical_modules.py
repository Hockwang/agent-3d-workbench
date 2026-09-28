"""Compact physical interfaces; host contours supply the structural cheeks."""

from .mechanical_geometry import *

VERSION = "mechanical-joints/0.1"


def hex_prism(across_flats, lo, hi):
    return mf.Manifold.cylinder(hi - lo, across_flats / np.sqrt(3), across_flats / np.sqrt(3), 6).translate([0, 0, lo])


def sector(r0, r1, a0, a1, z0, z1):
    a = np.linspace(a0, a1, max(4, int(np.ceil((a1 - a0) / np.radians(2)))))
    outer = np.c_[r1 * np.cos(a), r1 * np.sin(a)]
    inner = np.c_[r0 * np.cos(a[::-1]), r0 * np.sin(a[::-1])]
    return mf.CrossSection([np.vstack([outer, inner])]).extrude(z1 - z0).translate([0, 0, z0])


def compact_pivot(radius=4.4, outer=5.4, tongue=1.6, gap=0.2, hole_radius=1.2, limits=(-0.5, 0.6)):
    if not (3.4 <= radius <= 5 and 1.3 <= tongue <= 2 and 0.1 <= gap <= 0.3 and 1.1 <= hole_radius <= 1.3):
        raise ValueError("Outside the declared uncalibrated compact-pivot envelope")
    if outer != 5.4:
        raise ValueError("This revision binds the M2x8 hardware stack to outer=5.4 mm")
    inner = tongue + gap
    fork = cyl(radius, -outer, -inner) + cyl(radius, inner, outer)
    rotor = cyl(radius - 0.25, -tongue, tongue)
    bore = cyl(hole_radius, -outer - 0.1, outer + 0.1)
    head_pocket = cyl(2.05, -outer - 0.1, -3.15)
    nut_pocket = hex_prism(4.25, 2.95, outer + 0.1)
    fork -= bore + head_pocket + nut_pocket
    rotor -= bore
    angular_gap = 0.07
    low, high = limits
    if not (0 < high - low < np.pi):
        raise ValueError("Compact stop track supports ranges below 180 degrees")
    half_lug = np.arcsin(0.6 / 2.9)
    track = sector(2.15, 3.65, low - half_lug - angular_gap, high + half_lug + angular_gap, inner - 0.05, inner + 0.85)
    loading = box([2.0, -0.82, inner - 0.05], [radius + 0.3, 0.82, inner + 0.85]).rotate(
        [0, 0, float(np.degrees((low + high) / 2))]
    )
    fork -= track + loading
    rotor += cyl(0.6, tongue - 0.1, inner + 0.65).translate([2.9, 0, 0])
    # DIN 912-style M2x8 envelope: nominal head 3.8x2, shaft 2x8.
    screw = cyl(1.9, -5.3, -3.3) + cyl(1.0, -3.3, 4.7)
    nut = hex_prism(4.0, 3.05, 4.65) - cyl(1.05, 3.0, 4.7)
    return dict(
        family="compact_pivot",
        fork=fork,
        tongue=rotor,
        bore=bore,
        head_pocket=head_pocket,
        nut_pocket=nut_pocket,
        hardware={"screw_M2x8": screw, "nut_M2": nut},
        radius=radius,
        outer=outer,
        inner=inner,
        tongue_half=tongue,
        gap=gap,
        hole_radius=hole_radius,
        stop_track=track + loading,
        limits=list(limits),
        loading_angle=(low + high) / 2,
        physical_calibration="pending",
        holding="M2 clamp preload requires physical calibration",
    )


def thin_slew(radius=8.0, shaft_radius=2.5, gap=0.25):
    if not (7 <= radius <= 12 and 2 <= shaft_radius <= 3 and 0.15 <= gap <= 0.35):
        raise ValueError("Unsupported slew parameters")
    fixed = cyl(radius, -3, 0) - cyl(shaft_radius + gap, -3.1, 0.1)
    moving = cyl(radius, gap, gap + 0.6) + cyl(shaft_radius, -5.2, 3.0)
    cap = cyl(shaft_radius + 1.6, -5.2, -3.3) - cyl(shaft_radius + 0.15, -5.3, -3.2)
    return dict(
        family="thin_slew",
        parent=fixed,
        child=moving,
        cap=cap,
        radius=radius,
        shaft_radius=shaft_radius,
        gap=gap,
        physical_calibration="pending",
        holding="free rotation; bonded retaining cap",
    )


def telescopic_link(min_length=30.0, max_length=42.0, rest_length=35.0, tube_radius=2.2):
    from .mechanical_linkage import telescope

    return dict(
        family="telescopic_link",
        **telescope(min_length, max_length, rest_length, tube_radius),
        physical_calibration="pending",
    )


def catalog():
    return dict(
        version=VERSION,
        families={
            "compact_pivot": dict(dof=1, hardware=["M2x8 DIN912 screw", "M2 nut"], host_integrated=True),
            "thin_slew": dict(dof=1, hardware=[], host_integrated=True),
            "telescopic_link": dict(
                dof="one dependent translation with end pivots", hardware=[], host_integrated=False
            ),
        },
        physical_calibration="pending",
        appearance="requires explicit protected surfaces and finite machining zones",
    )
