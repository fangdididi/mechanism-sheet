#!/usr/bin/env python3
"""mech.py - solve and check a mechanism sheet before anything is drawn.

Zero dependencies (Python 3.8+ standard library only).

A sheet is a JSON file: one driver angle, a list of standard elements
(slider_crank, four_bar, gear_pair, rack_pinion, belt), optional claims to
test. Every element reads its input angle either from the driver or from the
output of an earlier element, so one number poses the whole machine.

Commands
  solve  SHEET [--steps N] [--csv FILE] [--json]   checks + readouts (+ pose table)
  claims SHEET [--json]                            test stated numbers against the model
  sheet  SHEET --out FILE.svg [--frames N]         contact sheet of key poses (SVG)
  keys   SHEET [--json]                            key poses worth showing (beats)

Exit codes: 0 all PASS/MATCH, 1 at least one WARN, 2 at least one FAIL/OFF,
3 the sheet itself is invalid.
"""
import argparse
import csv
import json
import math
import sys

RANK = {"PASS": 0, "WARN": 1, "FAIL": 2}
SOURCE_GRADES = ("measured", "drawing", "datasheet", "derived", "estimated", "guess")
KINDS = ("slider_crank", "four_bar", "gear_pair", "rack_pinion", "belt")


class SheetError(ValueError):
    pass


# ---------------------------------------------------------------- loading

def load_sheet(path_or_dict):
    if not isinstance(path_or_dict, (str, bytes)) and not hasattr(path_or_dict, "__fspath__"):
        data = path_or_dict
    else:
        with open(path_or_dict, encoding="utf-8") as fh:
            data = json.load(fh)
    validate(data)
    return data


def _num(part, key, positive=True, required=True, default=None):
    if key not in part:
        if required:
            raise SheetError("%s: missing '%s'" % (part.get("id", "?"), key))
        return default
    v = part[key]
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise SheetError("%s: '%s' must be a number" % (part.get("id", "?"), key))
    if positive and v <= 0:
        raise SheetError("%s: '%s' must be > 0" % (part.get("id", "?"), key))
    return float(v)


REQUIRED = {
    "slider_crank": ("crank", "rod"),
    "four_bar": ("ground", "crank", "coupler", "rocker"),
    "gear_pair": ("module", "z1", "z2"),
    "rack_pinion": ("module", "z"),
    "belt": ("d1", "d2"),
}


def validate(data):
    if not isinstance(data, dict):
        raise SheetError("sheet must be a JSON object")
    parts = data.get("parts")
    if not isinstance(parts, list) or not parts:
        raise SheetError("sheet needs a non-empty 'parts' list")
    seen = set()
    for p in parts:
        if not isinstance(p, dict):
            raise SheetError("every part must be an object")
        pid = p.get("id")
        if not pid or not isinstance(pid, str):
            raise SheetError("every part needs a string 'id'")
        if pid in seen:
            raise SheetError("duplicate part id '%s'" % pid)
        kind = p.get("type")
        if kind not in KINDS:
            raise SheetError("%s: unknown type '%s' (use one of %s)" % (pid, kind, ", ".join(KINDS)))
        for k in REQUIRED[kind]:
            _num(p, k)
        if kind == "slider_crank":
            _num(p, "offset", positive=False, required=False)
        if kind == "four_bar" and p.get("branch", "open") not in ("open", "crossed"):
            raise SheetError("%s: branch must be 'open' or 'crossed'" % pid)
        src = p.get("input", "driver")
        if src != "driver":
            ref = src.split(".")[0]
            if ref not in seen:
                raise SheetError("%s: input '%s' must name an earlier part" % (pid, src))
        grade = p.get("source")
        if grade is not None and grade not in SOURCE_GRADES:
            raise SheetError("%s: source must be one of %s" % (pid, ", ".join(SOURCE_GRADES)))
        seen.add(pid)
    drv = data.get("driver", {})
    if not isinstance(drv, dict):
        raise SheetError("'driver' must be an object")
    lo, hi = drv.get("from", 0), drv.get("to", 360)
    if not all(isinstance(x, (int, float)) for x in (lo, hi)) or hi <= lo:
        raise SheetError("driver needs from < to (degrees)")
    for c in data.get("claims", []):
        if not isinstance(c, dict) or "part" not in c or "quantity" not in c or "value" not in c:
            raise SheetError("each claim needs part, quantity, value")


