"""Step 4c: cut, reframe, animate, caption and mix one clip into one aspect ratio."""
import re
from pathlib import Path

from . import ff
from .reframe import crop_box


def _zoom_expr(style: str, fps: float) -> str:
    if style == "punch":
        # jump-cut zoom: alternate 1.00x / 1.12x every 4 s (no sub-pixel drift, so no jitter)
        period = int(round(fps * 4))
        return f"if(lt(mod(on,{2 * period}),{period}),1,1.12)"
    if style == "slow":
        # gentle push-in over the clip
        return "min(1+0.0006*on,1.15)"
    return "1"


TARGET_LUFS = -14.0
STACK_CAM_TOP = 0.40  # share of the height the facecam panel takes


def stack_geometry(framing: str, sw: int, sh: int, out_w: int, out_h: int,
                   facecam: tuple[int, int, int, int] | None = None) -> tuple[int, tuple[int, int, int, int]]:
    """Height of the top panel, and the source crop (w, h, x, y) shown in the bottom panel.
    With a facecam, the gameplay crop slides sideways so the webcam box doesn't show twice."""
    if framing == "stack_cam":
        top_h = int(out_h * STACK_CAM_TOP) // 2 * 2
        zoom = 1.0
    else:  # whole frame on top at full width, zoomed centre below
        top_h = int(out_w * sh / sw) // 2 * 2
        zoom = 1.25
    bot_aspect = out_w / (out_h - top_h)
    bh = int(sh / zoom) // 2 * 2
    bw = min(sw, int(bh * bot_aspect)) // 2 * 2
    bh = min(bh, int(bw / bot_aspect)) // 2 * 2
    bx = (sw - bw) // 2
    if facecam:
        cw, _, cx, _ = facecam
        margin = int(sw * 0.05)  # the detected box can be a little smaller than the real overlay
        if cx + cw / 2 > sw / 2:   # webcam on the right: end the crop before it
            bx = min(bx, max(0, cx - margin - bw))
        else:                      # webcam on the left: start the crop after it
            bx = max(bx, min(sw - bw, cx + cw + margin))
    return top_h, (bw, bh, bx // 2 * 2, (sh - bh) // 2 // 2 * 2)


def facecam_aspect(out_w: int, out_h: int) -> float:
    return out_w / (int(out_h * STACK_CAM_TOP) // 2 * 2)


def measure_lufs(path: Path) -> float | None:
    log = ff.run(["-i", path.name, "-vn", "-af", "ebur128=framelog=quiet", "-f", "null", "-"], cwd=path.parent).stderr
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", log)
    return float(m[-1]) if m else None


def _fix_loudness(path: Path):
    """Single-pass loudnorm undershoots on short clips; measure and apply the exact gain (video is copied)."""
    lufs = measure_lufs(path)
    if lufs is None or abs(lufs - TARGET_LUFS) <= 0.7:
        return
    gain = max(-12.0, min(12.0, TARGET_LUFS - lufs))
    tmp = path.with_name(path.stem + ".gain" + path.suffix)
    ff.run(["-i", path.name, "-map", "0", "-c:v", "copy",
            "-af", f"volume={gain:.2f}dB,alimiter=limit=0.89:level=false",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", tmp.name], cwd=path.parent)
    tmp.replace(path)


def render_clip(*, source: str, src_meta: dict, start: float, end: float, out_w: int, out_h: int,
                face: tuple[float, float] | None, ass_file: Path | None, music_file: Path | None,
                music_volume: float, zoom: str, out_path: Path, encoder: str | None = None,
                framing: str = "fit", facecam: tuple[int, int, int, int] | None = None) -> Path:
    """framing: 'fit' = whole video over a blurred copy of itself (nothing cut off),
    'fit_black' = whole video with black bars, 'crop' = fill the frame, centred on the face,
    'stack_cam' = facecam on top, gameplay below, 'stack_zoom' = whole frame on top, zoomed action below.
    Stacked layouts only apply to tall outputs; other shapes fall back to 'fit'."""
    duration = end - start
    fps = min(60.0, src_meta["fps"] or 30.0)
    sw, sh = src_meta["width"], src_meta["height"]
    same_shape = abs(sw / sh - out_w / out_h) < 0.01
    tall = out_h > out_w * 1.2 and sw > sh
    if framing in ("stack_cam", "stack_zoom") and not tall:
        framing = "fit"
    if framing == "stack_cam" and not facecam:
        framing = "stack_zoom"
    if framing not in ("fit", "fit_black", "crop", "stack_cam", "stack_zoom"):
        framing = "fit"

    vf = []
    if framing in ("stack_cam", "stack_zoom"):
        top_h, bot_crop = stack_geometry(framing, sw, sh, out_w, out_h, facecam if framing == "stack_cam" else None)
        bot_h = out_h - top_h
        bw, bh, bx, by = bot_crop
        if framing == "stack_cam":
            cw, ch, cx, cy = facecam
            top = f"crop={cw}:{ch}:{cx}:{cy},scale={out_w}:{top_h}:force_original_aspect_ratio=increase:flags=lanczos,crop={out_w}:{top_h}"
        else:
            top = f"scale={out_w}:{top_h}:flags=lanczos"
        vf.append(
            f"split=2[topsrc][botsrc];"
            f"[topsrc]{top},setsar=1[top];"
            f"[botsrc]crop={bw}:{bh}:{bx}:{by},scale={out_w}:{bot_h}:flags=lanczos,setsar=1[bot];"
            f"[top][bot]vstack=inputs=2"
        )
    elif framing != "crop" and not same_shape:
        # the whole picture, scaled to fit inside the canvas; zoom would cut parts off, so it only moves the background
        fit = f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags=lanczos,setsar=1"
        if framing == "fit_black":
            vf.append(f"{fit},pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black")
        else:
            bw, bh = out_w // 4 // 2 * 2, out_h // 4 // 2 * 2  # blur at quarter size: same look, much faster
            bg_zoom = ""
            if zoom in ("punch", "slow"):
                bg_zoom = f",zoompan=z='min(1+0.0004*on,1.1)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={bw}x{bh}:fps={fps:.3f}"
            vf.append(
                f"split=2[bgsrc][fgsrc];"
                f"[bgsrc]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh}{bg_zoom},"
                f"boxblur=12:3,eq=brightness=-0.12:saturation=1.1,scale={out_w}:{out_h},setsar=1[bg];"
                f"[fgsrc]{fit}[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2:shortest=1"
            )
    else:
        cw, ch, cx, cy = crop_box(src_meta["width"], src_meta["height"], out_w, out_h, face)
        vf.append(f"crop={cw}:{ch}:{cx}:{cy}")
        if zoom in ("punch", "slow"):
            z = _zoom_expr(zoom, fps)
            # upscale first so the zoom window has real pixels to work with
            vf.append(f"scale={out_w * 2 if zoom == 'slow' else out_w}:-2:flags=lanczos")
            vf.append(f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih*0.42-(ih/zoom*0.42)':d=1:s={out_w}x{out_h}:fps={fps:.3f}")
        else:
            vf.append(f"scale={out_w}:{out_h}:flags=lanczos")
    vf.append("setsar=1")
    if ass_file:
        # run with cwd = clip folder and a bare filename: avoids Windows drive-letter escaping
        vf.append(f"subtitles=filename={ass_file.name}:fontsdir='C\\:/Windows/Fonts'")
    vf.append("format=yuv420p")

    args = ["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", source]
    if music_file:
        args += ["-stream_loop", "-1", "-i", music_file]

    fade_out = max(0.0, duration - 1.5)
    if music_file:
        filt = (
            f"[0:v]{','.join(vf)}[v];"
            f"[1:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,volume={music_volume:.3f},"
            f"afade=t=in:st=0:d=0.8,afade=t=out:st={fade_out:.3f}:d=1.5[m];"
            f"[0:a]aresample=48000,asplit=2[voice][sc];"
            f"[m]aresample=48000[m48];"
            f"[m48][sc]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=350[duck];"
            f"[voice][duck]amix=inputs=2:duration=first:normalize=0,"
            f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]"
        )
    else:
        filt = f"[0:v]{','.join(vf)}[v];[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]"

    enc = encoder or ("h264_nvenc" if ff.nvenc_works() else "libx264")
    if enc == "h264_nvenc":
        venc = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0", "-profile:v", "high"]
    else:
        venc = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high"]

    args += ["-filter_complex", filt, "-map", "[v]", "-map", "[a]", *venc,
             "-r", f"{fps:.3f}", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
             "-t", f"{duration:.3f}", "-movflags", "+faststart", out_path.name]
    ff.run(args, cwd=out_path.parent)
    _fix_loudness(out_path)

    # poster frame for the web page
    ff.run(["-ss", f"{min(1.5, duration / 2):.2f}", "-i", out_path.name, "-frames:v", "1", "-q:v", "3",
            out_path.with_suffix(".jpg").name], cwd=out_path.parent)
    return out_path
