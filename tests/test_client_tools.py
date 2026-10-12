from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "voice-backend"))
from client_tools import FileTools


class FileToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.files = FileTools()
        self.files.roots = [self.root]

    def test_write_read_edit_and_list(self):
        path = self.root / "nota.txt"
        self.assertIn("Guardé", self.files.run("write_file", {"path": str(path), "content": "hola"}))
        self.assertEqual(self.files.run("read_text_file", {"path": str(path)}), "hola")
        self.assertIn("Edité", self.files.run("edit_file", {"path": str(path),
                                                             "oldText": "hola", "newText": "adiós"}))
        self.assertIn("nota.txt", self.files.run("list_directory", {"path": str(self.root)}))

    def test_rejects_paths_outside_roots(self):
        outside = self.root.parent / "fuera.txt"
        self.assertIn("fuera", self.files.run("write_file", {"path": str(outside), "content": "no"}))
        self.assertFalse(outside.exists())
