# Geometry-v2 central-task experiment protocol

This revision replaces the former remote angular-shell task. It changes only the
public experimental geometry, scenario coordinates, sensing range, and resulting
configuration capacities. The policy implementations and simulator framework are
not changed.

## Frozen geometry

All coordinates use the project ENU convention: x east, y north, z up, in metres.
Mount order is `[roll, pitch, yaw]` in degrees.

| Device | Position (m) | Mount R/P/Y (deg) | Initial local Y/P (deg) |
|---|---:|---:|---:|
| zr10_25 | `[0,-50,2]` | `[0,55,63.434948823]` | `[0,-25]` |
| zr10_26 | `[0,50,2]` | `[0,55,-63.434948823]` | `[0,-25]` |
| zr10_27 | `[50,-50,2]` | `[0,55,116.565051177]` | `[0,-25]` |
| zr10_28 | `[50,50,2]` | `[0,55,-116.565051177]` | `[0,-25]` |

The four mount yaw zero-directions point to the horizontal centre `(25,0)`. The
55-degree installation pitch plus the -25-degree initial local pitch points the
initial optical axes at approximately 30 degrees world elevation.

The task ROI is:

- `x: [10,40]`
- `y: [-40,40]`
- `z: [10,60]`

The persistent-search domain is the same box, discretised as `3×7×3=63` cells.
This keeps the candidate-generation budget close to the former 65-cell task while
representing all three spatial dimensions. The public effective sensing distance
is capped at 100 m.

The farthest device-to-ROI-corner distance is greater than 100 m, so no claim is
made that every device sees the whole box. The automated geometry test instead
enforces the experimental requirement that every search cell is within 100 m and
inside the calibrated local yaw/pitch limits of at least two devices.

## Scenario migration

Former Cartesian CV, sinusoidal, and waypoint trajectories are mapped by:

`x_new = 0.5*x_old - 40`, `y_new = 0.8*y_old`, `z_new = z_old - 25`.

Their velocity and sinusoidal-amplitude components use the same per-axis scale.
Coordinated-turn trajectories retain heading, turn rate, and climb rate, with
horizontal speed multiplied by 0.8. Scenario IDs, time windows, split membership,
and random seeds are unchanged.

## Validity and rerun order

Geometry-v1 validation selections and held-out results are not valid for this
revision. The manifest therefore locks held-out splits until the following order
is completed:

1. run correctness tests and non-held-out full-duration pilots;
2. tune all four parameterised non-learning baselines on S4/S8 and seeds 2001–2005;
3. freeze the selected JSON files and their SHA-256 identities;
4. unlock and run main, OOD, ablation, sensitivity, and scalability experiments;
5. retain raw per-run metrics, protocol snapshots, aggregate tables, statistical
   comparisons, figures, and completion audits.

The primary table continues to use the seven non-learning methods declared in the
manifest. MAPPO and Safe-MAPPO remain optional and excluded from that frozen scope.
If either is reintroduced, its old checkpoints must not be reused because the
geometry and search-state representation changed; it must be retrained and selected
using only the declared train/validation splits.

## Physical deployment warning

`calibration_verified` is deliberately false for all four stations. Editing YAML
does not physically align a gimbal. Before real-device experiments, measure station
positions and mount zero-directions in one ENU frame, run the control-point
calibration workflow, validate on independent points, and only then mark each
device as verified.
