import sys


def count_stats(content: str) -> dict:
    return {"lines": content.count("\n") + 1, "words": len(content.split()), "chars": len(content)}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: cli.py FILE", file=sys.stderr)
        return 2
    with open(argv[0], encoding="utf-8") as handle:
        content = handle.read()
    if not content.strip():
        return 1
    stats = count_stats(content)
    print("lines: {}".format(stats["lines"]))
    print("words: {}".format(stats["words"]))
    print("chars: {}".format(stats["chars"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())