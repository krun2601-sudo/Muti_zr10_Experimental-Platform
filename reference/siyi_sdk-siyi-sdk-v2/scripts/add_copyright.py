#!/usr/bin/env python3
# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import os
import sys

HEADER = """# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""

DIRECTORIES = ["siyi_sdk", "examples", "tests", "web_ui"]

def add_header(file_path):
    with open(file_path, "r") as f:
        content = f.read()

    if "Copyright (c) 2026 Mohamed Abdelkader" in content:
        return False

    with open(file_path, "w") as f:
        # Handle shebang if present
        if content.startswith("#!"):
            lines = content.splitlines()
            shebang = lines[0]
            rest = "\\n".join(lines[1:])
            f.write(shebang + "\\n" + HEADER + rest)
        else:
            f.write(HEADER + content)
    return True

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    count = 0
    for d in DIRECTORIES:
        dir_path = os.path.join(base_dir, d)
        if not os.path.isdir(dir_path):
            continue
        for root, _, files in os.walk(dir_path):
            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    if add_header(file_path):
                        print(f"Added header to {file_path}")
                        count += 1
    
    # Also check install_gst_dependencies.sh in root
    gst_script = os.path.join(base_dir, "install_gst_dependencies.sh")
    if os.path.exists(gst_script):
        if add_header(gst_script):
            print(f"Added header to {gst_script}")
            count += 1

    print(f"Finished! Added headers to {count} files.")

if __name__ == "__main__":
    main()
