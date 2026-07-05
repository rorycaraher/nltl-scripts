# NLTL Scripts

Scripts I use for music things. Not really making or playing music.

## bandcamp_unzip.sh

Watches `~/Downloads` for new Bandcamp zip files, extracts each into its own
folder under `BANDCAMP_DEST`, and cleans up the zip.

```
BANDCAMP_DEST=/Volumes/T7/Music ./bandcamp_unzip.sh [once|watch]
```

See the header comment in the script for environment variables and the
launchd setup for running it automatically on login.

## collect_all_and_save.py

Automates Ableton Live's "Collect All and Save" (only reachable by hand via
the File menu) for a `.als` file. Reverse-engineered by diffing real
before/after `.als` files rather than trusting Ableton's documentation,
which turned out to be wrong on destination-folder naming and Max for Live
collection scope.

Deliberately narrower than Ableton's own feature:

- Only collects audio referenced by actual clips (`SampleRef`/`FileRef`).
  Devices, racks, presets, M4L patches, and VST state are left alone.
- Pack content and Ableton's own bundled ("Builtin") content are always
  left alone — assumed present wherever the same Ableton install is.
- Collected files always land flattened in `Samples/Imported/`, not
  mirrored into Ableton's own subfolder-naming scheme.
- Fails that file's run and writes/copies nothing for it if it finds a
  destination collision with different content, a missing source file, or
  anything it doesn't recognize — never guesses.
- Never modifies the input; always writes a new, numbered `.als`
  (`-04.als` → `-05.als`), skipping past any number already taken by
  another file in the directory rather than overwriting it.

```
./collect_all_and_save.py path/to/Project/Song.als
./collect_all_and_save.py --all
```

`--all` processes every top-level `.als` in the current directory (not
`Backup/` or other subfolders) — a fixed list taken at launch, so anything
the run itself writes is never picked up. Each file is fully independent:
one file's failure doesn't stop the others, and a summary of collected /
unchanged / failed is printed at the end (exit status is nonzero if
anything failed). Bare no-argument invocation still just prints usage —
`--all` has to be explicit.

Pure standard library, no dependencies. Built and tested against Live
12.4.2; the fixtures used to reverse-engineer and validate its behavior
are in `collect-all-and-save-fixtures/`.
