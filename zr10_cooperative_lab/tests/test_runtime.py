"""跨模块端到端测试，验证真正产生可重放实验数据。"""
import csv
import json
from dataclasses import replace
from pathlib import Path
import numpy as np
import pytest
from zr10lab.actions import ActionValidator
from zr10lab.analysis import analyze_session,read_csv,replay_session
from zr10lab.config import load_config
from zr10lab.models import Action,Telemetry
from zr10lab.recording import CSVRecorder
from zr10lab.runtime import run_simulation
from zr10lab.timing import interpolate_telemetry


def config():
    return load_config(Path(__file__).resolve().parents[1]/"configs/four_zr10.yaml")


def test_complete_run_and_exact_fusion_replay(tmp_path):
    cfg = config(); cfg.system["duration_s"] = 1.2
    path = run_simulation(cfg,tmp_path)
    summary = analyze_session(path,plots=False)
    assert summary["completed"] and summary["cycles"]==12
    assert summary["localizations"]>=20
    assert summary["final_metrics"]["position_rmse_m"]<1
    for name in ("telemetry","detections","rays","tracks","localizations","actions","cycles","truth"):
        assert read_csv(path/f"{name}.csv")
    replay = replay_session(path,tmp_path)
    original = read_csv(path/"tracks.csv")
    repeated = read_csv(replay/"tracks.csv")
    assert len(original)==len(repeated)
    for left,right in zip(original,repeated):
        assert left["track_id"]==right["track_id"] and left["measured"]==right["measured"]
        assert np.allclose([float(left[k]) for k in ("x_m","y_m","z_m")],
                           [float(right[k]) for k in ("x_m","y_m","z_m")],atol=1e-10)


def test_action_mask_and_atomic_rejection():
    cfg = config(); s = Telemetry("zr10_25",1,0,0)
    validator = ActionValidator(cfg)
    for action in (Action(s.device_id,yaw_deg=float("nan"),issued_t=1),
                   Action(s.device_id,yaw_deg=140,issued_t=1),
                   Action(s.device_id,yaw_deg=5,zoom=2,issued_t=1),
                   Action(s.device_id,yaw_deg=5,issued_t=0,ttl_s=.1)):
        with pytest.raises(ValueError):
            validator.validate(action,s,1,.1)


def test_interpolation_no_yaw_shortcut_and_zoom_transition():
    a,b = Telemetry("d",0,-120,0),Telemetry("d",.1,120,10)
    mid = interpolate_telemetry([a,b],.05)
    assert mid.yaw_deg==0 and mid.pitch_deg==5
    with pytest.raises(ValueError,match="变焦"):
        interpolate_telemetry([a,replace(b,zoom=2)],.05)
    with pytest.raises(ValueError):
        interpolate_telemetry([a,b],1)


def test_logger_schema_integrity_and_incomplete_run(tmp_path):
    r = CSVRecorder(tmp_path,config().to_dict(),"sim")
    with pytest.raises(ValueError):
        r.write("events",0,unknown="bad")
    r.event("test",{"message":"中文,逗号\n换行"},0)
    r.close(completed=False)
    assert read_csv(r.path/"events.csv")[0]["payload_json"]=='{"message":"中文,逗号\\n换行"}'
    assert not json.loads((r.path/"metadata.json").read_text(encoding="utf-8"))["completed"]
    with (r.path/"events.csv").open("a",encoding="utf-8") as f:
        f.write("corrupt")
    with pytest.raises(ValueError,match="完整性"):
        analyze_session(r.path,plots=False)
