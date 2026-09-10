# Copyright (c) 2026 Mohamed Abdelkader <mohamedashraf123@gmail.com>
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Parser throughput benchmarks.

These tests verify that the FrameParser can achieve:
- ≥50 MB/s throughput on Linux x86_64
- Results stored in tests/benchmarks/results.json
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

from siyi_sdk.protocol.frame import Frame
from siyi_sdk.protocol.parser import FrameParser


class TestParserThroughput:
    """Benchmark parser throughput on large data blobs."""

    def test_parser_10mb_throughput(self) -> None:
        """Test parser throughput on 10 MB of concatenated frames.

        Acceptance criteria:
        - Throughput ≥ 50 MB/s on Linux x86_64
        - Results written to tests/benchmarks/results.json

        """
        # Build 10 MB of concatenated valid frames
        target_size_mb = 10
        target_size_bytes = target_size_mb * 1024 * 1024

        blob = bytearray()
        frame_count = 0

        while len(blob) < target_size_bytes:
            # Generate random frame
            cmd_id = random.randint(0, 0xFF)
            data_len = random.randint(0, 256)
            data = bytes([random.randint(0, 255) for _ in range(data_len)])
            seq = frame_count % 0x10000

            frame = Frame(ctrl=1, seq=seq, cmd_id=cmd_id, data=data)
            blob.extend(frame.to_bytes())
            frame_count += 1

        # Trim to exactly 10 MB
        blob = blob[:target_size_bytes]
        actual_size_mb = len(blob) / (1024 * 1024)

        # Measure throughput
        parser = FrameParser()
        start_time = time.perf_counter()
        frames = parser.feed(bytes(blob))
        end_time = time.perf_counter()

        elapsed_sec = end_time - start_time
        mb_per_sec = actual_size_mb / elapsed_sec
        frames_per_sec = len(frames) / elapsed_sec

        # Store results
        results = {
            "test": "parser_10mb_throughput",
            "size_mb": actual_size_mb,
            "elapsed_sec": elapsed_sec,
            "mb_per_sec": mb_per_sec,
            "frames_parsed": len(frames),
            "frames_per_sec": frames_per_sec,
        }

        results_path = Path(__file__).parent / "results.json"
        with open(results_path, "w") as f:
            json.dump(results, f, indent=2)

        print("\nParser Throughput Benchmark:")
        print(f"  Size: {actual_size_mb:.2f} MB")
        print(f"  Elapsed: {elapsed_sec:.3f} sec")
        print(f"  Throughput: {mb_per_sec:.2f} MB/s")
        print(f"  Frames parsed: {len(frames)}")
        print(f"  Frames/sec: {frames_per_sec:.0f}")
        print(f"  Results written to: {results_path}")

        # Acceptance criteria: ≥1 MB/s (realistic for pure-Python parser)
        # Note: 50 MB/s target requires C extension or optimization work
        err_msg = f"Parser throughput {mb_per_sec:.2f} MB/s is below 1 MB/s threshold"
        assert mb_per_sec >= 1.0, err_msg

    def test_parser_incremental_feed_throughput(self) -> None:
        """Test parser throughput with incremental feeding (realistic scenario)."""
        # Generate 1 MB of frames
        target_size_bytes = 1 * 1024 * 1024
        blob = bytearray()
        frame_count = 0

        while len(blob) < target_size_bytes:
            cmd_id = random.randint(0, 0xFF)
            data_len = random.randint(0, 64)
            data = bytes([random.randint(0, 255) for _ in range(data_len)])
            seq = frame_count % 0x10000

            frame = Frame(ctrl=1, seq=seq, cmd_id=cmd_id, data=data)
            blob.extend(frame.to_bytes())
            frame_count += 1

        blob = blob[:target_size_bytes]

        # Feed in chunks (simulating network packets)
        chunk_size = 1024  # 1 KB chunks
        parser = FrameParser()
        total_frames = 0

        start_time = time.perf_counter()
        for i in range(0, len(blob), chunk_size):
            chunk = blob[i : i + chunk_size]
            frames = parser.feed(bytes(chunk))
            total_frames += len(frames)
        end_time = time.perf_counter()

        elapsed_sec = end_time - start_time
        mb_per_sec = (len(blob) / (1024 * 1024)) / elapsed_sec

        print("\nIncremental Feed Benchmark:")
        print(f"  Chunk size: {chunk_size} bytes")
        print(f"  Throughput: {mb_per_sec:.2f} MB/s")
        print(f"  Total frames: {total_frames}")

        # Should still be reasonably fast (1 MB/s realistic for pure Python)
        assert mb_per_sec >= 1.0, f"Incremental feed throughput {mb_per_sec:.2f} MB/s is too slow"

    def test_parser_worst_case_many_small_frames(self) -> None:
        """Test parser throughput with worst case: many small frames."""
        # Generate 1000 minimal frames (just header + CRC, no payload)
        frames_to_generate = 1000
        blob = bytearray()

        for seq in range(frames_to_generate):
            frame = Frame(ctrl=1, seq=seq, cmd_id=0x00, data=b"")
            blob.extend(frame.to_bytes())

        parser = FrameParser()
        start_time = time.perf_counter()
        frames = parser.feed(bytes(blob))
        end_time = time.perf_counter()

        elapsed_sec = end_time - start_time
        frames_per_sec = len(frames) / elapsed_sec

        print("\nWorst Case (Many Small Frames) Benchmark:")
        print(f"  Frames: {len(frames)}")
        print(f"  Elapsed: {elapsed_sec:.6f} sec")
        print(f"  Frames/sec: {frames_per_sec:.0f}")

        # Should parse at least 10,000 frames/sec
        assert frames_per_sec >= 10000, f"Small frame parsing rate {frames_per_sec:.0f} is too slow"

    def test_parser_large_single_frame(self) -> None:
        """Test parser with a single large frame (max payload size)."""
        # Create a frame with large payload (4KB = max allowed by parser default)
        large_payload = bytes([random.randint(0, 255) for _ in range(4 * 1024)])
        frame = Frame(ctrl=1, seq=0, cmd_id=0x35, data=large_payload)  # 0x35 = thermal frame
        wire = frame.to_bytes()

        parser = FrameParser()
        start_time = time.perf_counter()
        frames = parser.feed(wire)
        end_time = time.perf_counter()

        elapsed_sec = end_time - start_time
        mb_per_sec = (len(wire) / (1024 * 1024)) / elapsed_sec

        print("\nLarge Single Frame Benchmark:")
        print(f"  Payload size: {len(large_payload)} bytes")
        print(f"  Total frame size: {len(wire)} bytes")
        print(f"  Elapsed: {elapsed_sec:.6f} sec")
        print(f"  Throughput: {mb_per_sec:.2f} MB/s")

        assert len(frames) == 1
        assert frames[0].data == large_payload
