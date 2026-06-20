#!/usr/bin/env bash
# bandcamp_unzip.sh
# Watches ~/Downloads for new Bandcamp zip files, extracts them, and cleans up.
#
# Required environment variable:
#   BANDCAMP_DEST        — destination folder for extracted albums
#                          e.g. export BANDCAMP_DEST=/Volumes/T7/Music
#
# Optional environment variables:
#   BANDCAMP_DRY_RUN=1   — print what would happen without extracting or deleting
#   WATCH_INTERVAL       — polling interval in seconds (default: 30)
#
# Usage:
#   BANDCAMP_DEST=/Volumes/T7/Music ./bandcamp_unzip.sh [once|watch]
#
# Extraction layout:
#   album.zip  →  $BANDCAMP_DEST/album/   (never directly into BANDCAMP_DEST)
#
# To run automatically on login, see the launchd plist instructions at the bottom.

set -euo pipefail

# ── Validate required env var ──────────────────────────────────────────────────
if [[ -z "${BANDCAMP_DEST:-}" ]]; then
    echo "Error: BANDCAMP_DEST is not set." >&2
    echo "Usage: BANDCAMP_DEST=/path/to/music $0 [once|watch]" >&2
    exit 1
fi

DOWNLOADS="$HOME/Downloads"
DEST="$BANDCAMP_DEST"
PROCESSED_LOG="$HOME/.bandcamp_unzip_processed"

DRY_RUN=false
[[ "${BANDCAMP_DRY_RUN:-0}" == "1" ]] && DRY_RUN=true

if ! $DRY_RUN; then
    mkdir -p "$DEST"
    touch "$PROCESSED_LOG"
fi

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

process_zip() {
    local zip="$1"
    local filename
    filename="$(basename "$zip")"

    # Skip if already processed
    if grep -qxF "$zip" "$PROCESSED_LOG" 2>/dev/null; then
        return
    fi

    # Check it's actually a Bandcamp zip by inspecting the extended attribute
    # set by Safari/Firefox (com.apple.metadata:kMDItemWhereFroms) for the URL.
    # Falls back to filename heuristics if the attribute isn't present.
    local source_url=""
    if command -v mdls &>/dev/null; then
        source_url=$(mdls -name kMDItemWhereFroms "$zip" 2>/dev/null | grep -o 'https\?://[^"]*' | head -1 || true)
    fi

    local is_bandcamp=false
    if echo "$source_url" | grep -qi "bandcamp\.com"; then
        is_bandcamp=true
    elif echo "$filename" | grep -qiE "^[a-z0-9_-]+-[a-z0-9_-]+\.(zip)$"; then
        # Bandcamp zips follow the pattern artist-album.zip; treat as likely match
        # when no URL metadata is available (e.g. downloaded via a download manager)
        is_bandcamp=true
    fi

    if ! $is_bandcamp; then
        return
    fi

    log "Found Bandcamp zip: $filename"

    # Strip .zip to get the album subfolder name.
    # Bandcamp zips contain files at their root (no top-level dir inside), so
    # extracting into $DEST/$subfolder gives exactly $DEST/album/track.flac etc.
    local subfolder="${filename%.zip}"
    local target="$DEST/$subfolder"

    if $DRY_RUN; then
        log "[DRY RUN] Would create:  $target/"
        log "[DRY RUN] Would extract: $zip → $target/"
        log "[DRY RUN] Would delete:  $filename"
        return
    fi

    mkdir -p "$target"

    if unzip -q "$zip" -d "$target"; then
        log "Extracted → $target"
        # Mark as processed before deleting (so a crash mid-delete doesn't re-process)
        echo "$zip" >> "$PROCESSED_LOG"
        rm -f "$zip"
        log "Deleted $filename"
    else
        log "ERROR: Failed to extract $filename — leaving zip in place."
    fi
}

# ── Mode: single scan (run once and exit) ──────────────────────────────────────
scan_once() {
    log "Scanning $DOWNLOADS for Bandcamp zips…"
    local found=0
    while IFS= read -r -d '' zip; do
        process_zip "$zip"
        ((found++)) || true
    done < <(find "$DOWNLOADS" -maxdepth 1 -name "*.zip" -print0)
    log "Done. $found zip(s) checked."
}

# ── Mode: watch (poll every N seconds) ────────────────────────────────────────
watch_loop() {
    local interval="${WATCH_INTERVAL:-30}"
    log "Watching $DOWNLOADS every ${interval}s. Press Ctrl-C to stop."
    log "Extracting to: $DEST"
    while true; do
        while IFS= read -r -d '' zip; do
            process_zip "$zip"
        done < <(find "$DOWNLOADS" -maxdepth 1 -name "*.zip" -print0)
        sleep "$interval"
    done
}

# ── Entrypoint ─────────────────────────────────────────────────────────────────
case "${1:-watch}" in
    once)  scan_once ;;
    watch) watch_loop ;;
    *)     echo "Usage: BANDCAMP_DEST=/path/to/music $0 [once|watch]"; exit 1 ;;
esac


# ══════════════════════════════════════════════════════════════════════════════
# OPTIONAL: Run automatically with launchd (macOS login item)
# ══════════════════════════════════════════════════════════════════════════════
#
# 1. Copy this script somewhere permanent, e.g.:
#       cp bandcamp_unzip.sh ~/bin/bandcamp_unzip.sh
#       chmod +x ~/bin/bandcamp_unzip.sh
#
# 2. Create a launchd plist at:
#       ~/Library/LaunchAgents/com.you.bandcamp-unzip.plist
#
#    Contents (edit the paths to match your setup):
#
#    <?xml version="1.0" encoding="UTF-8"?>
#    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
#        "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
#    <plist version="1.0">
#    <dict>
#        <key>Label</key>
#        <string>com.you.bandcamp-unzip</string>
#        <key>ProgramArguments</key>
#        <array>
#            <string>/bin/bash</string>
#            <string>/Users/YOU/bin/bandcamp_unzip.sh</string>
#            <string>watch</string>
#        </array>
#        <key>EnvironmentVariables</key>
#        <dict>
#            <key>BANDCAMP_DEST</key>
#            <string>/Volumes/T7/Music</string>
#        </dict>
#        <key>RunAtLoad</key>
#        <true/>
#        <key>KeepAlive</key>
#        <true/>
#        <key>StandardOutPath</key>
#        <string>/tmp/bandcamp-unzip.log</string>
#        <key>StandardErrorPath</key>
#        <string>/tmp/bandcamp-unzip.log</string>
#    </dict>
#    </plist>
#
# 3. Load it:
#       launchctl load ~/Library/LaunchAgents/com.you.bandcamp-unzip.plist
#
# 4. To stop it:
#       launchctl unload ~/Library/LaunchAgents/com.you.bandcamp-unzip.plist
