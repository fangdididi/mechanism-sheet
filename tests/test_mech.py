import io
import json
import math
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import mech  # noqa: E402

EX = os.path.join(HERE, "..", "examples")


def sheet(parts, claims=None, **driver):
    d = {"from": 0, "to": 360, "steps": 72}
    d.update(driver)
    s = {"name": "t", "driver": d, "parts": parts}
    if claims is not None:
        s["claims"] = claims
    return s


def sc(**kw):
    p = {"id": "p", "type": "slider_crank", "crank": 25, "rod": 100, "source": "drawing"}
    p.update(kw)
    return p


def fb(**kw):
    p = {"id": "w", "type": "four_bar", "ground": 300, "crank": 60, "coupler": 280, "rocker": 120, "source": "drawing"}
    p.update(kw)
    return p


def run(data):
    rows = mech.solve(mech.load_sheet(data))
    ro, checks = mech.readouts_and_checks(data, rows)
    return rows, ro, checks


def verdict_of(checks, name, part=None):
    for c in checks:
        if c["check"] == name and (part is None or c["part"] == part):
            return c["verdict"]
    return None


def cli(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = mech.main(args)
    return code, out.getvalue(), err.getvalue()


class Validation(unittest.TestCase):
    def bad(self, data):
        with self.assertRaises(mech.SheetError):
            mech.load_sheet(data)

    def test_needs_parts(self):
        self.bad({"parts": []})

    def test_not_object(self):
        self.bad([])

    def test_unknown_type(self):
        self.bad(sheet([{"id": "x", "type": "cam"}]))

    def test_missing_dimension(self):
        self.bad(sheet([{"id": "x", "type": "slider_crank", "crank": 10}]))

    def test_negative_length(self):
        self.bad(sheet([sc(crank=-3)]))

    def test_bool_is_not_number(self):
        self.bad(sheet([sc(rod=True)]))

    def test_duplicate_id(self):
        self.bad(sheet([sc(), sc()]))

    def test_input_must_be_earlier(self):
        self.bad(sheet([sc(input="g.out"), {"id": "g", "type": "gear_pair", "module": 1, "z1": 10, "z2": 20}]))

    def test_bad_branch(self):
        self.bad(sheet([fb(branch="up")]))

    def test_bad_source_grade(self):
        self.bad(sheet([sc(source="vibes")]))

    def test_driver_range(self):
        self.bad(sheet([sc()], **{"from": 90, "to": 10}))

    def test_claim_shape(self):
        self.bad(sheet([sc()], claims=[{"part": "p"}]))

    def test_offset_may_be_negative(self):
        mech.load_sheet(sheet([sc(offset=-5)]))


class SliderCrank(unittest.TestCase):
    def test_pose_at_tdc(self):
        x, phi, _ = mech.slider_crank_pose(25, 100, 0, 0)
        self.assertAlmostEqual(x, 125)
        self.assertAlmostEqual(phi, 0)

    def test_pose_at_bdc(self):
        x, _, _ = mech.slider_crank_pose(25, 100, 0, 180)
        self.assertAlmostEqual(x, 75)

    def test_pose_at_90(self):
        x, phi, _ = mech.slider_crank_pose(25, 100, 0, 90)
        self.assertAlmostEqual(x, math.sqrt(100 ** 2 - 25 ** 2))
        self.assertAlmostEqual(phi, math.degrees(math.asin(0.25)))

    def test_inline_stroke_is_twice_crank(self):
        _, ro, _ = run(sheet([sc()]))
        self.assertAlmostEqual(ro["p"]["stroke"], 50, places=6)
        self.assertAlmostEqual(ro["p"]["stroke_exact"], 50, places=6)

    def test_offset_stroke_longer_and_quick_return(self):
        _, ro, _ = run(sheet([sc(offset=20)], steps=720))
        self.assertGreater(ro["p"]["stroke_exact"], 50)
        self.assertGreater(ro["p"]["time_ratio"], 1.0)

    def test_inline_time_ratio_is_one(self):
        _, ro, _ = run(sheet([sc()]))
        self.assertAlmostEqual(ro["p"]["time_ratio"], 1.0)

    def test_rod_too_short_fails_assembly(self):
        _, _, checks = run(sheet([sc(rod=20)]))
        self.assertEqual(verdict_of(checks, "assembles over the whole input range"), "FAIL")
        self.assertEqual(mech.overall(checks), "FAIL")

    def test_short_rod_ratio_warns(self):
        _, _, checks = run(sheet([sc(rod=55)]))
        self.assertEqual(verdict_of(checks, "rod length ratio"), "WARN")

    def test_good_rod_ratio_passes(self):
        _, _, checks = run(sheet([sc()]))
        self.assertEqual(verdict_of(checks, "rod length ratio"), "PASS")

    def test_mean_speed_from_rpm(self):
        _, ro, _ = run(sheet([sc()], rpm=600))
        self.assertAlmostEqual(ro["p"]["mean_slider_speed_per_s"], 2 * 50 * 10)
        self.assertGreater(ro["p"]["peak_slider_speed_per_s"], ro["p"]["mean_slider_speed_per_s"])

    def test_phase_shifts_pose(self):
        rows, _, _ = run(sheet([sc(phase=180)]))
        self.assertAlmostEqual(rows[0]["p"]["x"], 75)


class FourBar(unittest.TestCase):
    def test_grashof_classes(self):
        self.assertEqual(mech.grashof(300, 60, 280, 120)[0], "crank-rocker")
        self.assertEqual(mech.grashof(40, 100, 120, 110)[0], "double-crank")
        self.assertEqual(mech.grashof(100, 120, 40, 110)[0], "double-rocker")
        self.assertEqual(mech.grashof(100, 100, 100, 100)[0], "change-point")
        self.assertTrue(mech.grashof(100, 60, 55, 50)[0].startswith("non-grashof"))

    def test_loop_closes(self):
        rows, _, _ = run(sheet([fb()]))
        for r in rows:
            s = r["w"]
            self.assertAlmostEqual(math.dist(s["A"], s["B"]), 280, places=6)
            self.assertAlmostEqual(math.dist(s["B"], (300, 0)), 120, places=6)

    def test_crank_rocker_passes(self):
        _, ro, checks = run(sheet([fb()]))
        self.assertEqual(verdict_of(checks, "input can turn fully"), "PASS")
        self.assertEqual(verdict_of(checks, "transmission angle"), "PASS")
        self.assertGreater(ro["w"]["output_swing_deg"], 30)

    def test_double_rocker_cannot_turn(self):
        _, ro, checks = run(sheet([fb(ground=100, crank=120, coupler=40, rocker=110)]))
        self.assertEqual(verdict_of(checks, "input can turn fully"), "FAIL")
        self.assertEqual(verdict_of(checks, "assembles over the whole input range"), "FAIL")

    def test_partial_range_avoids_full_turn_check(self):
        _, _, checks = run(sheet([fb()], to=90))
        self.assertIsNone(verdict_of(checks, "input can turn fully"))

    def test_poor_transmission_warns_or_fails(self):
        _, ro, checks = run(sheet([fb(ground=100, crank=45, coupler=100, rocker=60)]))
        self.assertIn(verdict_of(checks, "transmission angle"), ("WARN", "FAIL"))

    def test_branches_differ(self):
        a = mech.four_bar_pose(300, 60, 280, 120, 45, "open")
        b = mech.four_bar_pose(300, 60, 280, 120, 45, "crossed")
        self.assertNotAlmostEqual(a["B"][1], b["B"][1])

    def test_circle_no_intersection(self):
        self.assertIsNone(mech.circle_intersections((0, 0), 1, (10, 0), 1))


class Drives(unittest.TestCase):
    def gear(self, **kw):
        p = {"id": "g", "type": "gear_pair", "module": 2, "z1": 20, "z2": 60, "source": "datasheet"}
        p.update(kw)
        return p

    def test_gear_ratio_and_centre(self):
        _, ro, _ = run(sheet([self.gear()]))
        self.assertEqual(ro["g"]["ratio"], 3)
        self.assertEqual(ro["g"]["centre_distance"], 80)

    def test_internal_centre(self):
        _, ro, _ = run(sheet([self.gear(internal=True)]))
        self.assertEqual(ro["g"]["centre_distance"], 40)

    def test_wrong_centre_fails(self):
        _, _, checks = run(sheet([self.gear(centre_distance=85)]))
        self.assertEqual(verdict_of(checks, "centre distance matches teeth"), "FAIL")

    def test_module_mismatch(self):
        _, _, checks = run(sheet([self.gear(module2=2.5)]))
        self.assertEqual(verdict_of(checks, "same module on both gears"), "FAIL")

    def test_undercut_warning(self):
        _, _, checks = run(sheet([self.gear(z1=12)]))
        self.assertEqual(verdict_of(checks, "undercut"), "WARN")
        _, _, checks = run(sheet([self.gear(z1=12, profile_shifted=True)]))
        self.assertEqual(verdict_of(checks, "undercut"), "PASS")

    def test_external_gear_reverses(self):
        rows, _, _ = run(sheet([self.gear()]))
        self.assertAlmostEqual(rows[-1]["g"]["out_deg"], -120)

    def test_hunting_tooth(self):
        _, ro, _ = run(sheet([self.gear(z1=21, z2=64)]))
        self.assertTrue(ro["g"]["hunting_tooth"])

    def test_chain_gear_then_slider(self):
        data = sheet([self.gear(z1=20, z2=40), sc(input="g.out")])
        rows, _, _ = run(data)
        mid = rows[36]  # driver 180 -> gear out -90
        self.assertAlmostEqual(mid["p"]["in_deg"], -90)

    def test_rack_travel_check(self):
        rp = {"id": "r", "type": "rack_pinion", "module": 4, "z": 32, "travel": 201, "rotation_deg": 180, "source": "drawing"}
        _, ro, checks = run(sheet([rp], to=180))
        self.assertEqual(verdict_of(checks, "travel matches pinion turn"), "PASS")
        self.assertAlmostEqual(ro["r"]["travel_over_range"], math.pi * 128 / 2, places=6)

    def test_rack_travel_wrong(self):
        rp = {"id": "r", "type": "rack_pinion", "module": 4, "z": 32, "travel": 250, "rotation_deg": 180}
        _, _, checks = run(sheet([rp], to=180))
        self.assertEqual(verdict_of(checks, "travel matches pinion turn"), "FAIL")

    def test_belt(self):
        b = {"id": "b", "type": "belt", "d1": 50, "d2": 150, "centre_distance": 300, "source": "measured"}
        _, ro, checks = run(sheet([b]))
        self.assertEqual(ro["b"]["ratio"], 3)
        self.assertEqual(ro["b"]["direction"], "same")
        self.assertGreater(ro["b"]["belt_length"], 2 * 300)
        self.assertEqual(verdict_of(checks, "wrap on small pulley"), "PASS")

    def test_belt_pulleys_overlap(self):
        b = {"id": "b", "type": "belt", "d1": 100, "d2": 200, "centre_distance": 120}
        _, _, checks = run(sheet([b]))
        self.assertEqual(verdict_of(checks, "pulleys clear each other"), "FAIL")

    def test_crossed_belt_reverses(self):
        b = {"id": "b", "type": "belt", "d1": 50, "d2": 100, "crossed": True}
        rows, _, _ = run(sheet([b]))
        self.assertLess(rows[10]["b"]["out_deg"], 0)


class SourcesClaimsKeys(unittest.TestCase):
    def test_ungraded_warns(self):
        p = sc(); del p["source"]
        _, _, checks = run(sheet([p]))
        self.assertEqual(verdict_of(checks, "dimension source"), "WARN")

    def test_estimated_warns(self):
        _, _, checks = run(sheet([sc(source="estimated")]))
        self.assertEqual(verdict_of(checks, "dimension source"), "WARN")

    def test_measured_passes(self):
        _, _, checks = run(sheet([sc(source="measured")]))
        self.assertEqual(verdict_of(checks, "dimension source"), "PASS")

    def test_claim_match_off_unknown(self):
        data = sheet([sc()], claims=[{"part": "p", "quantity": "stroke", "value": 50},
                                     {"part": "p", "quantity": "stroke", "value": 60},
                                     {"part": "p", "quantity": "colour", "value": 1}])
        _, ro, _ = run(data)
        res = mech.test_claims(data, ro)
        self.assertEqual([r["verdict"] for r in res], ["MATCH", "OFF", "UNKNOWN"])

    def test_claim_alias_swing(self):
        data = sheet([fb()], claims=[{"part": "w", "quantity": "swing", "value": 60, "tol": 0.02}])
        _, ro, _ = run(data)
        self.assertEqual(mech.test_claims(data, ro)[0]["verdict"], "MATCH")

    def test_claim_unknown_part(self):
        data = sheet([sc()], claims=[{"part": "nope", "quantity": "stroke", "value": 1}])
        _, ro, _ = run(data)
        self.assertEqual(mech.test_claims(data, ro)[0]["verdict"], "UNKNOWN")

    def test_key_poses_slider(self):
        rows, _, _ = run(sheet([sc()]))
        ks = mech.key_poses(sheet([sc()]), rows)
        whys = " ".join(k["why"] for k in ks)
        self.assertIn("outer dead centre", whys)
        self.assertIn("fastest", whys)
        outer = [k for k in ks if "outer" in k["why"]][0]
        self.assertAlmostEqual(outer["driver_deg"] % 360, 0)

    def test_key_poses_four_bar(self):
        data = sheet([fb()])
        rows, _, _ = run(data)
        ks = mech.key_poses(data, rows)
        self.assertEqual(len(ks), 3)


class Output(unittest.TestCase):
    def test_flat_rows_and_csv(self):
        data = sheet([sc(), {"id": "g", "type": "gear_pair", "module": 1, "z1": 20, "z2": 40}])
        rows, _, _ = run(data)
        flat = mech.flat_rows(data, rows)
        self.assertIn("p.x", flat[0]); self.assertIn("g.out_deg", flat[0])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "poses.csv")
            mech.write_csv(path, flat)
            with open(path) as fh:
                lines = fh.read().strip().splitlines()
            self.assertEqual(len(lines), len(rows) + 1)

    def test_svg_sheet(self):
        data = sheet([sc(), fb()])
        rows, _, _ = run(data)
        svg = mech.render_sheet(data, rows, frames=6)
        self.assertTrue(svg.startswith("<svg"))
        self.assertEqual(svg.count("driver = "), 6)
        self.assertNotIn("driver = 360.0", svg)

    def test_svg_marks_no_fit(self):
        data = sheet([sc(rod=20)])
        rows, _, _ = run(data)
        self.assertIn("no fit", mech.render_sheet(data, rows, frames=8))

    def test_svg_frames_validated(self):
        data = sheet([sc()])
        rows, _, _ = run(data)
        with self.assertRaises(mech.SheetError):
            mech.render_sheet(data, rows, frames=0)


