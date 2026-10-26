"""RLR-001 §4d-3 — حقائق المُتحقّق الحي بمسارات نسبية لا أسماء أساسية."""
from roles.live import VerifierLive
from roles.verifier import VerifierRequest, VerifierResult, VerifierVerdict


def _capture_verifier(captured: dict, monkeypatch) -> None:
    def fake_validated(self, payload, model):
        captured.update(payload)
        return VerifierResult(verdict=VerifierVerdict.EVIDENCED,
                              confidence=1.0)

    monkeypatch.setattr(VerifierLive, "_validated_completion",
                        fake_validated)


def test_facts_files_dict_structure(tmp_path, monkeypatch):
    """حقائق الملفات مفاتيحها مسارات نسبية مميزة لكل ملف."""
    ws = tmp_path / "ws"
    (ws / "css").mkdir(parents=True)
    (ws / "css" / ".keep").write_text("", encoding="utf-8")
    (ws / "js").mkdir()
    (ws / "js" / ".keep").write_text("", encoding="utf-8")
    (ws / "styles.css").write_text("x{}", encoding="utf-8")

    captured: dict = {}
    _capture_verifier(captured, monkeypatch)
    v = VerifierLive(router=None, selection=None)
    artifacts = [str(ws / "css" / ".keep"), str(ws / "js" / ".keep"),
                 str(ws / "styles.css")]
    v.run(VerifierRequest(task_acceptance_criteria=[], artifacts=artifacts,
                          evidence_refs=[]))
    files = captured["facts"]["files"]
    keys = set(files)
    assert "css/.keep" in keys, keys
    assert "js/.keep" in keys, keys
    assert "styles.css" in keys, keys
    dirs = captured["facts"]["dirs"]
    assert "css" in dirs and "js" in dirs, dirs
