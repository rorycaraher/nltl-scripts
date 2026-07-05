#!/usr/bin/env python3
"""Automate Ableton Live's "Collect All and Save" for a .als file.

Scope, deliberately narrower than Ableton's own feature, based on empirical
diffing of real before/after .als files (Live 12.4.2) rather than Ableton's
documentation, which was found to be inaccurate on destination-folder naming
and Max for Live collection scope:

- Only touches <FileRef> nodes that are the direct child of a <SampleRef>
  (i.e. actual audio-clip content). Devices, racks, presets, M4L patches,
  VST state, and Pack content are never modified, matching observed Ableton
  behavior for those cases.
- Pack content (LivePackId non-empty) is always left alone.
- Ableton "Builtin" content bundled inside the app itself (path contains
  ".app/Contents/", e.g. Hybrid Reverb's factory impulse responses) is
  always left alone, for the same reason as Packs: guaranteed present
  alongside any matching Ableton install.
- Any SampleRef whose absolute Path already lives inside the project folder
  is left alone.
- Every other SampleRef is treated as external and collected into
  <project>/Samples/Imported/<basename> -- deliberately flattened, not
  mirroring Ableton's own (partially unverified) subfolder-preservation
  heuristic.
- On a destination collision (two different external files -> same
  basename), content is compared by hash: identical content is deduped,
  different content aborts the whole run.
- A missing source file aborts the whole run.
- The input .als is never modified; output is always written to a new,
  numbered file.

Everything is analyzed before anything is written: if any problem is found
(missing file, real collision, unrecognized structure), nothing is copied
and nothing is written -- every problem found is reported together.

Usage:
    collect_all_and_save.py <path-to-.als>
"""

import hashlib
import gzip
import re
import shutil
import sys
import time
import xml.sax
from pathlib import Path


class CollectError(Exception):
    pass


class SampleRefHandler(xml.sax.ContentHandler):
    """Walks the document tracking line numbers, recording -- for each
    <SampleRef> -- the direct-child <FileRef>'s RelativePathType/
    RelativePath/Path/LivePackId, plus the sibling LastModDate. Nested
    FileRefs (e.g. under SourceContext/OriginalFileRef) are ignored because
    they never sit at the tracked FileRef's exact depth with parent
    'FileRef'.
    """

    TRACKED_FILEREF_FIELDS = {"RelativePathType", "RelativePath", "Path", "LivePackId"}

    def __init__(self):
        super().__init__()
        self.locator = None
        self.stack = []
        self.context_stack = []
        self.results = []

    def setDocumentLocator(self, locator):
        self.locator = locator

    def startElement(self, name, attrs):
        line = self.locator.getLineNumber()
        parent_depth = len(self.stack)
        parent_name = self.stack[-1] if self.stack else None

        if name == "SampleRef":
            self.context_stack.append({"fields": {}, "file_ref_depth": None})
        elif self.context_stack:
            current = self.context_stack[-1]
            if name == "FileRef" and parent_name == "SampleRef" and current["file_ref_depth"] is None:
                current["file_ref_depth"] = parent_depth + 1
            elif name == "LastModDate" and parent_name == "SampleRef":
                current["fields"]["LastModDate"] = {"line": line, "value": attrs.get("Value")}
            elif (
                current["file_ref_depth"] is not None
                and parent_depth == current["file_ref_depth"]
                and parent_name == "FileRef"
                and name in self.TRACKED_FILEREF_FIELDS
            ):
                current["fields"][name] = {"line": line, "value": attrs.get("Value")}

        self.stack.append(name)

    def endElement(self, name):
        self.stack.pop()
        if name == "SampleRef" and self.context_stack:
            self.results.append(self.context_stack.pop())


def next_output_path(input_path: Path) -> Path:
    m = re.match(r"^(.*-)(\d{2})(\.als)$", input_path.name)
    if m:
        prefix, num, suffix = m.groups()
        new_num = str(int(num) + 1).zfill(len(num))
        return input_path.with_name(f"{prefix}{new_num}{suffix}")
    return input_path.with_name(f"{input_path.stem}-01{input_path.suffix}")


def sha256_of(path: Path, cache: dict) -> str:
    if path not in cache:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        cache[path] = h.hexdigest()
    return cache[path]


PATCH_LINE_RE = re.compile(r'(<\w+\s+Value=")[^"]*("\s*/>\s*)$')


def line_is_patchable(line: str) -> bool:
    return PATCH_LINE_RE.search(line) is not None