class CLI(unittest.TestCase):
    def test_examples_solve(self):
        code, out, _ = cli(["solve", os.path.join(EX, "single-cylinder.json")])
        self.assertEqual(code, 0)
        self.assertIn("stroke", out)

    def test_wiper_warns(self):
        code, _, _ = cli(["solve", os.path.join(EX, "wiper-linkage.json")])
        self.assertEqual(code, 1)

    def test_claims_off_exit_2(self):
        code, out, _ = cli(["claims", os.path.join(EX, "single-cylinder.json")])
        self.assertEqual(code, 2)
        self.assertIn("OFF", out)

    def test_json_output(self):
        code, out, _ = cli(["solve", os.path.join(EX, "landing-gear-rack.json"), "--json"])
        d = json.loads(out)
        self.assertEqual(d["verdict"], "PASS")

    def test_invalid_sheet_exit_3(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bad.json")
            with open(p, "w") as fh:
                fh.write("{\"parts\": []}")
            code, _, err = cli(["solve", p])
        self.assertEqual(code, 3)
        self.assertIn("invalid sheet", err)

    def test_sheet_and_keys_commands(self):
        with tempfile.TemporaryDirectory() as d:
            out_svg = os.path.join(d, "s.svg")
            code, out, _ = cli(["sheet", os.path.join(EX, "single-cylinder.json"), "--out", out_svg, "--keys"])
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(out_svg))
        code, out, _ = cli(["keys", os.path.join(EX, "wiper-linkage.json"), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)), 3)

    def test_csv_flag(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "p.csv")
            code, out, _ = cli(["solve", os.path.join(EX, "single-cylinder.json"), "--csv", p, "--steps", "36"])
            self.assertTrue(os.path.exists(p))
            self.assertIn("37 rows", out)


if __name__ == "__main__":
    unittest.main()
