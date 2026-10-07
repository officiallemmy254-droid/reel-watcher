"""Audio & Speech Transcription Engine for Reel-Watcher (`audio.py`).

Provides robust mono 16kHz audio extraction via FFmpeg, cross-platform
speech transcription with multi-engine fallback (faster-whisper -> openai-whisper -> mlx-whisper),
word-level and segment-level timestamp normalization, and audio energy / music-bed heuristics.
"""

from __future__ import annotations

import math
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any
import wave

import numpy as np

from reel_watcher.config import format_status
from reel_watcher.media import probe


def extract_audio(video_path: Path | str, out_wav: Path | str) -> Path:
    """Extract mono 16kHz 16-bit PCM WAV audio from media file using FFmpeg.

    Args:
        video_path: Path to target media file.
        out_wav: Path to destination WAV file.

    Returns:
        Path to generated WAV file.

    Raises:
        FileNotFoundError: If video_path does not exist.
        RuntimeError: If FFmpeg is missing from PATH or extraction fails.
    """
    src_path = Path(video_path)
    if not src_path.is_file():
        raise FileNotFoundError(f"Video file not found: {src_path}")

    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "ffmpeg is not found on PATH. Run preflight() for installation instructions."
        )

    dest_path = Path(out_wav)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(dest_path),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as exc:
        raise RuntimeError(f"Failed to execute ffmpeg: {exc}") from exc

    if proc.returncode != 0:
        snippet = proc.stderr.strip()[-300:]
        raise RuntimeError(
            f"ffmpeg audio extraction failed (exit code {proc.returncode}): {snippet}"
        )

    return dest_path


def normalize_transcript_segments(
    segments: list[dict[str, Any] | Any], language: str = "en"
) -> dict[str, Any]:
    """Normalize raw segments and word timestamps into a standardized structure.

    Args:
        segments: List of segment dicts or objects from Whisper engines.
        language: Language code (default: 'en').

    Returns:
        dict with:
            - text: concatenated full transcript text
            - language: detected or specified language code
            - segments: list of normalized segments with word timestamps
            - words: list of normalized word timestamps [{"w": str, "s": float, "e": float}]
    """
    if not segments:
        return {
            "text": "",
            "language": language,
            "segments": [],
            "words": [],
        }

    normalized_segments: list[dict[str, Any]] = []
    all_words: list[dict[str, Any]] = []

    for idx, seg in enumerate(segments):
        # Extract segment fields
        seg_id = getattr(seg, "id", None)
        if seg_id is None and isinstance(seg, dict):
            seg_id = seg.get("id", idx)
        if seg_id is None:
            seg_id = idx

        seg_start = getattr(seg, "start", None)
        if seg_start is None and isinstance(seg, dict):
            seg_start = seg.get("start", 0.0)
        seg_start = float(seg_start or 0.0)

        seg_end = getattr(seg, "end", None)
        if seg_end is None and isinstance(seg, dict):
            seg_end = seg.get("end", 0.0)
        seg_end = float(seg_end or 0.0)

        seg_text = getattr(seg, "text", None)
        if seg_text is None and isinstance(seg, dict):
            seg_text = seg.get("text", "")
        clean_text = str(seg_text or "").strip()

        # Extract words
        raw_words = getattr(seg, "words", None)
        if raw_words is None and isinstance(seg, dict):
            raw_words = seg.get("words", [])

        seg_words: list[dict[str, Any]] = []
        if raw_words:
            for w in raw_words:
                w_str = getattr(w, "word", None)
                if w_str is None and isinstance(w, dict):
                    w_str = w.get("word", w.get("w"))
                if w_str is None and hasattr(w, "w"):
                    w_str = getattr(w, "w")

                w_start = getattr(w, "start", None)
                if w_start is None and isinstance(w, dict):
                    w_start = w.get("start", w.get("s", seg_start))
                if w_start is None and hasattr(w, "s"):
                    w_start = getattr(w, "s")

                w_end = getattr(w, "end", None)
                if w_end is None and isinstance(w, dict):
                    w_end = w.get("end", w.get("e", seg_end))
                if w_end is None and hasattr(w, "e"):
                    w_end = getattr(w, "e")

                clean_w = str(w_str or "").strip()
                if clean_w:
                    s_val = round(float(w_start or seg_start), 3)
                    e_val = round(float(w_end or seg_end), 3)
                    seg_words.append({"w": clean_w, "s": s_val, "e": e_val})

        # Synthesize word timestamps proportionally if words list is empty
        if not seg_words and clean_text:
            tokens = clean_text.split()
            count = len(tokens)
            if count > 0:
                duration = max(0.001, seg_end - seg_start)
                interval = duration / count
                for i, tok in enumerate(tokens):
                    t_start = round(seg_start + i * interval, 3)
                    t_end = round(seg_start + (i + 1) * interval, 3)
                    seg_words.append({"w": tok, "s": t_start, "e": t_end})

        normalized_seg = {
            "id": seg_id,
            "start": round(seg_start, 3),
            "end": round(seg_end, 3),
            "text": clean_text,
            "words": seg_words,
        }
        normalized_segments.append(normalized_seg)
        all_words.extend(seg_words)

    full_text = " ".join(s["text"] for s in normalized_segments if s["text"]).strip()

    return {
        "text": full_text,
        "language": language,
        "segments": normalized_segments,
        "words": all_words,
    }


