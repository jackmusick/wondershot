"""--scroll-spike must stay: it is the scroll-capture debugging harness
(spec Addendum 2 Track 4b: 'Keep the CLI flag'). No Qt needed — main()
dispatches to run_scroll_spike before any QApplication exists."""


def test_scroll_spike_flag_dispatches(monkeypatch):
    import wondershot.scrollsource as scrollmod
    from wondershot.cli import main
    monkeypatch.setattr(scrollmod, "run_scroll_spike", lambda: 42)
    assert main(["--scroll-spike"]) == 42
