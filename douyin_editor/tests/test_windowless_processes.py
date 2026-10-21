"""Exercise real Windows children, including callers that subclass Popen."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


@unittest.skipUnless(os.name == "nt", "Windows process creation")
class WindowlessProcessesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = subprocess.Popen.__init__
        path = Path(__file__).resolve().parents[1] / "packaging/windowless_subprocess_hook.py"
        spec = importlib.util.spec_from_file_location("windowless_hook", path)
        cls.hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.hook)

    @classmethod
    def tearDownClass(cls):
        subprocess.Popen.__init__ = cls.original

    def test_child_has_no_console_and_pipes_work(self):
        code = "import ctypes,json,sys; print(json.dumps({'console':bool(ctypes.windll.kernel32.GetConsoleWindow()),'input':sys.stdin.read()})); print('diagnostic',file=sys.stderr)"
        result = subprocess.run([sys.executable, "-c", code], input="audio input",
                                capture_output=True, text=True, check=True, timeout=20)
        self.assertEqual(json.loads(result.stdout), {"console": False, "input": "audio input"})
        self.assertEqual(result.stderr.strip(), "diagnostic")

    def test_subclass_retains_group_flags_and_can_be_cancelled(self):
        class LibraryProcess(subprocess.Popen):
            pass
        code = "import ctypes,time; print(int(bool(ctypes.windll.kernel32.GetConsoleWindow())),flush=True); time.sleep(30)"
        with LibraryProcess([sys.executable, "-c", code], stdout=subprocess.PIPE,
                            text=True, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP) as process:
            try:
                self.assertEqual(process.stdout.readline().strip(), "0")
            finally:
                process.terminate()
                process.wait(timeout=10)
        self.assertIsNotNone(process.returncode)

    def test_install_is_idempotent_and_exit_codes_are_preserved(self):
        installed = subprocess.Popen.__init__
        self.hook.install()
        self.assertIs(subprocess.Popen.__init__, installed)
        result = subprocess.run([sys.executable, "-c", "raise SystemExit(7)"], timeout=20)
        self.assertEqual(result.returncode, 7)


if __name__ == "__main__":
    unittest.main()
