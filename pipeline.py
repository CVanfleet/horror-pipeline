#!/usr/bin/env python3
"""TikTok Horror Story Video Pipeline.

Generates horror narration scripts via Claude, converts to speech via ElevenLabs,
and composites final videos with background footage via FFmpeg.
"""

import argparse
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from prompts import SETTING_HINTS, SYSTEM_PROMPT, USER_PROMPT
from prompts_history import HISTORY_SYSTEM_PROMPT, HISTORY_TOPIC_HINTS, HISTORY_USER_PROMPT

# ── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
BACKGROUNDS_DIR = BASE_DIR / "backgrounds"  # parent; subfolders used per channel
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR = BASE_DIR / "temp"
DESKTOP = Path.home() / "Desktop"
STORY_HISTORY_FILE = BASE_DIR / "story_history.json"
MAX_HISTORY = 40  # total entries kept across all channels

# ── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_VOICE_ID = "Uh6UEmMIUnnL0GOOUghh"
DEFAULT_MODEL = "claude-sonnet-4-6"

CHANNELS = {
    "horror": {
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt": USER_PROMPT,
        "hints": SETTING_HINTS,
        "label": "Horror Story",
        "output_dir": OUTPUT_DIR / "horror",
        "desktop_dir": DESKTOP / "Horror Stories",
        "backgrounds_dir": BACKGROUNDS_DIR / "horror",
    },
    "history": {
        "system_prompt": HISTORY_SYSTEM_PROMPT,
        "user_prompt": HISTORY_USER_PROMPT,
        "hints": HISTORY_TOPIC_HINTS,
        "label": "Dark History",
        "output_dir": OUTPUT_DIR / "history",
        "desktop_dir": DESKTOP / "Dark History",
        "backgrounds_dir": BACKGROUNDS_DIR / "history",
    },
}

log = logging.getLogger("horror-pipeline")


# ── Story history ─────────────────────────────────────────────────────────────

def load_story_history() -> list[dict]:
    """Return past story records from disk, or [] if none exist yet."""
    if not STORY_HISTORY_FILE.exists():
        return []
    try:
        return json.loads(STORY_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        log.warning("Could not read story_history.json — starting fresh.")
        return []


def save_to_history(
    history: list[dict], title: str, hint: str, channel: str
) -> list[dict]:
    """Append one entry and persist the trimmed list; returns the updated list."""
    updated = (history + [{"title": title, "hint": hint, "channel": channel,
                           "date": datetime.now().strftime("%Y-%m-%d")}])[-MAX_HISTORY:]
    try:
        STORY_HISTORY_FILE.write_text(json.dumps(updated, indent=2), encoding="utf-8")
    except Exception:
        log.warning("Could not save story_history.json.")
    return updated


# ── Validation ───────────────────────────────────────────────────────────────

def validate_environment(dry_run: bool = False) -> list[str]:
    """Check that all required tools, credentials, and directories are ready.

    Returns a list of error messages. Empty list means everything is OK.
    Performs all checks before any API calls are made.
    """
    errors: list[str] = []

    if not os.environ.get("ANTHROPIC_API_KEY"):
        errors.append("ANTHROPIC_API_KEY not set. Add it to .env file.")

    if not dry_run:
        if not os.environ.get("ELEVENLABS_API_KEY"):
            errors.append("ELEVENLABS_API_KEY not set. Add it to .env file.")

        # Verify ffmpeg/ffprobe exist and actually run
        for tool in ("ffmpeg", "ffprobe"):
            if not shutil.which(tool):
                errors.append(f"{tool} not found. Install it with: winget install Gyan.FFmpeg")
            else:
                result = subprocess.run(
                    [tool, "-version"], capture_output=True
                )
                if result.returncode != 0:
                    errors.append(f"{tool} found but failed to run. Try reinstalling via winget.")

        for ch_name, ch in CHANNELS.items():
            bg_dir = ch["backgrounds_dir"]
            if not bg_dir.exists():
                errors.append(
                    f"backgrounds/{ch_name}/ not found. Create it and add .mp4 clips."
                )
            elif not list(bg_dir.glob("*.mp4")):
                errors.append(
                    f"No .mp4 files found in backgrounds/{ch_name}/. Add background clips."
                )

        # Create output directories and verify they're writable before any API calls
        dirs = [TEMP_DIR] + [
            d for ch in CHANNELS.values() for d in (ch["output_dir"], ch["desktop_dir"])
        ]
        for directory in dirs:
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                errors.append(f"Cannot create directory {directory}: {e}")

    return errors


# ── Stage 1: Script Generation ───────────────────────────────────────────────

def generate_script(
    hint: str,
    system_prompt: str,
    user_prompt: str,
    channel: str = "",
    history: list[dict] | None = None,
) -> tuple[str, str]:
    """Generate a narration script using Claude.

    Returns (script_text, title).
    """
    import anthropic

    content = user_prompt.format(hint=hint)

    # Inject recent stories for this channel so Claude avoids repeating them
    if history:
        past = [h for h in history if h.get("channel") == channel][-20:]
        if past:
            lines = "\n".join(f'- "{h["title"]}" (setting: {h["hint"]})' for h in past)
            content += (
                "\n\nThe following stories have already been produced for this channel. "
                "Do NOT repeat their settings, themes, core plot structures, or reveal types. "
                "Each new story must feel distinct from all of these:\n" + lines
            )

    client = anthropic.Anthropic()
    message = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[
            {"role": "user", "content": content}
        ],
    )

    full_response = message.content[0].text

    title_match = re.search(r"TITLE:\s*(.+)", full_response)
    if title_match:
        title = title_match.group(1).strip()
        script = full_response[: title_match.start()].strip()
    else:
        log.warning("No TITLE: line found in response. Using timestamp as title.")
        title = f"untitled_{datetime.now().strftime('%H%M%S')}"
        script = full_response.strip()

    word_count = len(script.split())
    log.info("Script word count: %d", word_count)
    if not 150 <= word_count <= 400:
        log.warning("Script word count (%d) is outside expected bounds.", word_count)

    return script, title