# ---------------------------------------------------------------- element maths

def slider_crank_pose(r, L, e, theta_deg):
    """Return slider position x (from crank centre along the line) and rod
    angle in degrees, or None if the rod cannot reach the line."""
    t = math.radians(theta_deg)
    h = r * math.sin(t) - e
    if abs(h) > L:
        return None
    x = r * math.cos(t) + math.sqrt(L * L - h * h)
    phi = math.degrees(math.asin(h / L))
    return x, phi, (r * math.cos(t), r * math.sin(t))


def circle_intersections(c0, r0, c1, r1):
    dx, dy = c1[0] - c0[0], c1[1] - c0[1]
    d = math.hypot(dx, dy)
    if d == 0 or d > r0 + r1 + 1e-9 or d < abs(r0 - r1) - 1e-9:
        return None
    a = (r0 * r0 - r1 * r1 + d * d) / (2 * d)
    h = math.sqrt(max(r0 * r0 - a * a, 0.0))
    mx, my = c0[0] + a * dx / d, c0[1] + a * dy / d
    p1 = (mx + h * dy / d, my - h * dx / d)
    p2 = (mx - h * dy / d, my + h * dx / d)
    return p1, p2


def four_bar_pose(g, a, b, c, theta_deg, branch="open"):
    """Crank pivot O2 at (0,0), rocker pivot O4 at (g,0). Returns dict with
    crank pin A, coupler-rocker joint B, rocker angle, transmission angle."""
    t = math.radians(theta_deg)
    A = (a * math.cos(t), a * math.sin(t))
    D = (g, 0.0)
    pts = circle_intersections(A, b, D, c)
    if pts is None:
        return None
    # open branch: B on the upper side relative to line A->D (left of A->D)
    def side(p):
        return (D[0] - A[0]) * (p[1] - A[1]) - (D[1] - A[1]) * (p[0] - A[0])
    up = [p for p in pts if side(p) >= 0]
    dn = [p for p in pts if side(p) < 0]
    if branch == "open":
        B = up[0] if up else pts[0]
    else:
        B = dn[0] if dn else pts[1]
    rocker = math.degrees(math.atan2(B[1], B[0] - g))
    ad2 = (D[0] - A[0]) ** 2 + (D[1] - A[1]) ** 2
    cos_mu = (b * b + c * c - ad2) / (2 * b * c)
    mu = math.degrees(math.acos(max(-1.0, min(1.0, cos_mu))))
    return {"A": A, "B": B, "rocker_deg": rocker, "mu_deg": mu}


def grashof(g, a, b, c):
    links = {"ground": g, "crank": a, "coupler": b, "rocker": c}
    vals = sorted(links.values())
    s, l = vals[0], vals[-1]
    p, q = vals[1], vals[2]
    shortest = min(links, key=lambda k: links[k])
    lhs, rhs = s + l, p + q
    if abs(lhs - rhs) < 1e-9 * max(1.0, rhs):
        return "change-point", shortest
    if lhs > rhs:
        return "non-grashof (triple rocker)", shortest
    if shortest == "crank":
        return "crank-rocker", shortest
    if shortest == "ground":
        return "double-crank", shortest
    if shortest == "rocker":
        return "rocker-crank", shortest
    return "double-rocker", shortest


def pitch_diameter(module, z):
    return module * z


# ---------------------------------------------------------------- solving

