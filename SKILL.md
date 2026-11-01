---
name: mechanism-sheet
description: Before you draw, animate, simulate or explain how a machine moves (an engine, a wiper, a gearbox, a landing-gear leg, a toy linkage, a printer axis), reduce it to one driver and a chain of standard elements, put real dimensions with a source grade on every part, solve it over the full cycle, and run assembly checks (closes everywhere, Grashof class, transmission angle, gear mesh, rack travel, belt wrap). Output a mechanism sheet: readouts every label must quote, key poses worth a beat, a pose table any renderer reads, and a claim check for numbers already in a script, caption or diagram. Use when someone asks "how does X work, show me", wants a cutaway, exploded view, 3D lesson, SVG diagram or motion explainer of a mechanism, or asks whether an explainer's numbers are right.
---

# Mechanism Sheet

Animations of machines go wrong in the same three ways. The parts are invented, so the motion is generic. Each part is moved on its own, so the rod passes through the crank or the wiper swings 90° on a linkage that can only do 60°. And the labels are typed in by hand, so the caption says 15 m/s while the motion shows 11.

A mechanism sheet fixes all three before a single frame exists. It is a short, checked description of the machine: **one driver**, **a chain of standard elements**, **real numbers with a grade for where they came from**, and **everything else computed**. Whatever you build afterwards (a three.js page, a Blender rig, an SVG diagram, a Manim scene, a Remotion clip or a plain written explanation) reads its poses and numbers from the sheet, so nothing on screen can disagree with the motion.

`scripts/mech.py` (Python 3.8+, no dependencies) solves the sheet, runs the checks, finds the key poses, writes the pose table and draws an SVG contact sheet so you can see the motion without a renderer.

## When to use

- "How does a ___ work? Show me." Engines, pumps, wipers, cranes, gear legs, clocks, toy walkers, 3D printer axes, door closers.
- Before building any mechanism visual: interactive simulator, cutaway, exploded view, product explainer, classroom diagram.
- Checking someone else's explainer: a script, caption, storyboard or diagram already states numbers ("stroke 54.8 mm", "the wiper sweeps 90°", "gear ratio 3:1").
- A rendered machine "looks wrong" and you need to know whether the problem is the model or the drawing.

Not for: free-form motion design with no mechanism behind it, organic or soft-body motion, fluid flow, or structural strength (this checks how things move, not whether they break).

## The method

### 1. Write the machine card (5 lines)

```
machine:   the specific thing (make/model if real), not the category
question:  the one thing the viewer should understand ("why the cam turns at half speed")
output:    3D page | video | SVG diagram | written explanation | claim check only
audience:  who reads the numbers (student, buyer, engineer)
reference: the photo, drawing, manual page or clip you will match
```

No reference means you stop and find one. A mechanism built from a sentence comes out as a generic one; a mechanism built against a manual drawing comes out as the real one.

### 2. Get the numbers and grade each one

For every element, find the dimensions the type needs (table below) and record where they came from with one grade:

| grade | meaning | how labels may quote it |
|---|---|---|
| `measured` | you or the user put a rule on the real part | exact |
| `drawing` | dimensioned drawing, CAD, manual figure | exact |
| `datasheet` | published spec (bore × stroke, tooth count) | exact |
| `derived` | computed from other graded numbers | exact, show the derivation once |
| `estimated` | scaled from a photo against a known length | "about", round it |
| `guess` | plausible value to get started | never on screen |

The checker warns on `estimated`, `guess` and ungraded parts. That warning is the point: it stops a guessed number from turning into a confident caption.

### 3. Pick ONE driver and reduce the machine to standard elements

Choose the single input everything follows: crank angle, motor angle, pinion angle, stroke fraction. Then express the machine as a chain:

| element | it needs | it gives |
|---|---|---|
| `slider_crank` | `crank`, `rod`, optional `offset` | slider position, rod angle, stroke, dead centres, time ratio, slider speed (with `rpm`) |
| `four_bar` | `ground`, `crank`, `coupler`, `rocker`, `branch` | output angle and swing, Grashof class, transmission angle |
| `gear_pair` | `module`, `z1`, `z2`, optional `centre_distance`, `internal` | ratio, pitch diameters, centre distance, direction |
| `rack_pinion` | `module`, `z`, optional `travel` + `rotation_deg` | rack travel |
| `belt` | `d1`, `d2`, optional `centre_distance`, `crossed` | ratio, direction, belt length, wrap angle |

Each element takes `"input": "driver"` (default) or `"input": "<earlier id>.out"`, plus an optional `phase` in degrees, so a gear can drive a crank, a crank can drive a four-bar, and so on. Several cylinders are several slider cranks on the driver with different phases.

If part of the machine is not one of these (a cam profile, a Geneva wheel, a spring), keep it outside the sheet and drive it from a sheet output in your renderer; note it on the card as "not checked".

### 4. Write the sheet and solve it

```json
{
  "name": "Single-cylinder 125 cc engine",
  "units": "mm",
  "driver": {"name": "crank angle", "from": 0, "to": 360, "steps": 72, "rpm": 6000},
  "parts": [
    {"id": "piston", "type": "slider_crank", "crank": 27.4, "rod": 97, "source": "datasheet"},
    {"id": "cam_drive", "type": "gear_pair", "module": 1, "z1": 18, "z2": 36, "centre_distance": 27, "source": "drawing"}
  ]
}
```

```
python3 scripts/mech.py solve engine.json --csv poses.csv
```

