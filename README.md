# Clipper

**Turn one long video into short clips ready to post: captions, AI music, every aspect ratio, checked before you download. Runs on your own PC, free.**

Paste a YouTube link or drop an MP4. Clipper transcribes it, picks the strongest moments, reframes them for Shorts, Reels and TikTok, adds animated captions, a hook title and a generated music bed, then verifies every file.

It works for **talking videos** (podcasts, interviews, vlogs, any language including Arabic) and for **gameplay** (GTA, Fortnite and so on), where it finds highlights from the action instead of the words.

## What it does

| Step | What happens | Tech |
|---|---|---|
| 1. Import | YouTube or any yt-dlp supported link, or a local MP4, MOV, MKV or WEBM | yt-dlp, FFmpeg |
| 2. Transcribe | Word level timestamps on the GPU, language detected automatically | faster-whisper |
| 3. Pick clips | **Talking:** an AI reads the transcript and picks self contained moments with a hook. **Gameplay:** on screen motion, sudden bursts (gunfire, explosions), loudness and scene cuts are scored to find the action; cutscenes and shouting in dialogue count for less | Ollama (free, local) or Claude API, NumPy, OpenCV |
| 4. Style | Jump cuts that trim pauses and filler words (talking videos), word by word animated captions, a hook title for the first 3 seconds, punch in zoom, and an instrumental track generated for each clip that ducks under the voice | FFmpeg, libass, MusicGen |
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

### Jump cuts

For talking videos, pauses between 0.45 and 2.5 seconds are shortened to 0.2 seconds and filler words (um, uh, erm and common Arabic hesitations) are removed. Longer gaps are kept, since they're usually laughter or a reaction. Captions follow the new timing. Turn it off with **Cut pauses and filler words**.

### Re-run with new settings

Open any finished job and press **Re-run with these settings** to try another framing, caption style or clip length on the same video. Nothing is downloaded again, the video is linked rather than copied, and the transcript is reused when the Whisper model and language are unchanged.

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
- Node.js 20 or newer, to build the interface once (and when you change it)
- Optional: [Ollama](https://ollama.com) for the free AI picker

## Setup

```bash
git clone https://github.com/mohamedashraf23/clipper.git
cd clipper
winget install Gyan.FFmpeg
python -m venv .venv
.venv\Scripts\python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
.venv\Scripts\python -m pip install -r requirements.txt
winget install OpenJS.NodeJS.LTS
```

For the free AI picker:

```bash
winget install Ollama.Ollama
ollama pull qwen2.5:7b
```

Optional: copy `.env.example` to `.env` to add a Claude key or change models. The file is ignored by git, so your key never gets committed.

The first run downloads the Whisper model (`small`, about 500 MB) and MusicGen small (about 1 GB) into your Hugging Face cache.

## Run

Double click `start.bat`. On the first run it builds the interface, then starts the server and opens http://127.0.0.1:8765. The server only listens on your own machine.

To do it by hand:

```bash
cd frontend
npm ci
npm run build
cd ..
.venv\Scripts\python server.py
```

## Working on the interface

The interface is a Next.js app in `frontend/` (React, TypeScript, [Motion](https://motion.dev) for animation, [Phosphor](https://phosphoricons.com) icons). It's exported as static files to `frontend/out`, which `server.py` serves, so no Node server runs in normal use.

For live reload while editing, keep the Python server running and start the dev server next to it:

```bash
cd frontend
npm run dev
```

Then open http://localhost:3000. It calls the Python API on port 8765 directly (see `frontend/.env.development`). Run `npm run build` when you're done so `start.bat` picks up the changes.

Animations respect your system's reduced motion setting.

## Output

Each run gets its own folder in the jobs folder: `jobs/` in the project, or `~/clipper-jobs` when the project sits inside a synced folder such as OneDrive or Dropbox (so the sync client doesn't upload every video). Set `CLIPPER_JOBS_DIR` in `.env` to choose another place.

- `NN-title/NN-title_9x16.mp4` (plus `_1x1` and `_16x9`): the finished clips, each with a poster image
- `transcript.json`: the word level transcript
- `job.json`: the picks, hooks, music prompts and verify results


## Project layout

```
server.py            FastAPI app: API routes, serves the built interface and the clips
frontend/            Next.js interface
  app/page.tsx       Page state and job polling
  components/        Header, settings form, history, job view, clip cards, empty state
  lib/api.ts         Typed client for the API
  lib/motion.ts      Shared easing and animation presets
clipper/
  pipeline.py        Runs the six steps for a job and keeps job.json current
  ingest.py          Download or copy the video, extract audio
  transcribe.py      faster-whisper with word timestamps
  picker.py          Clip picking for talking videos (Ollama, Claude, rules)
  highlights.py      Clip picking for gameplay (motion, audio bursts, cutscene detection)
  tighten.py         Jump cuts: which pieces of a talking clip to keep
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

## License

[MIT](LICENSE). The models Clipper downloads (Whisper, MusicGen, Qwen) come with their own licenses. MusicGen weights are for non commercial use.