def _steps(data, steps):
    drv = data.get("driver", {})
    lo, hi = float(drv.get("from", 0)), float(drv.get("to", 360))
    n = int(steps or drv.get("steps", 72))
    if n < 4:
        raise SheetError("need at least 4 steps")
    return [lo + (hi - lo) * i / n for i in range(n + 1)]


def _input_angle(part, outputs, theta):
    src = part.get("input", "driver")
    if src == "driver":
        return theta
    return outputs.get(src.split(".")[0])


def solve(data, steps=None):
    """Pose every part at every driver step. Returns rows (list of dicts)."""
    rows = []
    for theta in _steps(data, steps):
        row = {"driver_deg": theta}
        outputs = {}
        for p in data["parts"]:
            pid, kind = p["id"], p["type"]
            ang = _input_angle(p, outputs, theta)
            if ang is None:
                row[pid] = None
                outputs[pid] = None
                continue
            ang = ang + float(p.get("phase", 0))
            if kind == "slider_crank":
                res = slider_crank_pose(float(p["crank"]), float(p["rod"]), float(p.get("offset", 0)), ang)
                row[pid] = None if res is None else {"x": res[0], "rod_deg": res[1], "pin": res[2], "in_deg": ang}
                outputs[pid] = None if res is None else ang  # passes its crank angle on
            elif kind == "four_bar":
                res = four_bar_pose(float(p["ground"]), float(p["crank"]), float(p["coupler"]),
                                    float(p["rocker"]), ang, p.get("branch", "open"))
                if res is not None:
                    res["in_deg"] = ang
                row[pid] = res
                outputs[pid] = None if res is None else res["rocker_deg"]
            elif kind == "gear_pair":
                ratio = float(p["z1"]) / float(p["z2"])
                sign = 1.0 if p.get("internal") else -1.0
                out = sign * ang * ratio
                row[pid] = {"in_deg": ang, "out_deg": out}
                outputs[pid] = out
            elif kind == "rack_pinion":
                d = pitch_diameter(float(p["module"]), float(p["z"]))
                s = math.radians(ang) * d / 2.0
                row[pid] = {"in_deg": ang, "travel": s}
                outputs[pid] = ang
            elif kind == "belt":
                ratio = float(p["d1"]) / float(p["d2"])
                sign = -1.0 if p.get("crossed") else 1.0
                out = sign * ang * ratio
                row[pid] = {"in_deg": ang, "out_deg": out}
                outputs[pid] = out
        rows.append(row)
    return rows


def _rel_off(stated, computed):
    if computed == 0:
        return abs(stated)
    return abs(stated - computed) / abs(computed)