def replace_attr_value(line: str, new_value: str) -> str:
    escaped = (
        new_value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    new_line, count = PATCH_LINE_RE.subn(
        lambda m: m.group(1) + escaped + m.group(2),
        line,
        count=1,
    )
    if count != 1:
        raise CollectError(f"could not patch line, format not recognized: {line!r}")
    return new_line


def analyze(sample_refs, project_root: Path, lines: list):
    """Returns (to_collect, problems). Touches nothing on disk except reads
    for hashing/existence checks. Every line that would need patching is
    validated against the expected one-tag-per-line format here, before the
    caller copies or writes anything -- so a format surprise is reported
    like any other problem, never left as a partial copy on disk.
    """
    to_collect = []
    problems = []

    for ctx in sample_refs:
        fields = ctx["fields"]
        if ctx["file_ref_depth"] is None:
            continue  # no FileRef under this SampleRef at all

        live_pack_id = fields.get("LivePackId", {}).get("value")
        if live_pack_id:
            continue  # Pack content, always skip

        path_field = fields.get("Path")
        if path_field is None or not path_field["value"]:
            continue
        source_path = Path(path_field["value"])

        if ".app/Contents/" in str(source_path):
            continue  # Ableton "Builtin" content bundled with the app itself, always skip

        try:
            source_path.relative_to(project_root)
            continue  # already local
        except ValueError:
            pass  # external

        required = ("RelativePathType", "RelativePath", "Path", "LastModDate")
        missing = [f for f in required if f not in fields]
        if missing:
            problems.append(
                f"unrecognized SampleRef structure for {source_path} "
                f"(missing field(s): {', '.join(missing)}) -- refusing to guess"
            )
            continue

        if not source_path.is_file():
            problems.append(f"source file missing on disk: {source_path}")
            continue

        unpatchable = [
            name
            for name in required
            if not line_is_patchable(lines[fields[name]["line"] - 1])
        ]
        if unpatchable:
            problems.append(
                f"unrecognized line format for {source_path} "
                f"(field(s): {', '.join(unpatchable)}) -- refusing to guess"
            )
            continue

        dest_path = project_root / "Samples" / "Imported" / source_path.name

        to_collect.append(
            {
                "source": source_path,
                "dest": dest_path,
                "relpathtype_line": fields["RelativePathType"]["line"],
                "relpath_line": fields["RelativePath"]["line"],
                "path_line": fields["Path"]["line"],
                "lastmod_line": fields["LastModDate"]["line"],
            }
        )

    hash_cache = {}
    dest_to_sources = {}
    for entry in to_collect:
        dest_to_sources.setdefault(entry["dest"], set()).add(entry["source"])

    for dest, sources in dest_to_sources.items():
        hashes = {source: sha256_of(source, hash_cache) for source in sources}
        if dest.exists():
            hashes[dest] = sha256_of(dest, hash_cache)
        if len(set(hashes.values())) > 1:
            named = ", ".join(f"{p} ({h[:8]})" for p, h in hashes.items())
            problems.append(f"destination collision at {dest}: {named}")

    return to_collect, problems


def collect(input_path: Path):
    project_root = input_path.parent
    raw = gzip.decompress(input_path.read_bytes()).decode("utf-8")
    lines = raw.splitlines(keepends=True)

    handler = SampleRefHandler()
    xml.sax.parseString(raw.encode("utf-8"), handler)

    to_collect, problems = analyze(handler.results, project_root, lines)

    if problems:
        print("Aborted -- nothing was copied or written. Problems found:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)

    if not to_collect:
        print("Nothing to collect -- no external SampleRef audio found.")
        return

    run_timestamp = str(int(time.time()))
    dest_dir = project_root / "Samples" / "Imported"
    dest_dir.mkdir(parents=True, exist_ok=True)

    # All line edits are computed (and, per the analyze() pre-check, guaranteed
    # patchable) before any file is copied, and any copy this run performs is
    # tracked so it can be undone if a later step fails -- the goal being that
    # a crash here still leaves either everything done or nothing done.
    copied = set()
    edits = {}
    report = []
    newly_created = []

    try:
        for entry in to_collect:
            dest = entry["dest"]
            if dest not in copied:
                if not dest.exists():
                    shutil.copy2(entry["source"], dest)
                    newly_created.append(dest)
                    report.append(f"copied  {entry['source']} -> {dest}")
                else:
                    report.append(f"reused  {dest} (already present, identical content)")
                copied.add(dest)

            rel_path_value = f"Samples/Imported/{dest.name}"
            edits[entry["relpathtype_line"]] = replace_attr_value(lines[entry["relpathtype_line"] - 1], "3")
            edits[entry["relpath_line"]] = replace_attr_value(lines[entry["relpath_line"] - 1], rel_path_value)
            edits[entry["path_line"]] = replace_attr_value(lines[entry["path_line"] - 1], str(dest))
            edits[entry["lastmod_line"]] = replace_attr_value(lines[entry["lastmod_line"] - 1], run_timestamp)

        for line_no, new_line in edits.items():
            lines[line_no - 1] = new_line

        output_path = next_output_path(input_path)
        output_path.write_bytes(gzip.compress("".join(lines).encode("utf-8")))
    except Exception as exc:
        for path in newly_created:
            path.unlink(missing_ok=True)
        print(f"Aborted after an unexpected error -- rolled back {len(newly_created)} copied file(s).", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        sys.exit(1)

    for line in report:
        print(line)
    print(f"Collected {len(to_collect)} reference(s), {len(copied)} unique file(s), into {dest_dir}")
    print(f"Wrote {output_path}")


def main():
    if len(sys.argv) != 2:
        print("usage: collect_all_and_save.py <path-to-.als>", file=sys.stderr)
        sys.exit(2)

    input_path = Path(sys.argv[1]).resolve()
    if not input_path.is_file():
        print(f"error: {input_path} not found", file=sys.stderr)
        sys.exit(1)

    collect(input_path)


if __name__ == "__main__":
    main()
