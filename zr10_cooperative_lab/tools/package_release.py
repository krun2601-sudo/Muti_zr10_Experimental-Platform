"""可复现交付打包：只打包源码、文档、示例验证数据及锁定 SDK，不打包用户权重。"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import zipfile


def main():
    project = Path(__file__).resolve().parents[1]
    workspace = project.parent
    sdk = workspace/"reference"/"siyi_sdk-siyi-sdk-v2"
    vendor = project/"vendor"/"siyi_sdk_v2_snapshot.zip"
    # 保留已核验的SDK固定快照，避免每次打包重新生成而改变其哈希。
    if not vendor.exists() and sdk.exists():
        with zipfile.ZipFile(vendor,"w",zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(sdk.rglob("*")):
                if file.is_file() and not any(p in (".git","__pycache__",".claude",".pytest_cache") for p in file.parts):
                    archive.write(file,Path("siyi_sdk")/file.relative_to(sdk))
        record = {"source":"https://github.com/mzahana/siyi_sdk/tree/siyi-sdk-v2",
            "sdk_version":"0.6.0","retrieved_utc_date":"2026-09-06",
            "upstream_archive_sha256":hashlib.sha256((workspace/"reference"/"siyi_sdk_upstream.zip").read_bytes()).hexdigest(),
            "bundled_snapshot_sha256":hashlib.sha256(vendor.read_bytes()).hexdigest(),
            "license":"MIT (included in snapshot)",
            "note":"固定所核验的源码快照，以哈希标识；运行时不自动更新到分支最新版本。"}
        (project/"vendor"/"SOURCE.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
    output = workspace/"delivery"
    output.mkdir(exist_ok=True)
    version = re.search(r'__version__\s*=\s*"([^"]+)"', (project/"zr10lab"/"__init__.py").read_text(encoding="utf-8")).group(1)
    target = output/f"zr10_cooperative_lab_v{version.replace('.', '_')}.zip"
    excluded = {".venv","__pycache__",".pytest_cache",".git","runs","build","dist"}
    verification_path = project/"samples"/"validation"/"VERIFICATION.json"
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    if verification.get("status")!="passed":
        raise RuntimeError("必须先完成 tools/verify_release.py")
    for name,digest in verification["source_sha256"].items():
        if hashlib.sha256((project/name).read_bytes()).hexdigest()!=digest:
            raise RuntimeError(f"验收后源码已改变，需要重新验证：{name}")
    session_dirs = [project/s["session"] for s in verification["scenarios"]]+[project/verification["replay_session"]]
    def include_sample(file):
        relative = file.relative_to(project).as_posix()
        if not relative.startswith("samples/validation/"):
            return True
        # 仅交付最终验收实际引用的会话，保留失败尝试在本地，不混入正式样例。
        return file.parent==verification_path.parent or any(file.is_relative_to(d) for d in session_dirs)
    files = [file for file in sorted(project.rglob("*")) if file.is_file()
             and not any(p in excluded or p.startswith(".venv") or p.endswith(".egg-info") for p in file.relative_to(project).parts)
             and not file.name.startswith("~$")
             and file.suffix not in (".pyc",".pt",".onnx", ".bak") and include_sample(file)]
    with zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for file in files:
            info = zipfile.ZipInfo((Path(project.name)/file.relative_to(project)).as_posix(),date_time=(2026,9,7,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            # 原README可能正由Word占用；发布包入口使用v4说明，保留旧说明便于追溯。
            if file == project/"README.md":
                original_info = zipfile.ZipInfo((Path(project.name)/"README_v3_reference.md").as_posix(), date_time=(2026,9,7,0,0,0))
                original_info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(original_info, file.read_bytes())
                readme = (project/"README_v4.md").read_text(encoding="utf-8")
                readme = readme.replace("[原平台使用说明](README.md)", "[原平台使用说明](README_v3_reference.md)")
                archive.writestr(info, readme.encode("utf-8"))
            else:
                archive.writestr(info,file.read_bytes())
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".zip.sha256").write_text(f"{digest}  {target.name}\n",encoding="ascii")
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        file_count = len(archive.infolist())
    print(json.dumps({"zip":str(target),"sha256":digest,"files":file_count,"size_bytes":target.stat().st_size},indent=2))


if __name__=="__main__":
    main()