def readouts_and_checks(data, rows):
    """Return (readouts per part, list of checks)."""
    out, checks = {}, []

    def chk(pid, name, verdict, detail):
        checks.append({"part": pid, "check": name, "verdict": verdict, "detail": detail})

    rpm = data.get("driver", {}).get("rpm")
    span = rows[-1]["driver_deg"] - rows[0]["driver_deg"]
    for p in data["parts"]:
        pid, kind = p["id"], p["type"]
        series = [r[pid] for r in rows]
        ok = [s for s in series if s is not None]
        missing = [r["driver_deg"] for r in rows if r[pid] is None]
        ro = {}
        if p.get("source") in ("guess", None):
            chk(pid, "dimension source", "WARN",
                "dimensions graded '%s'; find a drawing, datasheet or measurement before labels quote them"
                % (p.get("source") or "ungraded"))
        elif p["source"] == "estimated":
            chk(pid, "dimension source", "WARN",
                "dimensions estimated (scaled from a photo or similar); mark every quoted number as approximate")
        else:
            chk(pid, "dimension source", "PASS", "graded '%s'" % p["source"])
        if missing and kind in ("slider_crank", "four_bar"):
            first, last = missing[0], missing[-1]
            chk(pid, "assembles over the whole input range", "FAIL",
                "cannot close at %d of %d steps (e.g. %.1f deg ... %.1f deg); change a length, the range, or the type"
                % (len(missing), len(rows), first, last))
        elif kind in ("slider_crank", "four_bar"):
            chk(pid, "assembles over the whole input range", "PASS", "closes at all %d steps" % len(rows))
        if kind == "slider_crank" and ok:
            r, L, e = float(p["crank"]), float(p["rod"]), float(p.get("offset", 0))
            xs = [s["x"] for s in ok]
            ro["stroke"] = max(xs) - min(xs)
            ro["x_max"] = max(xs)
            ro["x_min"] = min(xs)
            ro["max_rod_angle_deg"] = max(abs(s["rod_deg"]) for s in ok)
            ro["rod_to_crank"] = L / r
            if not missing:
                ro["stroke_exact"] = (math.sqrt((L + r) ** 2 - e * e) - math.sqrt((L - r) ** 2 - e * e)
                                      if L - r > abs(e) else None)
                # crank angles at dead centres
                tdc = math.degrees(math.asin(e / (L + r)))
                bdc = 180 + math.degrees(math.asin(e / (L - r))) if L - r > abs(e) else None
                ro["dead_centre_deg"] = [tdc, bdc]
                if bdc is not None and span >= 359.999:
                    fwd = (bdc - tdc) % 360
                    ro["time_ratio"] = max(fwd, 360 - fwd) / min(fwd, 360 - fwd)
            lam = L / r
            if lam < 2.5:
                chk(pid, "rod length ratio", "WARN", "rod/crank = %.2f; below about 2.5 the rod swings hard and side load on the slider climbs" % lam)
            else:
                chk(pid, "rod length ratio", "PASS", "rod/crank = %.2f" % lam)
            if rpm and not missing:
                w = 2 * math.pi * float(rpm) / 60.0
                speeds = []
                for i in range(1, len(ok)):
                    dth = math.radians(ok[i]["in_deg"] - ok[i - 1]["in_deg"])
                    if dth:
                        speeds.append(abs(ok[i]["x"] - ok[i - 1]["x"]) / dth * w)
                ro["peak_slider_speed_per_s"] = max(speeds) if speeds else 0.0
                ro["mean_slider_speed_per_s"] = 2 * ro["stroke"] * float(rpm) / 60.0
        if kind == "four_bar":
            g, a, b, c = (float(p[k]) for k in ("ground", "crank", "coupler", "rocker"))
            cls, shortest = grashof(g, a, b, c)
            ro["grashof_class"] = cls
            ro["shortest_link"] = shortest
            if p.get("expect_full_rotation", True) and span >= 359.999 and cls not in ("crank-rocker", "double-crank"):
                chk(pid, "input can turn fully", "FAIL" if missing else "WARN",
                    "class is %s: the input link cannot make a full turn" % cls)
            elif span >= 359.999:
                chk(pid, "input can turn fully", "PASS", "class %s" % cls)
            if ok:
                rock = [s["rocker_deg"] for s in ok]
                ro["output_swing_deg"] = max(rock) - min(rock)
                ro["output_min_deg"] = min(rock)
                ro["output_max_deg"] = max(rock)
                mus = [s["mu_deg"] for s in ok]
                worst = min(min(m, 180 - m) for m in mus)
                ro["worst_transmission_deg"] = worst
                limit = float(p.get("min_transmission", 40))
                if worst < 20:
                    v = "FAIL"
                elif worst < limit:
                    v = "WARN"
                else:
                    v = "PASS"
                chk(pid, "transmission angle", v,
                    "worst %.1f deg (aim >= %.0f; under 20 the linkage jams or chatters)" % (worst, limit))
        if kind == "gear_pair":
            m, z1, z2 = float(p["module"]), float(p["z1"]), float(p["z2"])
            d1, d2 = pitch_diameter(m, z1), pitch_diameter(m, z2)
            ro["pitch_d1"], ro["pitch_d2"] = d1, d2
            ro["ratio"] = z2 / z1
            cd = (d2 - d1) / 2 if p.get("internal") else (d1 + d2) / 2
            ro["centre_distance"] = cd
            if "centre_distance" in p:
                stated = float(p["centre_distance"])
                off = _rel_off(stated, cd)
                chk(pid, "centre distance matches teeth", "PASS" if off <= 0.005 else "FAIL",
                    "stated %.3f, teeth give %.3f" % (stated, cd))
            if "module2" in p and float(p["module2"]) != m:
                chk(pid, "same module on both gears", "FAIL",
                    "module %.3g vs %.3g: these gears cannot mesh" % (m, float(p["module2"])))
            if p.get("internal") and z2 - z1 < 10:
                chk(pid, "internal tooth difference", "WARN", "ring has only %d more teeth than pinion; interference likely" % (z2 - z1))
            smallest = min(z1, z2)
            if smallest < 17 and not p.get("profile_shifted"):
                chk(pid, "undercut", "WARN", "%d teeth at 20 deg pressure angle undercuts unless profile-shifted" % smallest)
            else:
                chk(pid, "undercut", "PASS", "smallest gear %d teeth" % smallest)
            if any(int(x) != x for x in (z1, z2)):
                chk(pid, "whole teeth", "FAIL", "tooth counts must be whole numbers")
            g = math.gcd(int(z1), int(z2))
            ro["hunting_tooth"] = g == 1
        if kind == "rack_pinion":
            m, z = float(p["module"]), float(p["z"])
            d = pitch_diameter(m, z)
            ro["pitch_d"] = d
            ro["travel_per_turn"] = math.pi * d
            if ok:
                tr = [s["travel"] for s in ok]
                ro["travel_over_range"] = max(tr) - min(tr)
            if "travel" in p:
                rot = float(p.get("rotation_deg", span))
                expect = math.pi * d * rot / 360.0
                stated = float(p["travel"])
                off = _rel_off(stated, expect)
                chk(pid, "travel matches pinion turn", "PASS" if off <= 0.01 else "FAIL",
                    "stated %.3f; %.0f deg of a %.3f pitch circle gives %.3f" % (stated, rot, d, expect))
        if kind == "belt":
            d1, d2 = float(p["d1"]), float(p["d2"])
            ro["ratio"] = d2 / d1
            ro["direction"] = "reversed" if p.get("crossed") else "same"
            if "centre_distance" in p:
                C = float(p["centre_distance"])
                if C <= (d1 + d2) / 2:
                    chk(pid, "pulleys clear each other", "FAIL", "centre distance %.3g <= (d1+d2)/2 = %.3g" % (C, (d1 + d2) / 2))
                else:
                    ro["belt_length"] = 2 * C + math.pi * (d1 + d2) / 2 + (d2 - d1) ** 2 / (4 * C)
                    wrap = 180 - 2 * math.degrees(math.asin((d2 - d1) / (2 * C)))
                    ro["small_pulley_wrap_deg"] = min(wrap, 360 - wrap)
                    chk(pid, "wrap on small pulley", "PASS" if ro["small_pulley_wrap_deg"] >= 120 else "WARN",
                        "%.0f deg (below about 120 the belt slips)" % ro["small_pulley_wrap_deg"])
        out[pid] = ro
    return out, checks


