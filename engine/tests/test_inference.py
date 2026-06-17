"""INI-076 Phase 2 — tests for the inference backend abstraction.
Run (from engine/): python -m unittest tests.test_inference -v
Mocks backend boundaries so tests run with no network / no ollama|anthropic pkgs.
"""
import sys, unittest
from pathlib import Path
from unittest import mock

_engine_dir = Path(__file__).resolve().parent.parent
if str(_engine_dir) not in sys.path:
    sys.path.insert(0, str(_engine_dir))
import inference  # noqa: E402


class TestRouting(unittest.TestCase):
    def test_prefers_local_when_available(self):
        with mock.patch.object(inference, "local_available", return_value=True), \
             mock.patch.object(inference, "_ollama_generate", return_value='{"ok": 1}') as og, \
             mock.patch.object(inference, "_anthropic_generate") as ag:
            text, backend = inference.generate_json("sys", "user")
        self.assertEqual(text, '{"ok": 1}')
        self.assertEqual(backend, "ollama")
        og.assert_called_once(); ag.assert_not_called()

    def test_falls_back_when_local_unavailable(self):
        with mock.patch.object(inference, "local_available", return_value=False), \
             mock.patch.object(inference, "_ollama_generate") as og, \
             mock.patch.object(inference, "_anthropic_generate", return_value='{"api": 1}') as ag:
            text, backend = inference.generate_json("sys", "user")
        self.assertEqual(text, '{"api": 1}'); self.assertEqual(backend, "anthropic")
        og.assert_not_called(); ag.assert_called_once()

    def test_falls_back_when_local_errors(self):
        with mock.patch.object(inference, "local_available", return_value=True), \
             mock.patch.object(inference, "_ollama_generate", side_effect=RuntimeError("boom")), \
             mock.patch.object(inference, "_anthropic_generate", return_value='{"api": 1}') as ag:
            text, backend = inference.generate_json("sys", "user")
        self.assertEqual(backend, "anthropic"); ag.assert_called_once()

    def test_prefer_local_false_skips_ollama(self):
        with mock.patch.object(inference, "local_available", return_value=True) as la, \
             mock.patch.object(inference, "_ollama_generate") as og, \
             mock.patch.object(inference, "_anthropic_generate", return_value='{"api": 1}'):
            text, backend = inference.generate_json("sys", "user", prefer_local=False)
        self.assertEqual(backend, "anthropic"); la.assert_not_called(); og.assert_not_called()


class TestLocalAvailable(unittest.TestCase):
    def _fake(self, names):
        f = mock.MagicMock()
        f.Client.return_value.list.return_value = {"models": [{"name": n} for n in names]}
        return f
    def test_true_when_resident(self):
        with mock.patch.dict(sys.modules, {"ollama": self._fake(["llama3.1:8b"])}), \
             mock.patch.object(inference, "LOCAL_MODEL", "llama3.1:8b"):
            self.assertTrue(inference.local_available())
    def test_false_when_absent(self):
        with mock.patch.dict(sys.modules, {"ollama": self._fake(["mistral:7b"])}), \
             mock.patch.object(inference, "LOCAL_MODEL", "llama3.1:8b"):
            self.assertFalse(inference.local_available())
    def test_false_on_conn_error(self):
        f = mock.MagicMock(); f.Client.return_value.list.side_effect = OSError("refused")
        with mock.patch.dict(sys.modules, {"ollama": f}):
            self.assertFalse(inference.local_available())


class TestAnthropicGuard(unittest.TestCase):
    def test_requires_key(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                inference._anthropic_generate("sys", "user", 256)


if __name__ == "__main__":
    unittest.main()
