"""Unit and integration tests for Audio & Speech Transcription Engine (`audio.py`)."""

from __future__ import annotations

import math
from pathlib import Path
import shutil
import struct
import subprocess
from typing import Any
from unittest.mock import MagicMock, patch
import wave

import pytest

from reel_watcher.audio import (
    extract_audio,
    normalize_transcript_segments,
    transcribe,
    non_speech_energy_heuristic,
)


def _create_synthetic_wav(
    dest_path: Path,
    duration_sec: float = 2.0,
    sample_rate: int = 16000,
    tone_freq: float = 440.0,
    volume: float = 0.5,
    silent_intervals: list[tuple[float, float]] | None = None,
) -> Path:
    """Generate a valid mono 16-bit PCM WAV file with optional silent intervals."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(duration_sec * sample_rate)
    samples: list[int] = []

    intervals = silent_intervals or []

    for i in range(num_samples):
        t = i / sample_rate
        # Check if current time falls in any silent interval
        in_silence = any(s <= t <= e for s, e in intervals)
        if in_silence or volume <= 0.0:
            val = 0
        else:
            val = int(volume * 32767.0 * math.sin(2.0 * math.pi * tone_freq * t))
        val = max(-32768, min(32767, val))
        samples.append(val)

    raw_bytes = struct.pack(f"<{len(samples)}h", *samples)

    with wave.open(str(dest_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(raw_bytes)

    return dest_path


# ==============================================================================
# 1. extract_audio Tests
# ==============================================================================

def test_extract_audio_nonexistent_file(tmp_path: Path) -> None:
    """extract_audio should raise FileNotFoundError if source video does not exist."""
    missing = tmp_path / "missing_video.mp4"
    dest = tmp_path / "output.wav"
    with pytest.raises(FileNotFoundError, match="Video file not found"):
        extract_audio(missing, dest)


def test_extract_audio_missing_ffmpeg(tmp_path: Path) -> None:
    """extract_audio should raise RuntimeError if ffmpeg is missing from PATH."""
    video = tmp_path / "test.mp4"
    video.write_bytes(b"dummy video content")
    dest = tmp_path / "output.wav"

    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="ffmpeg is not found on PATH"):
            extract_audio(video, dest)


def test_extract_audio_subprocess_failure(tmp_path: Path) -> None:
    """extract_audio should raise RuntimeError with stderr if ffmpeg exits with non-zero code."""
    video = tmp_path / "test.mp4"
    video.write_bytes(b"dummy video content")
    dest = tmp_path / "output.wav"

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stderr = "Invalid data found when processing input"

    with patch("shutil.which", return_value="C:\\ffmpeg\\ffmpeg.exe"), \
         patch("subprocess.run", return_value=mock_proc):
        with pytest.raises(RuntimeError, match="ffmpeg audio extraction failed"):
            extract_audio(video, dest)


def test_extract_audio_mock_success(tmp_path: Path) -> None:
    """extract_audio should execute correct ffmpeg parameters and create destination directory."""
    video = tmp_path / "input.mp4"
    video.write_bytes(b"dummy video data")
    out_dir = tmp_path / "nested" / "sub"
    dest = out_dir / "extracted.wav"

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stderr = ""

    with patch("shutil.which", return_value="ffmpeg"), \
         patch("subprocess.run", return_value=mock_proc) as mock_run:
        result = extract_audio(video, dest)
        assert result == dest
        assert out_dir.is_dir()

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-y" in cmd
        assert "-vn" in cmd
        assert "-acodec" in cmd and "pcm_s16le" in cmd
        assert "-ar" in cmd and "16000" in cmd
        assert "-ac" in cmd and "1" in cmd
        assert str(dest) == cmd[-1]


def test_extract_audio_live_ffmpeg(tmp_path: Path) -> None:
    """extract_audio integration test with live ffmpeg."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not available on system PATH")

    # Generate a real 1-second synthetic wav
    src_wav = tmp_path / "input_tone.wav"
    _create_synthetic_wav(src_wav, duration_sec=1.0, sample_rate=44100)

    dest_wav = tmp_path / "extracted_16k.wav"
    out = extract_audio(src_wav, dest_wav)
    assert out.is_file()
    assert out.stat().st_size > 0

    with wave.open(str(out), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        # 1.0 second at 16000Hz = 16000 frames
        assert abs(wf.getnframes() - 16000) < 100


# ==============================================================================
# 2. normalize_transcript_segments Tests
# ==============================================================================

def test_normalize_transcript_segments_empty() -> None:
    """Empty segment list should return standard structure with empty lists."""
    res = normalize_transcript_segments([], language="es")
    assert res == {
        "text": "",
        "language": "es",
        "segments": [],
        "words": [],
    }


def test_normalize_transcript_segments_preformatted_words() -> None:
    """Normalize segments that already have 'w', 's', 'e' formatted words."""
    raw = [
        {
            "id": 0,
            "start": 0.1234,
            "end": 1.4567,
            "text": "Hello world",
            "words": [
                {"w": "Hello", "s": 0.1234, "e": 0.8},
                {"w": "world", "s": 0.81, "e": 1.4567},
            ],
        }
    ]
    res = normalize_transcript_segments(raw, language="en")
    assert res["text"] == "Hello world"
    assert res["language"] == "en"
    assert len(res["segments"]) == 1
    assert res["segments"][0]["start"] == 0.123
    assert res["segments"][0]["end"] == 1.457
    assert res["segments"][0]["text"] == "Hello world"
    assert res["segments"][0]["words"] == [
        {"w": "Hello", "s": 0.123, "e": 0.8},
        {"w": "world", "s": 0.81, "e": 1.457},
    ]
    assert res["words"] == [
        {"w": "Hello", "s": 0.123, "e": 0.8},
        {"w": "world", "s": 0.81, "e": 1.457},
    ]


def test_normalize_transcript_segments_whisper_dict_format() -> None:
    """Normalize OpenAI Whisper format with 'word', 'start', 'end' keys and whitespace."""
    raw = [
        {
            "start": 0.5,
            "end": 2.0,
            "text": " Stop scrolling now! ",
            "words": [
                {"word": " Stop", "start": 0.5, "end": 0.9},
                {"word": " scrolling", "start": 0.95, "end": 1.5},
                {"word": " now!", "start": 1.52, "end": 2.0},
            ],
        }
    ]
    res = normalize_transcript_segments(raw)
    assert res["text"] == "Stop scrolling now!"
    assert len(res["words"]) == 3
    assert res["words"][0] == {"w": "Stop", "s": 0.5, "e": 0.9}
    assert res["words"][1] == {"w": "scrolling", "s": 0.95, "e": 1.5}
    assert res["words"][2] == {"w": "now!", "s": 1.52, "e": 2.0}


def test_normalize_transcript_segments_faster_whisper_objects() -> None:
    """Normalize object instances (faster-whisper style) with attributes."""
    class DummyWord:
        def __init__(self, word: str, start: float, end: float) -> None:
            self.word = word
            self.start = start
            self.end = end

    class DummySegment:
        def __init__(self, id_val: int, text: str, start: float, end: float, words: list[Any]) -> None:
            self.id = id_val
            self.text = text
            self.start = start
            self.end = end
            self.words = words

    seg1 = DummySegment(
        id_val=0,
        text=" First tip ",
        start=0.0,
        end=1.2,
        words=[DummyWord("First", 0.0, 0.5), DummyWord("tip", 0.55, 1.2)],
    )
    seg2 = DummySegment(
        id_val=1,
        text=" second tip ",
        start=1.5,
        end=2.5,
        words=[DummyWord("second", 1.5, 1.9), DummyWord("tip", 2.0, 2.5)],
    )

    res = normalize_transcript_segments([seg1, seg2], language="en")
    assert res["text"] == "First tip second tip"
    assert len(res["segments"]) == 2
    assert len(res["words"]) == 4
    assert res["words"][0] == {"w": "First", "s": 0.0, "e": 0.5}
    assert res["words"][3] == {"w": "tip", "s": 2.0, "e": 2.5}


def test_normalize_transcript_segments_interpolate_missing_words() -> None:
    """If words list is missing or empty, synthesize word-level timestamps across segment duration."""
    raw = [
        {
            "id": 0,
            "start": 1.0,
            "end": 3.0,
            "text": "Three word hook",
            "words": [],
        }
    ]
    res = normalize_transcript_segments(raw)
    assert len(res["words"]) == 3
    assert res["words"][0]["w"] == "Three"
    assert res["words"][0]["s"] == 1.0
    assert res["words"][1]["w"] == "word"
    assert res["words"][2]["w"] == "hook"
    assert res["words"][2]["e"] == 3.0
    # Segments words should also be populated
    assert res["segments"][0]["words"] == res["words"]


# ==============================================================================
# 3. transcribe Engine & Fallback Tests
# ==============================================================================

def test_transcribe_nonexistent_file(tmp_path: Path) -> None:
    """transcribe should raise FileNotFoundError if media file is missing."""
    missing = tmp_path / "ghost_video.mp4"
    with pytest.raises(FileNotFoundError, match="Media file not found"):
        transcribe(missing)


def test_transcribe_video_without_audio(tmp_path: Path) -> None:
    """transcribe should return empty transcript if probe reports no audio."""
    dummy_video = tmp_path / "silent.mp4"
    dummy_video.write_bytes(b"dummy")

    with patch("reel_watcher.audio.probe", return_value={"has_audio": False, "duration": 5.0}):
        res = transcribe(dummy_video)
        assert res["text"] == ""
        assert res["backend"] == "none"
        assert res["segments"] == []
        assert res["words"] == []


def test_transcribe_faster_whisper_backend(tmp_path: Path) -> None:
    """transcribe should execute faster-whisper when available."""
    audio_file = tmp_path / "sample.wav"
    audio_file.write_bytes(b"RIFF dummy wav")

    mock_word = MagicMock(word=" hello", start=0.1, end=0.8)
    mock_segment = MagicMock(id=0, text=" hello", start=0.1, end=0.8, words=[mock_word])
    mock_info = MagicMock(language="en", duration=1.0)

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([mock_segment], mock_info)

    mock_cls = MagicMock(return_value=mock_model)

    with patch.dict("sys.modules", {"faster_whisper": MagicMock(WhisperModel=mock_cls)}), \
         patch("reel_watcher.audio.probe", return_value={"has_audio": True, "duration": 1.0}):
        res = transcribe(audio_file, backend="faster-whisper", model_name="base")
        assert res["backend"] == "faster-whisper"
        assert res["text"] == "hello"
        assert res["language"] == "en"
        assert len(res["words"]) == 1
        assert res["words"][0]["w"] == "hello"


def test_transcribe_openai_whisper_backend(tmp_path: Path) -> None:
    """transcribe should execute openai-whisper when requested."""
    audio_file = tmp_path / "sample.wav"
    audio_file.write_bytes(b"RIFF dummy wav")

    mock_model = MagicMock()
    mock_model.transcribe.return_value = {
        "text": "test speech",
        "language": "en",
        "segments": [
            {
                "id": 0,
                "text": "test speech",
                "start": 0.0,
                "end": 1.0,
                "words": [
                    {"word": "test", "start": 0.0, "end": 0.4},
                    {"word": "speech", "start": 0.45, "end": 1.0},
                ],
            }
        ],
    }

    mock_whisper = MagicMock(load_model=MagicMock(return_value=mock_model))

    with patch.dict("sys.modules", {"whisper": mock_whisper}), \
         patch("reel_watcher.audio.probe", return_value={"has_audio": True, "duration": 1.0}):
        res = transcribe(audio_file, backend="openai-whisper", model_name="base")
        assert res["backend"] == "openai-whisper"
        assert res["text"] == "test speech"
        assert len(res["words"]) == 2


def test_transcribe_mlx_whisper_backend(tmp_path: Path) -> None:
    """transcribe should execute mlx-whisper when requested."""
    audio_file = tmp_path / "sample.wav"
    audio_file.write_bytes(b"RIFF dummy wav")

    mock_mlx = MagicMock()
    mock_mlx.transcribe.return_value = {
        "text": "mlx transcription",
        "language": "en",
        "segments": [
            {
                "id": 0,
                "text": "mlx transcription",
                "start": 0.0,
                "end": 1.5,
                "words": [
                    {"word": "mlx", "start": 0.0, "end": 0.5},
                    {"word": "transcription", "start": 0.6, "end": 1.5},
                ],
            }
        ],
    }

    with patch.dict("sys.modules", {"mlx_whisper": mock_mlx}), \
         patch("reel_watcher.audio.probe", return_value={"has_audio": True, "duration": 1.5}):
        res = transcribe(audio_file, backend="mlx-whisper", model_name="base")
        assert res["backend"] == "mlx-whisper"
        assert res["text"] == "mlx transcription"
        assert len(res["words"]) == 2


def test_transcribe_fallback_chain_faster_to_openai(tmp_path: Path) -> None:
    """auto backend falls back to openai-whisper if faster-whisper fails."""
    audio_file = tmp_path / "sample.wav"
    audio_file.write_bytes(b"RIFF dummy wav")

    # faster-whisper raises ImportError or RuntimeError
    mock_fw = MagicMock()
    mock_fw.WhisperModel.side_effect = ImportError("No ctranslate2 module")

    # openai-whisper succeeds
    mock_ow_model = MagicMock()
    mock_ow_model.transcribe.return_value = {
        "text": "fallback text",
        "language": "en",
        "segments": [
            {
                "id": 0,
                "text": "fallback text",
                "start": 0.0,
                "end": 1.0,
                "words": [{"word": "fallback", "start": 0.0, "end": 0.5}],
            }
        ],
    }
    mock_ow = MagicMock(load_model=MagicMock(return_value=mock_ow_model))

    with patch.dict("sys.modules", {"faster_whisper": mock_fw, "whisper": mock_ow}), \
         patch("reel_watcher.audio.probe", return_value={"has_audio": True, "duration": 1.0}):
        res = transcribe(audio_file, backend="auto")
        assert res["backend"] == "openai-whisper"
        assert res["text"] == "fallback text"


def test_transcribe_fallback_chain_all_fail_graceful_empty(tmp_path: Path) -> None:
    """auto backend returns graceful empty transcript with [!] warning when all engines fail."""
    audio_file = tmp_path / "sample.wav"
    audio_file.write_bytes(b"RIFF dummy wav")

    # Force all to fail
    with patch.dict("sys.modules", {"faster_whisper": None, "whisper": None, "mlx_whisper": None}), \
         patch("reel_watcher.audio.probe", return_value={"has_audio": True, "duration": 1.0}):
        res = transcribe(audio_file, backend="auto")
        assert res["backend"] == "none"
        assert res["text"] == ""
        assert res["segments"] == []
        assert res["words"] == []


def test_transcribe_unsupported_backend_raises_value_error(tmp_path: Path) -> None:
    """transcribe should raise ValueError on unrecognized backend string."""
    audio_file = tmp_path / "sample.wav"
    audio_file.write_bytes(b"RIFF dummy wav")

    with pytest.raises(ValueError, match="Unsupported transcription backend"):
        transcribe(audio_file, backend="unknown_engine")


def test_transcribe_extracts_video_to_temp_audio(tmp_path: Path) -> None:
    """When a video file (.mp4) is passed, extract_audio is called to create temporary WAV."""
    video = tmp_path / "input.mp4"
    video.write_bytes(b"dummy video")

    dummy_wav_holder: list[Path] = []

    def mock_extract(src: Path | str, dst: Path | str) -> Path:
        out = Path(dst)
        out.write_bytes(b"RIFF dummy extracted wav")
        dummy_wav_holder.append(out)
        return out

    mock_result = {
        "text": "video transcribed",
        "language": "en",
        "segments": [],
        "words": [],
    }

    with patch("reel_watcher.audio.extract_audio", side_effect=mock_extract) as mock_ext, \
         patch("reel_watcher.audio.probe", return_value={"has_audio": True, "duration": 2.0}), \
         patch("reel_watcher.audio._transcribe_with_backend", return_value=mock_result):
        res = transcribe(video, backend="auto")
        mock_ext.assert_called_once()
        assert res["text"] == "video transcribed"
        # Temporary wav should be cleaned up
        if dummy_wav_holder:
            assert not dummy_wav_holder[0].exists()


# ==============================================================================
# 4. non_speech_energy_heuristic Tests
# ==============================================================================

def test_non_speech_energy_heuristic_nonexistent_file(tmp_path: Path) -> None:
    """non_speech_energy_heuristic should raise FileNotFoundError if file path is missing."""
    missing = tmp_path / "missing.wav"
    with pytest.raises(FileNotFoundError, match="Media file not found"):
        non_speech_energy_heuristic(missing, words=[], duration=5.0)


def test_non_speech_energy_heuristic_zero_duration() -> None:
    """non_speech_energy_heuristic with zero or negative duration returns zeroed dict."""
    res = non_speech_energy_heuristic("", words=[], duration=0.0)
    assert res["duration"] == 0.0
    assert res["speech_duration"] == 0.0
    assert res["non_speech_duration"] == 0.0
    assert res["speech_ratio"] == 0.0
    assert res["gaps"] == []
    assert res["has_music_bed"] is False


def test_non_speech_energy_heuristic_timing_only_without_audio() -> None:
    """Computes accurate speech timing metrics and gaps without audio file."""
    words = [
        {"w": "Stop", "s": 0.5, "e": 1.0},
        {"w": "right", "s": 1.1, "e": 1.5},
        {"w": "there", "s": 1.6, "e": 2.5},
    ]
    # Total duration = 4.0s
    # Speech intervals: [0.5, 1.0] (0.5s), [1.1, 1.5] (0.4s), [1.6, 2.5] (0.9s)
    # Total speech = 1.8s
    # Non-speech: 4.0 - 1.8 = 2.2s
    # Gaps: [0.0, 0.5] (0.5s), [1.0, 1.1] (0.1s), [1.5, 1.6] (0.1s), [2.5, 4.0] (1.5s)
    res = non_speech_energy_heuristic("", words=words, duration=4.0)
    assert res["duration"] == 4.0
    assert res["speech_duration"] == 1.8
    assert res["non_speech_duration"] == 2.2
    assert res["speech_ratio"] == 0.45
    assert res["non_speech_ratio"] == 0.55
    assert len(res["gaps"]) == 4
    assert res["longest_gap"] == 1.5


def test_non_speech_energy_heuristic_with_silent_gaps(tmp_path: Path) -> None:
    """Synthetic WAV with speech tone and silent gaps detects dead silence and no music bed."""
    # 3.0s total: speech active at [0.5, 1.5], silence at [0.0, 0.5] and [1.5, 3.0]
    wav_path = tmp_path / "silent_gaps.wav"
    _create_synthetic_wav(
        wav_path,
        duration_sec=3.0,
        volume=0.8,
        silent_intervals=[(0.0, 0.5), (1.5, 3.0)],
    )

    words = [{"w": "speech", "s": 0.5, "e": 1.5}]
    res = non_speech_energy_heuristic(wav_path, words=words, duration=3.0)

    assert res["has_music_bed"] is False
    assert res["has_dead_silence"] is True
    assert res["dead_silence_count"] >= 1
    assert res["speech_rms"] > 0.1
    assert res["non_speech_rms"] < 0.01


def test_non_speech_energy_heuristic_with_continuous_music_bed(tmp_path: Path) -> None:
    """Synthetic WAV with continuous audio throughout reports has_music_bed=True."""
    wav_path = tmp_path / "music_bed.wav"
    # Audio present continuously (no silence)
    _create_synthetic_wav(wav_path, duration_sec=3.0, volume=0.5, silent_intervals=[])

    words = [{"w": "speech", "s": 0.5, "e": 1.5}]
    res = non_speech_energy_heuristic(wav_path, words=words, duration=3.0)

    assert res["has_music_bed"] is True
    assert res["has_dead_silence"] is False
    assert res["dead_silence_count"] == 0
    assert res["non_speech_rms"] > 0.1