# ── Stage 2: Text-to-Speech ──────────────────────────────────────────────────

def render_speech(script: str, output_path: Path, voice_id: str) -> Path:
    """Convert script text to MP3 via ElevenLabs.

    Returns the path to the saved MP3 file.
    """
    from elevenlabs import ElevenLabs, VoiceSettings
    from elevenlabs import save as save_audio

    client = ElevenLabs()
    audio = client.text_to_speech.convert(
        text=script,
        voice_id=voice_id,
        model_id="eleven_v3",
        output_format="mp3_44100_128",
        voice_settings=VoiceSettings(
            stability=0.80,
            similarity_boost=0.70,
            style=0.15,
            use_speaker_boost=True,
        ),
    )

    save_audio(audio, str(output_path))
    log.info("Audio saved to %s", output_path)
    return output_path


# ── Stage 3: Video Assembly ──────────────────────────────────────────────────

def get_audio_duration(audio_path: Path) -> float:
    """Get duration of an audio file in seconds via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "json",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def assemble_video(audio_path: Path, output_path: Path, backgrounds_dir: Path) -> Path:
    """Combine audio narration with a random background video.

    Returns the path to the final MP4.
    """
    duration = get_audio_duration(audio_path)
    background = random.choice(list(backgrounds_dir.glob("*.mp4")))
    log.info("Using background: %s (audio duration: %.1fs)", background.name, duration)

    cmd = [
        "ffmpeg",
        "-y",
        "-stream_loop", "-1",
        "-i", str(background),
        "-i", str(audio_path),
        "-t", str(duration),
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("FFmpeg stderr:\n%s", result.stderr)
        raise RuntimeError(
            f"FFmpeg failed (exit code {result.returncode}). See log for details."
        )

    log.info("Video saved to %s", output_path)
    return output_path


# ── Orchestration ────────────────────────────────────────────────────────────

def sanitize_filename(title: str) -> str:
    """Convert a title string into a safe filename component."""
    name = re.sub(r"[^\w\s-]", "", title.lower())
    name = re.sub(r"[\s]+", "-", name).strip("-")
    return name[:60]  # cap length


def _sample_hints(hints: list, count: int) -> list:
    """Return `count` items sampled without replacement, cycling if needed."""
    if count <= len(hints):
        return random.sample(hints, count)
    result = []
    while len(result) < count:
        result.extend(random.sample(hints, len(hints)))
    return result[:count]


def run_pipeline(args: argparse.Namespace) -> None:
    """Run the full pipeline for --count videos per active channel."""
    # Build work list: [(channel_name, hint), ...]
    if args.script:
        work = [("horror", None)]
    else:
        active = (
            list(CHANNELS.keys()) if args.mode == "both" else [args.mode]
        )
        work = []
        for channel_name in active:
            hints = _sample_hints(CHANNELS[channel_name]["hints"], args.count)
            work.extend((channel_name, h) for h in hints)

    total = len(work)
    succeeded = 0
    failed = 0
    history = load_story_history()
    log.info("Loaded %d past story entries from history.", len(history))

    for i, (channel_name, hint) in enumerate(work, 1):
        channel = CHANNELS[channel_name]
        log.info("── Video %d/%d [%s] ──", i, total, channel["label"])
        try:
            if args.script:
                script = args.script.read_text(encoding="utf-8")
                base_name = args.script.stem
                title = base_name.replace("-", " ").title()
                log.info("Using script file: %s", args.script.name)

                video_dir = channel["output_dir"] / base_name
                video_dir.mkdir(exist_ok=True)
            else:
                log.info("Generating script (hint: %s)...", hint)
                script, title = generate_script(
                    hint, channel["system_prompt"], channel["user_prompt"],
                    channel=channel_name, history=history,
                )
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                base_name = f"{sanitize_filename(title)}_{timestamp}"

                video_dir = channel["output_dir"] / base_name
                video_dir.mkdir(exist_ok=True)

                script_path = video_dir / f"{base_name}.txt"
                script_path.write_text(script, encoding="utf-8")
                log.info("Script saved: %s", script_path.name)

            if args.dry_run:
                print(f"\n{'='*60}")
                print(f"[{i}/{total}] [{channel['label']}] {title}")
                print(f"{'='*60}")
                print(script)
                print()
                history = save_to_history(history, title, hint, channel_name)
                succeeded += 1
                continue

            # Stage 2: Text-to-speech
            log.info("Rendering speech...")
            audio_path = TEMP_DIR / f"{base_name}.mp3"
            render_speech(script, audio_path, args.voice)

            # Stage 3: Assemble video
            log.info("Assembling video...")
            video_path = video_dir / f"{base_name}.mp4"
            assemble_video(audio_path, video_path, channel["backgrounds_dir"])

            # Copy final video to Desktop
            desktop_dest = channel["desktop_dir"] / f"{base_name}.mp4"
            shutil.copy2(video_path, desktop_dest)
            log.info("Copied to %s", desktop_dest)

            history = save_to_history(history, title, hint, channel_name)
            succeeded += 1
            log.info("Done: %s", video_path.name)

        except Exception:
            failed += 1
            log.exception("Failed to generate video %d/%d", i, total)

    # Cleanup temp files
    if not args.keep_temp and TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
        log.info("Cleaned up temp/")

    print(f"\n{'='*60}")
    print(f"Batch complete: {succeeded} succeeded, {failed} failed out of {total}")
    print(f"Output directory: {OUTPUT_DIR}/")
    print(f"{'='*60}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate TikTok horror story videos from AI-written scripts."
    )
    parser.add_argument(
        "--count", type=int, default=1, help="Number of videos to generate (default: 1)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate scripts only (skip TTS and video assembly)",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Preserve intermediate MP3 files in temp/",
    )
    parser.add_argument(
        "--mode",
        choices=["horror", "history", "both"],
        default="both",
        help="Content mode: horror stories, dark history facts, or both (default: horror)",
    )
    parser.add_argument(
        "--voice",
        default=DEFAULT_VOICE_ID,
        help=f"ElevenLabs voice ID (default: {DEFAULT_VOICE_ID})",
    )
    parser.add_argument(
        "--script",
        type=Path,
        metavar="FILE",
        help="Path to an existing .txt script file. Skips AI generation and goes straight to TTS and video.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )

    args = parser.parse_args()

    # Logging setup
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load env
    load_dotenv(BASE_DIR / ".env")

    # Validate script file exists before anything else
    if args.script and not args.script.exists():
        print(f"ERROR: Script file not found: {args.script}")
        sys.exit(1)

    # Validate environment
    errors = validate_environment(dry_run=args.dry_run)
    if errors:
        for err in errors:
            log.error(err)
        sys.exit(1)

    run_pipeline(args)


if __name__ == "__main__":
    main()
