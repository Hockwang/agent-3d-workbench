"""A real paired cantilever latch for an existing A/B cut interface.

The arm is integral with A and the receiver is subtracted from B.  This is
geometric design only: snap-in force, fatigue life and print-process strain
are deliberately not inferred from a watertight static mesh.
"""

from __future__ import annotations

from backend.engine import box, mf, np


def _prism_xz(points, width):
    """Extrude an X/Z section about Y=0 in millimetre local coordinates."""
    return mf.CrossSection([points]).extrude(float(width)).rotate([90, 0, 0]).translate([0, float(width) / 2, 0])


def build_cantilever(item, place, basis):
    """Return (cut_A, cut_B, male_on_A, separate_pin).

    The hook is a sloped trapezoid on one face of an otherwise free beam.  B
    gets a narrow insertion channel and a wider terminal undercut window.
    Their assembled positions have positive single-side clearance; a rigid
    insertion path is intentionally not claimed because this mechanism needs
    controlled elastic deflection.
    """
    width = float(item["size_mm"])
    depth = float(item["depth_mm"])
    thickness = float(item["beam_thickness_mm"])
    hook = float(item["hook_mm"])
    side = float(item["size_tolerance_mm"])
    axial = float(item["depth_tolerance_mm"])
    half = thickness / 2
    # The thick root is buried 0.3 mm in A; the protrusion is one continuous
    # manifold, rather than a freestanding imported accessory.
    section = [
        (-half, -0.30),
        (half, -0.30),
        (half, depth * 0.54),
        (half + hook, depth * 0.76),
        (half + hook, depth * 0.85),
        (half, depth * 0.85),
        (half, depth),
        (-half, depth),
    ]
    arm = _prism_xz(section, width)
    # Entrance is narrow enough to retain the hook after snap-in, while the
    # terminal window provides a genuine local undercut in the receiver.
    channel = box([-half - side, -width / 2 - side, -0.40], [half + side, width / 2 + side, depth + axial + 0.30])
    latch_window = box(
        [half + side - 0.01, -width / 2 - side, depth * 0.53],
        [half + hook + side, width / 2 + side, depth * 0.90 + axial],
    )
    receiver = channel + latch_window
    center = np.asarray(item["center_mm"], dtype=float)
    return None, place(receiver, center, basis), place(arm, center, basis), None