def overall(checks):
    worst = "PASS"
    for c in checks:
        if RANK[c["verdict"]] > RANK[worst]:
            worst = c["verdict"]
    return worst


# ---------------------------------------------------------------- claims

ALIASES = {"travel": ("travel_over_range", "travel_per_turn"), "swing": ("output_swing_deg",),
           "ratio": ("ratio",), "stroke": ("stroke",)}


def test_claims(data, readouts):
    results = []
    for c in data.get("claims", []):
        pid, q, val = c["part"], c["quantity"], float(c["value"])
        tol = float(c.get("tol", 0.01))
        ro = readouts.get(pid)
        keys = (q,) + ALIASES.get(q, ())
        got = None
        if ro is not None:
            for k in keys:
                if isinstance(ro.get(k), (int, float)) and not isinstance(ro.get(k), bool):
                    got, q_used = float(ro[k]), k
                    break
        if got is None:
            results.append({"part": pid, "quantity": q, "stated": val, "model": None, "verdict": "UNKNOWN",
                            "detail": "the model has no '%s' for %s" % (q, pid), "said_by": c.get("said_by")})
            continue
        off = _rel_off(val, got)
        verdict = "MATCH" if off <= tol else "OFF"
        results.append({"part": pid, "quantity": q_used, "stated": val, "model": round(got, 6), "verdict": verdict,
                        "detail": "%.1f%% from the model (tolerance %.1f%%)" % (off * 100, tol * 100),
                        "said_by": c.get("said_by")})
    return results


