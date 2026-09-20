from textstats.cli import count_stats, main


def test_basic():
    assert count_stats("hello world\nsecond line") == {
        "lines": 2, "words": 4, "chars": 23}


def test_single_line():
    assert count_stats("one two three") == {
        "lines": 1, "words": 3, "chars": 13}


def test_unicode():
    assert count_stats("مرحبا") == {"lines": 1, "words": 1, "chars": 5}


def test_three_lines():
    assert count_stats("a\nb\nc") == {"lines": 3, "words": 3, "chars": 5}


def test_main_output_format(tmp_path, capsys):
    sample = tmp_path / "s.txt"
    sample.write_text("hello world\nsecond line", encoding="utf-8")
    assert main([str(sample)]) == 0
    out = capsys.readouterr().out
    assert out == "lines: 2\nwords: 4\nchars: 23\n"