def _transcribe_with_backend(
    backend: str, audio_path: Path, model_name: str
) -> dict[str, Any]:
    """Execute speech transcription with a specific engine."""
    backend_key = backend.lower().strip().replace("_", "-")

    if backend_key == "faster-whisper":
        try:
            import av

            if hasattr(av, "open") and not getattr(av, "_reel_watcher_patched", False):
                _orig_av_open = av.open

                def _patched_av_open(*args: Any, **kwargs: Any) -> Any:
                    kwargs.pop("metadata_errors", None)
                    return _orig_av_open(*args, **kwargs)

                av.open = _patched_av_open  # type: ignore[assignment]
                setattr(av, "_reel_watcher_patched", True)
        except Exception:
            pass

        from faster_whisper import WhisperModel

        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments_iter, info = model.transcribe(str(audio_path), word_timestamps=True)
        raw_segments = list(segments_iter)
        lang = getattr(info, "language", "en") or "en"
        res = normalize_transcript_segments(raw_segments, language=lang)
        res["backend"] = "faster-whisper"
        res["model"] = model_name
        return res

    if backend_key == "openai-whisper":
        import whisper

        model = whisper.load_model(model_name)
        out = model.transcribe(str(audio_path), word_timestamps=True)
        lang = out.get("language", "en") or "en"
        raw_segments = out.get("segments", [])
        res = normalize_transcript_segments(raw_segments, language=lang)
        res["backend"] = "openai-whisper"
        res["model"] = model_name
        return res

    if backend_key == "mlx-whisper":
        import mlx_whisper

        repo = (
            model_name
            if "/" in model_name
            else f"mlx-community/whisper-{model_name}"
        )
        out = mlx_whisper.transcribe(
            str(audio_path), path_or_hf_repo=repo, word_timestamps=True
        )
        lang = out.get("language", "en") or "en"
        raw_segments = out.get("segments", [])
        res = normalize_transcript_segments(raw_segments, language=lang)
        res["backend"] = "mlx-whisper"
        res["model"] = model_name
        return res

    raise ValueError(f"Unsupported transcription backend: {backend}")


def transcribe(
    video_or_audio: Path | str, backend: str = "auto", model_name: str = "base"
) -> dict[str, Any]:
    """Transcribe speech with word-level timestamps and multi-engine fallback.

    Engine fallback order when backend="auto":
    `faster-whisper` -> `openai-whisper` -> `mlx-whisper` -> graceful empty fallback.

    Args:
        video_or_audio: Path to target video or audio file.
        backend: Transcription engine ('auto', 'faster-whisper', 'openai-whisper', 'mlx-whisper').
        model_name: Whisper model size (default: 'base').

    Returns:
        dict with keys: 'text', 'language', 'segments', 'words', 'backend', 'model'.
    """
    file_path = Path(video_or_audio)
    if not file_path.is_file():
        raise FileNotFoundError(f"Media file not found: {file_path}")

    backend_norm = backend.lower().strip().replace("_", "-")
    valid_backends = {"auto", "faster-whisper", "openai-whisper", "mlx-whisper"}
    if backend_norm not in valid_backends:
        raise ValueError(
            f"Unsupported transcription backend: '{backend}'. "
            f"Choose from 'auto', 'faster-whisper', 'openai-whisper', 'mlx-whisper'."
        )

    # Check if media has an audio stream
    try:
        media_info = probe(file_path)
        if not media_info.get("has_audio", True):
            print(format_status("info", f"No audio stream detected in {file_path.name}."))
            return {
                "text": "",
                "language": "en",
                "segments": [],
                "words": [],
                "backend": "none",
                "model": model_name,
            }
    except Exception:
        pass

    # Extract audio to temporary 16kHz mono WAV if not already a WAV file
    temp_dir: str | None = None
    target_audio: Path = file_path

    if file_path.suffix.lower() != ".wav":
        temp_dir = tempfile.mkdtemp(prefix="reel_watcher_audio_")
        target_audio = Path(temp_dir) / f"{file_path.stem}_mono16k.wav"
        try:
            extract_audio(file_path, target_audio)
        except Exception as exc:
            print(format_status("warning", f"Audio extraction failed: {exc}"))
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
            return {
                "text": "",
                "language": "en",
                "segments": [],
                "words": [],
                "backend": "none",
                "model": model_name,
            }

    try:
        backends_to_try = (
            ["faster-whisper", "openai-whisper", "mlx-whisper"]
            if backend_norm == "auto"
            else [backend_norm]
        )

        for b in backends_to_try:
            try:
                res = _transcribe_with_backend(b, target_audio, model_name)
                print(format_status("success", f"Transcribed speech using {b} ({model_name})."))
                return res
            except Exception as exc:
                if backend_norm != "auto":
                    raise
                print(format_status("info", f"Engine {b} unavailable or failed: {exc}"))
                continue

        # All engines failed or none available
        print(
            format_status(
                "warning",
                "No speech-to-text engine available. Returning empty transcript.",
            )
        )
        return {
            "text": "",
            "language": "en",
            "segments": [],
            "words": [],
            "backend": "none",
            "model": model_name,
        }

    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