# ---------------------------------------------------------------- key poses

def key_poses(data, rows):
    """Driver angles worth a beat: dead centres, limit positions, worst
    transmission, fastest slider. Each with a reason."""
    keys = []
    for p in data["parts"]:
        pid, kind = p["id"], p["type"]
        pts = [(r["driver_deg"], r[pid]) for r in rows if r[pid] is not None]
        if len(pts) < 3:
            continue
        if kind == "slider_crank":
            hi = max(pts, key=lambda t: t[1]["x"])
            lo = min(pts, key=lambda t: t[1]["x"])
            keys.append({"driver_deg": hi[0], "part": pid, "why": "slider furthest out (outer dead centre)"})
            keys.append({"driver_deg": lo[0], "part": pid, "why": "slider furthest in (inner dead centre)"})
            best, bv = None, -1
            for i in range(1, len(pts) - 1):
                v = abs(pts[i + 1][1]["x"] - pts[i - 1][1]["x"])
                if v > bv:
                    best, bv = pts[i][0], v
            if best is not None:
                keys.append({"driver_deg": best, "part": pid, "why": "slider moving fastest"})
        if kind == "four_bar":
            hi = max(pts, key=lambda t: t[1]["rocker_deg"])
            lo = min(pts, key=lambda t: t[1]["rocker_deg"])
            keys.append({"driver_deg": hi[0], "part": pid, "why": "output at one limit"})
            keys.append({"driver_deg": lo[0], "part": pid, "why": "output at the other limit"})
            w = min(pts, key=lambda t: min(t[1]["mu_deg"], 180 - t[1]["mu_deg"]))
            keys.append({"driver_deg": w[0], "part": pid, "why": "worst transmission angle (where it would jam first)"})
    keys.sort(key=lambda k: k["driver_deg"])
    return keys


# ---------------------------------------------------------------- SVG sheet

