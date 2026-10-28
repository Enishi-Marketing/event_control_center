"""Exercise the native Swift client against real subprocess pipes."""

import json
import os
import selectors
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


BACKEND = r'''
import json, sys, time
request = json.load(sys.stdin)
mode = request["payload"]["mode"]
progress = {"type": "progress", "message": "Video — 園"}
completed = {"type": "completed"}
if mode == "error":
    sys.stderr.write("Video encoder failed\n")
    sys.exit(7)
if mode == "malformed":
    print("not JSON", flush=True)
    time.sleep(15)
    sys.exit()
if mode == "noisy":
    sys.stderr.write("diagnostic output\n" * 32768)
    sys.stderr.flush()
if mode == "split":
    data = (json.dumps(progress, ensure_ascii=False) + "\n").encode()
    for byte in data:
        sys.stdout.buffer.write(bytes([byte]))
        sys.stdout.buffer.flush()
else:
    print(json.dumps(progress), flush=True)
if mode == "delayed":
    time.sleep(2)
sys.stdout.write(json.dumps(completed) + ("" if mode == "no_newline" else "\n"))
sys.stdout.flush()
'''


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("swiftc"), "Requires macOS and Swift")
class BackendStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="ecc-native-stream-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.probe = cls.root / "probe"
        project = Path(__file__).resolve().parents[1]
        cls.project = project
        compile_command = ["swiftc", "-parse-as-library"]
        if sdk := os.environ.get("ECC_SWIFT_SDK"):
            compile_command += ["-sdk", sdk]
        compile_command += [
            str(project / "swiftui/Sources/EventControlCenter/BackendClient.swift"),
            str(project / "swiftui/Sources/EventControlCenter/Models.swift"),
            str(project / "tests/fixtures/BackendStreamProbe.swift"),
            "-o", str(cls.probe),
        ]
        subprocess.run(compile_command, capture_output=True, text=True, check=True, timeout=120)
        (cls.root / "backend_bridge.py").write_text(BACKEND, encoding="utf-8")
        cls.environment = {
            **os.environ, "ECC_BACKEND_ROOT": str(cls.root), "ECC_PYTHON": sys.executable,
        }

    def run_probe(self, mode: str, count: int = 1) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(self.probe), mode, str(count)], cwd=self.root, env=self.environment,
            capture_output=True, text=True, timeout=10,
        )

    def assert_completed(self, mode: str) -> None:
        result = self.run_probe(mode)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[-1], "finished: 2")
        events = [json.loads(line) for line in lines[:-1]]
        self.assertEqual([event["type"] for event in events], ["progress", "completed"])
        self.assertEqual(events[0]["message"], "Video — 園")

    def test_stream_finishes_after_backend_exits(self) -> None:
        self.assert_completed("normal")

    def test_split_json_and_utf8_are_preserved(self) -> None:
        self.assert_completed("split")

    def test_final_event_without_newline_is_delivered(self) -> None:
        self.assert_completed("no_newline")

    def test_full_stderr_pipe_does_not_block_progress_or_completion(self) -> None:
        self.assert_completed("noisy")

    def test_nonzero_exit_reports_diagnostics(self) -> None:
        result = self.run_probe("error")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Video encoder failed", result.stderr)

    def test_malformed_output_stops_backend_and_reports_error(self) -> None:
        result = self.run_probe("malformed")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("finished:", result.stdout)

    def test_concurrent_streams_all_finish(self) -> None:
        result = self.run_probe("normal", count=24)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines().count("finished: 2"), 24)

    def test_progress_arrives_before_backend_finishes(self) -> None:
        with subprocess.Popen(
            [str(self.probe), "delayed"], cwd=self.root, env=self.environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ) as process:
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    self.assertTrue(selector.select(timeout=1.5), "No live progress received")
                event = json.loads(process.stdout.readline())
                self.assertEqual(event["type"], "progress")
                self.assertIsNone(process.poll(), "Progress was buffered until backend exit")
                remaining, errors = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, errors)
                self.assertIn("finished: 2", remaining)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    def test_real_video_import_delivers_completion_and_smaller_copy(self) -> None:
        from imageio_ffmpeg import get_ffmpeg_exe

        with tempfile.TemporaryDirectory(prefix="ecc-native-video-") as directory:
            root = Path(directory)
            source = root / "camera media"
            source.mkdir()
            original = source / "camera.mp4"
            subprocess.run([
                get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                "-i", "testsrc2=size=320x180:rate=24", "-t", "0.5", "-c:v", "libx264",
                "-preset", "ultrafast", str(original),
            ], check=True, capture_output=True, timeout=15)
            event = root / "events" / "2026.10.29 - Native video test"
            (event / "Data").mkdir(parents=True)
            metadata = event / "Data/metadata.json"
            metadata.write_text(json.dumps({"photo_count": 0, "video_count": 0}))
            environment = {**self.environment, "ECC_BACKEND_ROOT": str(self.project)}
            result = subprocess.run(
                [str(self.probe), "real-import", str(source), str(event)],
                cwd=self.project, env=environment, capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.splitlines()
            self.assertEqual(lines[-1], "finished")
            events = [json.loads(line) for line in lines[:-1]]
            self.assertEqual(events[-1]["type"], "completed")
            self.assertEqual(events[-1]["outcome"]["videosImported"], 1)
            self.assertEqual(events[-1]["outcome"]["socialVideosGenerated"], 1)
            self.assertFalse(events[-1]["outcome"]["failures"])
            self.assertIn("Creating smaller video", [entry.get("phase") for entry in events])
            self.assertTrue(original.is_file())
            self.assertEqual(json.loads(metadata.read_text())["video_count"], 1)
            self.assertEqual(len(list((event / "Raw/Smaller Videos").glob("*.mp4"))), 1)


if __name__ == "__main__":
    unittest.main()
