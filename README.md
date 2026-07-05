# NLTL Scripts

Scripts I use for music things. Not really making or playing music.

## bandcamp_unzip.sh

Watches `~/Downloads` for Bandcamp zips, extracts each into its own folder
under `BANDCAMP_DEST`, deletes the zip.

```
BANDCAMP_DEST=/Volumes/T7/Music ./bandcamp_unzip.sh [once|watch]
```

Env vars and launchd setup are documented in the script's header comment.

## collect_all_and_save.py

Scriptable version of Ableton's "Collect All and Save" (menu-only in Live).
Reverse-engineered from real before/after `.als` diffs, not the docs.

```
./collect_all_and_save.py path/to/Project/Song.als   # one file
./collect_all_and_save.py --all                      # every .als here
```

**What it collects:** audio (`SampleRef`) and Max for Live devices
(`MxPatchRef`) — same rules for both, flattened into `Samples/Imported/`
and `Presets/Imported/`.

**What it leaves alone:** Packs, Ableton's own bundled content, anything
already inside the project, and everything else (racks, presets, VST).

**Safety:**
- Never touches the input — always writes a new numbered file, skipping
  any number already taken.
- A collision (two different files, same name) or a missing source aborts
  *that file* — nothing copied, nothing written. `--all` keeps going on
  the rest and reports failures at the end.

No dependencies. Tested against Live 12.4.2; fixtures in
`collect-all-and-save-fixtures/`.
