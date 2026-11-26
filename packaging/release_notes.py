"""Print the CHANGELOG.md section for one version (used as GitHub release notes).

    python packaging/release_notes.py 0.1.0 > notes.md
    python packaging/release_notes.py --check-tag v0.1.0   # tag must match the version

The version is dragonwilds_save_editor.__version__ (read from the source, not imported).

Exits non-zero if the version has no section, so a release can't go out without notes.
"""

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_version():
    """__version__ from dragonwilds_save_editor/__init__.py."""
    path = os.path.join(ROOT, "dragonwilds_save_editor", "__init__.py")
    with open(path, encoding="utf-8") as f:
        m = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", f.read(), re.M)
    if not m:
        raise SystemExit("__version__ not found in %s" % path)
    return m.group(1)


def section(version, text):
    # Headings look like "## [0.1.0] - 2026-11-24"; the section ends at the next "## "
    # heading or at the link reference definitions at the bottom.
    head = re.compile(r"^## \[?%s\]?(?:[ \t].*)?$" % re.escape(version), re.M)
    m = head.search(text)
    if not m:
        return None
    body = text[m.end():]
    end = re.search(r"^(## |\[[^\]]+\]: )", body, re.M)
    return (body[:end.start()] if end else body).strip()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("version", nargs="?", help="version to print (default: the package __version__)")
    p.add_argument("--check-tag", metavar="TAG", help="fail unless TAG == 'v' + __version__")
    a = p.parse_args(argv)

    version = a.version or read_version()
    if a.check_tag is not None:
        if a.check_tag != "v" + read_version():
            print("Tag %s does not match __version__ %s (expected v%s)"
                  % (a.check_tag, read_version(), read_version()), file=sys.stderr)
            return 1
        version = read_version()

    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        notes = section(version, f.read())
    if not notes:
        print("CHANGELOG.md has no non-empty section for %s" % version, file=sys.stderr)
        return 1
    sys.stdout.write(notes + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
