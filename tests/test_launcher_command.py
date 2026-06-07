import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_launcher_command_is_absolute_when_on_path(monkeypatch):
    import wondershot
    monkeypatch.setattr("shutil.which",
                        lambda n: "/home/u/.local/bin/wondershot")
    assert wondershot.launcher_command() == \
        "/home/u/.local/bin/wondershot --capture"


def test_launcher_command_falls_back_to_venv_bin(monkeypatch, tmp_path):
    import sys

    import wondershot
    monkeypatch.setattr("shutil.which", lambda n: None)
    fake = tmp_path / "wondershot"
    fake.write_text("")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python3"))
    assert wondershot.launcher_command() == f"{fake} --capture"


def test_launcher_command_program_is_never_grabbit(monkeypatch):
    import os

    import wondershot
    monkeypatch.setattr("shutil.which", lambda n: None)
    program = wondershot.launcher_command().split()[0]
    # the dir may legitimately be named grabbit (this repo!) — the
    # PROGRAM must be wondershot
    assert os.path.basename(program) == "wondershot"
