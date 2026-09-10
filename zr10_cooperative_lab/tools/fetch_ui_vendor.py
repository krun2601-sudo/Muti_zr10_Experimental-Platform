"""仅开发/更新前端依赖时运行：获取固定 Three.js r180 资源并记录哈希。

正常使用总控制中心不需要运行本工具，也不需要 Node.js、npm 或外部 CDN。
文件均来自 Three.js 官方仓库的固定标签，保留 MIT 许可证。
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1] / "zr10lab" / "web" / "vendor"
BASE = "https://raw.githubusercontent.com/mrdoob/three.js/r180/"
FILES = {
    "three.module.js": "build/three.module.js",
    "three.core.js": "build/three.core.js",
    "OrbitControls.js": "examples/jsm/controls/OrbitControls.js",
    "THREE-LICENSE.txt": "LICENSE",
}


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    def fetch(item):
        name, relative = item
        with urlopen(BASE + relative, timeout=45) as response:
            data = response.read()
        if not data:
            raise RuntimeError(f"资源为空：{name}")
        return name, data
    # 全部下载成功以后再写文件，避免网络错误导致混合版本。
    with ThreadPoolExecutor(max_workers=4) as pool:
        contents = list(pool.map(fetch, FILES.items()))
    result = {"library": "three.js", "version": "0.180.0", "tag": "r180",
              "source": "https://github.com/mrdoob/three.js/tree/r180", "license": "MIT", "files": {}}
    for name, data in contents:
        (ROOT / name).write_bytes(data)
        result["files"][name] = {"source": BASE + FILES[name], "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    (ROOT / "SOURCE.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