def _frame_svg(data, row, ox, oy, size):
    """Draw slider cranks and four-bars of one row into a size x size cell."""
    els = []
    drawable = [p for p in data["parts"] if p["type"] in ("slider_crank", "four_bar")]
    if not drawable:
        return els
    lane = size / len(drawable)
    for i, p in enumerate(drawable):
        s = row[p["id"]]
        cy = oy + lane * (i + 0.5)
        if p["type"] == "slider_crank":
            r, L = float(p["crank"]), float(p["rod"])
            reach = r + L + r * 0.6
            k = (size * 0.86) / (reach + r)
            cx = ox + size * 0.07 + r * k
            els.append('<circle cx="%.1f" cy="%.1f" r="3" fill="#222"/>' % (cx, cy))
            gy = cy - float(p.get("offset", 0)) * k
            els.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#bbb" stroke-dasharray="3 3"/>' % (cx + (L - r) * k * 0.9, gy, cx + reach * k, gy))
            if s is None:
                els.append('<text x="%.1f" y="%.1f" font-size="11" fill="#b00">no fit</text>' % (cx + 10, cy))
                continue
            px, py = cx + s["pin"][0] * k, cy - s["pin"][1] * k
            sx, sy = cx + s["x"] * k, cy + float(p.get("offset", 0)) * k * -1
            els.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#222" stroke-width="3"/>' % (cx, cy, px, py))
            els.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#d2552b" stroke-width="2.5"/>' % (px, py, sx, sy))
            els.append('<rect x="%.1f" y="%.1f" width="14" height="10" fill="#555"/>' % (sx - 7, sy - 5))
        else:
            g, a, b, c = (float(p[k]) for k in ("ground", "crank", "coupler", "rocker"))
            span = g + max(a, c) * 2
            k = (size * 0.8) / span
            x0 = ox + size * 0.1 + max(a, c) * k * 0.5
            els.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#999" stroke-dasharray="3 3"/>' % (x0, cy, x0 + g * k, cy))
            if s is None:
                els.append('<text x="%.1f" y="%.1f" font-size="11" fill="#b00">no fit</text>' % (x0 + 4, cy - 6))
                continue
            A = (x0 + s["A"][0] * k, cy - s["A"][1] * k)
            B = (x0 + s["B"][0] * k, cy - s["B"][1] * k)
            D = (x0 + g * k, cy)
            els.append('<polyline points="%.1f,%.1f %.1f,%.1f %.1f,%.1f %.1f,%.1f" fill="none" stroke="#222" stroke-width="2.5"/>'
                       % (x0, cy, A[0], A[1], B[0], B[1], D[0], D[1]))
            els.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#d2552b" stroke-width="3"/>' % (B[0], B[1], D[0], D[1]))
    return els


def render_sheet(data, rows, frames=8, cols=4, size=220, angles=None):
    if frames < 1:
        raise SheetError("frames must be >= 1")
    span = rows[-1]["driver_deg"] - rows[0]["driver_deg"]
    if angles:
        idx = [min(range(len(rows)), key=lambda j: abs(rows[j]["driver_deg"] - a)) for a in angles]
    elif span >= 359.999:
        # a full turn: the last row repeats the first, so spread over the rest
        idx = [round(i * (len(rows) - 1) / frames) for i in range(frames)]
    else:
        idx = [round(i * (len(rows) - 1) / max(frames - 1, 1)) for i in range(frames)] if frames > 1 else [0]
    nrows = (len(idx) + cols - 1) // cols
    W, H = cols * size, nrows * (size + 22)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" font-family="sans-serif">' % (W, H, W, H),
           '<rect width="100%" height="100%" fill="#f6f4ef"/>']
    for n, i in enumerate(idx):
        ox, oy = (n % cols) * size, (n // cols) * (size + 22)
        out.append('<rect x="%d" y="%d" width="%d" height="%d" fill="none" stroke="#ddd"/>' % (ox, oy, size, size + 22))
        out.extend(_frame_svg(data, rows[i], ox, oy, size))
        out.append('<text x="%d" y="%d" font-size="12" fill="#333">driver = %.1f deg</text>' % (ox + 8, oy + size + 15, rows[i]["driver_deg"]))
    out.append("</svg>")
    return "\n".join(out)


# ---------------------------------------------------------------- pose table

def flat_rows(data, rows):
    flat = []
    for r in rows:
        f = {"driver_deg": round(r["driver_deg"], 6)}
        for p in data["parts"]:
            pid, s = p["id"], r[p["id"]]
            if p["type"] == "slider_crank":
                f[pid + ".x"] = None if s is None else round(s["x"], 6)
                f[pid + ".rod_deg"] = None if s is None else round(s["rod_deg"], 6)
            elif p["type"] == "four_bar":
                f[pid + ".out_deg"] = None if s is None else round(s["rocker_deg"], 6)
                f[pid + ".mu_deg"] = None if s is None else round(s["mu_deg"], 6)
            elif p["type"] == "rack_pinion":
                f[pid + ".travel"] = None if s is None else round(s["travel"], 6)
            else:
                f[pid + ".out_deg"] = None if s is None else round(s["out_deg"], 6)
        flat.append(f)
    return flat


def write_csv(path, flat):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(flat[0].keys()))
        w.writeheader()
        for f in flat:
            w.writerow({k: ("" if v is None else v) for k, v in f.items()})