Exit code 0 = every check PASS, 1 = a WARN, 2 = a FAIL, 3 = the sheet itself is invalid.

### 5. Read the checks and fix with numbers

| check | FAIL / WARN means | fix |
|---|---|---|
| assembles over the whole input range | at some driver angle the loop cannot close | the lengths are wrong or the driver range is too wide; re-read the reference |
| input can turn fully | the four-bar is not crank-rocker or double-crank | it is a rocker mechanism: limit the driver range, or recheck which link is shortest |
| transmission angle | under 40° it pushes badly; under 20° it jams | lengthen the coupler or move the ground pivot |
| rod length ratio | rod under 2.5 × crank swings hard | usually a mis-read rod length |
| centre distance / same module | the gears cannot mesh as drawn | tooth counts or module are wrong |
| travel matches pinion turn | stated travel is not π × d × turn | one of module, teeth, travel or angle is wrong |
| pulleys clear / wrap | pulleys overlap or the belt slips | move the centres |
| dimension source | numbers are estimated or guessed | find a better source, or mark labels "about" |

Never fix a FAIL by hiding it in the render (a camera angle, a cut, a part made invisible). The sheet is the machine; if the sheet fails, the machine does too.

### 6. Freeze the readouts

The `solve` output is the list of numbers the visual is allowed to show: stroke, swing, ratio, peak speed, centre distance. Copy them into the build as data, not as typed text. Round only at display time, and round estimated values harder ("about 60°").

### 7. Choose the beats from the key poses

```
python3 scripts/mech.py keys engine.json
python3 scripts/mech.py sheet engine.json --keys --out keys.svg
```

Key poses are where the mechanism says something: dead centres, the fastest moment of the slider, both limits of a rocker, the worst transmission angle. These are the frames worth a pause, a label or a camera move. Use them as the beats of the tour or storyboard instead of evenly spaced time.

Open the SVG (or render it to PNG) and look at it. If the contact sheet looks wrong, the render will too.

### 8. Hand off the pose table

`--csv poses.csv` writes one row per driver step: `driver_deg`, `piston.x`, `piston.rod_deg`, `wiper.out_deg`, `wiper.mu_deg`, `cam_drive.out_deg`, `retract.travel`. The renderer contract:

- Every moving part is posed from the row for the current driver value (interpolate between rows, or call the same formulas in code).
- Every label, gauge and chart reads the same row or the frozen readouts. No second source of numbers.
- Time maps to the driver in one place (`driver = f(t)`), so the live view, the recording and any sound stay in step.

### 9. Claim check mode

When numbers already exist in someone's script, caption or diagram, add them as claims and test them:

```json
"claims": [
  {"part": "piston", "quantity": "stroke", "value": 54.8, "tol": 0.005, "said_by": "spec sheet"},
  {"part": "piston", "quantity": "mean_slider_speed_per_s", "value": 15000, "tol": 0.05, "said_by": "caption draft"}
]
```

```
python3 scripts/mech.py claims engine.json
```

Each claim comes back MATCH, OFF (with the percentage) or UNKNOWN (the model has no such quantity). Report OFF claims with what the model says and why, and fix the claim or the sheet, whichever the reference supports.

## Report format

```
MECHANISM SHEET - <machine>        verdict PASS | WARN | FAIL
driver:     <name>, <range>, <rpm if any>
elements:   <id: type, key dims, grade> ...
readouts:   <the numbers the visual may quote>
checks:     <only WARN/FAIL lines, each with its fix>
key poses:  <angle - why> ...
claims:     <MATCH/OFF/UNKNOWN lines>
not checked: <anything outside the sheet>
hand-off:   poses.csv (<rows>), keys.svg
```

## Examples

**Engine explainer.** A creator wants a 20 s piece on a 125 cc single. Datasheet: bore 52.4, stroke 54.8; the rod is measured at 97 mm. The sheet uses crank 27.4 (half the stroke), rod 97, and an 18/36 cam gear. `solve` gives stroke 54.8, rod/crank 3.54, mean piston speed 10.96 m/s at 6000 rpm, peak about 17.9 m/s. The draft caption said "15 m/s"; `claims` marks it OFF by 37%. The caption becomes "about 11 m/s on average, nearly 18 at its fastest". Beats: top dead centre, bottom dead centre, fastest point.

**Wiper storyboard.** A storyboard frame shows the blade sweeping 90°. Lengths scaled from a photo (graded `estimated`): ground 300, crank 60, coupler 280, rocker 120. The linkage is crank-rocker, closes everywhere, worst transmission angle 57°, but the swing is 60°. Either the storyboard changes to 60°, or the lengths come from a better source before anyone animates 90°.

**Landing-gear rack.** A drawing says a 32-tooth, module-4 pinion turns 180° to move a rack 201 mm. Pitch diameter is 128 mm, half its circumference is 201.06 mm: PASS. One hand check like this, shown once in the explainer, earns trust for every other number.

## Tips

- Check one number by hand and show it. It catches unit mistakes and makes the explainer credible.
- Keep the units consistent across the whole sheet (all mm or all inches). Angles are degrees.
- For a multi-cylinder engine, add one slider crank per cylinder with its firing phase; the solver keeps them on one driver.
- A double-rocker is not broken: limit the driver range to where it closes and say so in the explainer.
- The open/crossed branch of a four-bar changes the motion completely; match it to the reference photo.
- Run `solve` again after every dimension change. A two-second rerun is cheaper than re-rendering a minute of video.