def non_speech_energy_heuristic(
    video_or_audio: Path | str, words: list[dict[str, Any]], duration: float
) -> dict[str, Any]:
    """Compute speech vs non-speech energy, pauses, and background music heuristics.

    Args:
        video_or_audio: Path to video or audio media file (or empty string for timing-only analysis).
        words: List of word timestamp dicts [{"w": str, "s": float, "e": float}].
        duration: Total media duration in seconds.

    Returns:
        dict with:
            - duration, speech_duration, non_speech_duration
            - speech_ratio, non_speech_ratio
            - gaps: list of non-speech intervals
            - longest_gap: maximum continuous non-speech duration
            - overall_rms, speech_rms, non_speech_rms
            - overall_db, speech_db, non_speech_db
            - has_music_bed: True if background audio exists during pauses
            - dead_silence_count: count of gaps with near-zero energy
            - has_dead_silence: True if dead air dropouts detected
    """
    total_dur = max(0.0, float(duration))
    if total_dur <= 0.0:
        return {
            "duration": 0.0,
            "speech_duration": 0.0,
            "non_speech_duration": 0.0,
            "speech_ratio": 0.0,
            "non_speech_ratio": 0.0,
            "gaps": [],
            "longest_gap": 0.0,
            "overall_rms": 0.0,
            "speech_rms": 0.0,
            "non_speech_rms": 0.0,
            "overall_db": -96.0,
            "speech_db": -96.0,
            "non_speech_db": -96.0,
            "has_music_bed": False,
            "dead_silence_count": 0,
            "has_dead_silence": False,
        }

    # 1. Merge overlapping and contiguous speech intervals
    raw_intervals: list[tuple[float, float]] = []
    for w in words:
        s = float(w.get("s", w.get("start", 0.0)))
        e = float(w.get("e", w.get("end", s)))
        s_clamped = max(0.0, min(total_dur, s))
        e_clamped = max(0.0, min(total_dur, e))
        if e_clamped > s_clamped:
            raw_intervals.append((s_clamped, e_clamped))

    raw_intervals.sort()
    merged: list[tuple[float, float]] = []
    for s, e in raw_intervals:
        if not merged:
            merged.append((s, e))
        else:
            prev_s, prev_e = merged[-1]
            if s <= prev_e:
                merged[-1] = (prev_s, max(prev_e, e))
            else:
                merged.append((s, e))

    speech_dur = min(total_dur, sum(e - s for s, e in merged))
    non_speech_dur = max(0.0, total_dur - speech_dur)
    speech_ratio = speech_dur / total_dur if total_dur > 0 else 0.0
    non_speech_ratio = non_speech_dur / total_dur if total_dur > 0 else 0.0

    # 2. Compute non-speech gaps
    gaps: list[dict[str, float]] = []
    cur = 0.0
    for s, e in merged:
        if s > cur:
            gap_len = s - cur
            if gap_len >= 0.05:
                gaps.append({
                    "start": round(cur, 3),
                    "end": round(s, 3),
                    "duration": round(gap_len, 3),
                })
        cur = max(cur, e)

    if cur < total_dur:
        gap_len = total_dur - cur
        if gap_len >= 0.05:
            gaps.append({
                "start": round(cur, 3),
                "end": round(total_dur, 3),
                "duration": round(gap_len, 3),
            })

    longest_gap = max((g["duration"] for g in gaps), default=0.0)

    # 3. Audio Energy Analysis
    pcm: np.ndarray | None = None
    framerate = 16000

    media_str = str(video_or_audio).strip() if video_or_audio is not None else ""
    if media_str:
        media_path = Path(media_str)
        if not media_path.is_file():
            raise FileNotFoundError(f"Media file not found: {media_path}")

        temp_dir: str | None = None
        wav_to_read = media_path

        if media_path.suffix.lower() != ".wav":
            temp_dir = tempfile.mkdtemp(prefix="reel_watcher_energy_")
            wav_to_read = Path(temp_dir) / f"{media_path.stem}.wav"
            try:
                extract_audio(media_path, wav_to_read)
            except Exception:
                wav_to_read = None

        if wav_to_read and wav_to_read.is_file():
            try:
                with wave.open(str(wav_to_read), "rb") as wf:
                    n_channels = wf.getnchannels()
                    sampwidth = wf.getsampwidth()
                    framerate = wf.getframerate()
                    n_frames = wf.getnframes()
                    raw_bytes = wf.readframes(n_frames)

                    if sampwidth == 2:
                        raw_pcm = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                    elif sampwidth == 1:
                        raw_pcm = (np.frombuffer(raw_bytes, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
                    else:
                        raw_pcm = None

                    if raw_pcm is not None and n_channels > 1:
                        raw_pcm = raw_pcm.reshape(-1, n_channels).mean(axis=1)

                    pcm = raw_pcm
            except Exception:
                pcm = None

        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _to_db(rms_val: float) -> float:
        if rms_val <= 1e-5:
            return -96.0
        return float(20.0 * np.log10(rms_val))

    if pcm is not None and len(pcm) > 0:
        total_samples = len(pcm)
        speech_mask = np.zeros(total_samples, dtype=bool)

        for s, e in merged:
            start_idx = max(0, int(s * framerate))
            end_idx = min(total_samples, int(e * framerate))
            speech_mask[start_idx:end_idx] = True

        overall_rms = float(np.sqrt(np.mean(pcm ** 2)))

        speech_samples = pcm[speech_mask]
        speech_rms = (
            float(np.sqrt(np.mean(speech_samples ** 2)))
            if len(speech_samples) > 0
            else 0.0
        )

        non_speech_samples = pcm[~speech_mask]
        non_speech_rms = (
            float(np.sqrt(np.mean(non_speech_samples ** 2)))
            if len(non_speech_samples) > 0
            else 0.0
        )

        overall_db = _to_db(overall_rms)
        speech_db = _to_db(speech_rms)
        non_speech_db = _to_db(non_speech_rms)

        # Has music bed if energy during non-speech gaps exceeds threshold (RMS >= 0.01 / -40 dBFS)
        has_music_bed = bool(non_speech_rms >= 0.01)

        dead_silence_count = 0
        for g in gaps:
            if g["duration"] >= 0.3:
                g_start_idx = max(0, int(g["start"] * framerate))
                g_end_idx = min(total_samples, int(g["end"] * framerate))
                gap_slice = pcm[g_start_idx:g_end_idx]
                if len(gap_slice) > 0:
                    gap_rms = float(np.sqrt(np.mean(gap_slice ** 2)))
                    if gap_rms < 0.005:
                        dead_silence_count += 1
    else:
        overall_rms = 0.0
        speech_rms = 0.0
        non_speech_rms = 0.0
        overall_db = -96.0
        speech_db = -96.0
        non_speech_db = -96.0
        has_music_bed = False
        dead_silence_count = 0

    return {
        "duration": round(total_dur, 3),
        "speech_duration": round(speech_dur, 3),
        "non_speech_duration": round(non_speech_dur, 3),
        "speech_ratio": round(speech_ratio, 3),
        "non_speech_ratio": round(non_speech_ratio, 3),
        "gaps": gaps,
        "longest_gap": round(longest_gap, 3),
        "overall_rms": round(overall_rms, 4),
        "speech_rms": round(speech_rms, 4),
        "non_speech_rms": round(non_speech_rms, 4),
        "overall_db": round(overall_db, 2),
        "speech_db": round(speech_db, 2),
        "non_speech_db": round(non_speech_db, 2),
        "has_music_bed": bool(has_music_bed),
        "dead_silence_count": int(dead_silence_count),
        "has_dead_silence": bool(dead_silence_count > 0),
    }