# ---------------------------------------------------------------- CLI

def _fmt(v):
    if isinstance(v, float):
        return "%.4g" % v
    if isinstance(v, list):
        return "[" + ", ".join("-" if x is None else "%.4g" % x for x in v) + "]"
    return str(v)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mech.py", description="Solve and check a mechanism sheet.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("solve"); s.add_argument("sheet"); s.add_argument("--steps", type=int)
    s.add_argument("--csv"); s.add_argument("--json", action="store_true")
    c = sub.add_parser("claims"); c.add_argument("sheet"); c.add_argument("--steps", type=int); c.add_argument("--json", action="store_true")
    k = sub.add_parser("keys"); k.add_argument("sheet"); k.add_argument("--steps", type=int); k.add_argument("--json", action="store_true")
    v = sub.add_parser("sheet"); v.add_argument("sheet"); v.add_argument("--out", required=True)
    v.add_argument("--frames", type=int, default=8); v.add_argument("--steps", type=int)
    v.add_argument("--keys", action="store_true", help="draw the key poses instead of evenly spaced frames")
    a = ap.parse_args(argv)
    try:
        data = load_sheet(a.sheet)
        rows = solve(data, a.steps)
    except (SheetError, OSError, json.JSONDecodeError) as e:
        print("invalid sheet: %s" % e, file=sys.stderr)
        return 3
    readouts, checks = readouts_and_checks(data, rows)
    if a.cmd == "solve":
        verdict = overall(checks)
        if a.csv:
            write_csv(a.csv, flat_rows(data, rows))
        if a.json:
            print(json.dumps({"verdict": verdict, "readouts": readouts, "checks": checks}, indent=1))
        else:
            print("MECHANISM SHEET: %s   verdict %s" % (data.get("name", "(unnamed)"), verdict))
            for pid, ro in readouts.items():
                print("\n[%s]" % pid)
                for key, val in ro.items():
                    print("  %-26s %s" % (key, _fmt(val)))
            print("\nchecks")
            for ch in checks:
                print("  %-4s %-12s %-38s %s" % (ch["verdict"], ch["part"], ch["check"], ch["detail"]))
            if a.csv:
                print("\npose table -> %s (%d rows)" % (a.csv, len(rows)))
        return RANK[verdict]
    if a.cmd == "claims":
        res = test_claims(data, readouts)
        if a.json:
            print(json.dumps(res, indent=1))
        else:
            if not res:
                print("no claims in the sheet")
            for r in res:
                who = (" (" + r["said_by"] + ")") if r.get("said_by") else ""
                print("  %-7s %s.%s stated %s, model %s - %s%s" % (r["verdict"], r["part"], r["quantity"], _fmt(r["stated"]),
                                                              "-" if r["model"] is None else _fmt(r["model"]), r["detail"], who))
        if any(r["verdict"] == "OFF" for r in res):
            return 2
        return 1 if any(r["verdict"] == "UNKNOWN" for r in res) else 0
    if a.cmd == "keys":
        ks = key_poses(data, rows)
        if a.json:
            print(json.dumps(ks, indent=1))
        else:
            for kp in ks:
                print("  %7.1f deg  %-12s %s" % (kp["driver_deg"], kp["part"], kp["why"]))
        return 0
    if a.cmd == "sheet":
        try:
            angles = [kp["driver_deg"] for kp in key_poses(data, rows)] if a.keys else None
            svg = render_sheet(data, rows, a.frames, angles=angles)
        except SheetError as e:
            print("invalid sheet: %s" % e, file=sys.stderr)
            return 3
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(svg)
        print("contact sheet -> %s (%d frames)" % (a.out, len(angles) if angles else a.frames))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
