# Clipper

**Turn one long video into short clips ready to post: captions, AI music, every aspect ratio, checked before you download. Runs on your own PC, free.**

Paste a YouTube link or drop an MP4. Clipper transcribes it, picks the strongest moments, reframes them for Shorts, Reels and TikTok, adds animated captions, a hook title and a generated music bed, then verifies every file.

It works for **talking videos** (podcasts, interviews, vlogs, any language including Arabic) and for **gameplay** (GTA, Fortnite and so on), where it finds highlights from the action instead of the words.

## What it does

| Step | What happens | Tech |
|---|---|---|
| 1. Import | YouTube or any yt-dlp supported link, or a local MP4, MOV, MKV or WEBM | yt-dlp, FFmpeg |
| 2. Transcribe | Word level timestamps on the GPU, language detected automatically | faster-whisper |
| 3. Pick clips | **Talking:** an AI reads the transcript and picks self contained moments with a hook. **Gameplay:** loudness, sudden bursts (gunfire, explosions), on screen motion and scene cuts are scored to find the action | Ollama (free, local) or Claude API, NumPy, OpenCV |
| 4. Style | Word by word animated captions, a hook title for the first 3 seconds, punch in zoom, and an instrumental track generated for each clip that ducks under the voice | libass, MusicGen |
| 5. Formats | Every clip rendered in 9:16, 1:1 and 16:9 | FFmpeg, NVENC or x264 |
| 6. Verify | Resolution, duration, audio, codec, loudness (−14 LUFS), black frames, dead air and captions. A render that fails is redone once on the CPU encoder | ffprobe, ebur128 |

### Framing when the shape doesn't match

| Option | Result |
|---|---|
| Show the whole video, blurred fill | Nothing is cut off. A blurred copy fills the empty space (default) |
| Show the whole video, black bars | Same, with plain bars |
| Crop to fill, follow the face | Fills the frame, centred on the speaker |
| Stacked: facecam on top, gameplay below | For streams with a webcam. It finds the webcam automatically or uses the corner you pick |
| Stacked: whole frame on top, zoomed action below | For gameplay without a webcam |

### Who picks the clips

| Picker | Cost | Notes |
|---|---|---|
| Free local AI | Free | Ollama with `qwen2.5:7b`, runs on your GPU |
| Claude | Paid API, a few cents per video | Best judgement, needs `ANTHROPIC_API_KEY` |
| Simple rules | Free | Fastest. Also the fallback if the others aren't available |

## Requirements

- Windows 10 or 11 (the code is plain Python and should also run on Linux with small path changes)
- Python 3.11 or newer
- An NVIDIA GPU with 6 GB or more is recommended. CPU works, slowly
- FFmpeg
- Optional: [Ollama](https://ollama.com) for the free AI picker

## Setup

```bash
git clone https://github.com/mohamedashraf23/clipper.git
cd clipper
winget install Gyan.FFmpeg
python -m venv .venv
.venv\Scripts\python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
.venv\Scripts\python -m pip install -r requirements.txt
```

For the free AI picker:

```bash
winget install Ollama.Ollama
ollama pull qwen2.5:7b
```

Optional: copy `.env.example` to `.env` to add a Claude key or change models. The file is ignored by git, so your key never gets committed.

The first run downloads the Whisper model (`small`, about 500 MB) and MusicGen small (about 1 GB) into your Hugging Face cache.

## Run

Double click `start.bat`, or:

```bash
.venv\Scripts\python server.py
```

Then open http://127.0.0.1:8765. The server only listens on your own machine.

## Output

Each run gets its own folder in `jobs/<job-id>/`:

- `NN-title/NN-title_9x16.mp4` (plus `_1x1` and `_16x9`): the finished clips, each with a poster image
- `transcript.json`: the word level transcript
- `job.json`: the picks, hooks, music prompts and verify results

Videos can be large. If your project folder is synced (OneDrive, Dropbox), set `CLIPPER_JOBS_DIR` in `.env` to a folder outside it.

## Project layout

```
server.py            FastAPI app and API routes
web/index.html       The interface (single page, no build step)
clipper/
  pipeline.py        Runs the six steps for a job and keeps job.json current
  ingest.py          Download or copy the video, extract audio
  transcribe.py      faster-whisper with word timestamps
  picker.py          Clip picking for talking videos (Ollama, Claude, rules)
  highlights.py      Clip picking for gameplay (audio and motion signals)
  captions.py        Animated ASS captions and hook titles, right to left aware
  music.py           MusicGen background tracks
  reframe.py         Face and facecam detection
  render.py          FFmpeg filter graphs for every framing and the audio mix
  verify.py          Checks on every finished file
```

## Notes

- One job runs at a time, so Whisper, the local AI and MusicGen take turns on the GPU.
- MusicGen writes up to 30 seconds of music. Longer clips loop it with a fade in and out.
- Only clip videos you have the rights to use, and check each platform's rules for game footage.
