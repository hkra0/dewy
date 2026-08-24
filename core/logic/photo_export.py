"""每日照片延时视频 (MP4) 与动图 (GIF) 流式合成与导出。

设计考量：
1. 树莓派 Zero 2 W 内存仅 512MB，处理高清原图（每张 ~3-5MB）时绝对不能
   将所有图片一次性读入内存。采用流式管道（Stream Pipeline）：
   逐帧读入 -> PIL 缩放加水印 -> 管道输入 ffmpeg -> 逐帧编码。
   整个生命周期内存占用恒定 < 25MB。
2. 编码生成标准 H.264 MP4（yuv420p + faststart），全平台（iOS/Android/浏览器/微信）
   原生硬件解码，体积极小（100 帧仅 ~2-4MB），传输仅需数秒。
3. 自动缓存结果并定期清理，避免相同请求重复耗费 CPU 渲染。
"""

import hashlib
import io
import logging
import os
import shutil
import subprocess
import time
from typing import Optional, List, Tuple
from PIL import Image, ImageDraw, ImageFont

import core.state as state
import core.database as db

logger = logging.getLogger(__name__)

# 最大合成帧数（与前端保持一致：120 帧，超过时均匀抽样保留起止）
DEFAULT_MAX_FRAMES = 120
CACHE_TTL_SEC = 12 * 3600  # 缓存 12 小时


def select_frames(photos: List[Tuple[str, str]], max_frames: int = DEFAULT_MAX_FRAMES) -> List[Tuple[str, str]]:
    """超过上限时均匀抽样，并保证首尾两帧一定入选。
    
    photos: 列表，每个元素为 (date_str, filename)
    """
    if len(photos) <= max_frames:
        return photos
    step = (len(photos) - 1) / (max_frames - 1)
    picked = []
    for i in range(max_frames):
        picked.append(photos[round(i * step)])
    return picked


def _clean_expired_cache():
    """清理过期的导出缓存文件。"""
    try:
        now = time.time()
        if not os.path.exists(state.EXPORT_CACHE_DIR):
            return
        for f in os.listdir(state.EXPORT_CACHE_DIR):
            fpath = os.path.join(state.EXPORT_CACHE_DIR, f)
            if os.path.isfile(fpath):
                if now - os.path.getmtime(fpath) > CACHE_TTL_SEC:
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass
    except Exception as e:
        logger.warning("清理导出缓存异常: %s", e)


def _draw_watermark(img: Image.Image, date_str: str) -> Image.Image:
    """在图片左下角绘制统一半透明暗底白字日期水印。"""
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size

    # 根据画幅高度自适应字号
    font_size = max(13, int(h * 0.032))
    font = None
    try:
        # 尝试使用常见 TTF 字体
        for font_name in ("DejaVuSans.ttf", "FreeSans.ttf", "Arial.ttf", "Helvetica.ttf"):
            try:
                font = ImageFont.truetype(font_name, font_size)
                break
            except Exception:
                continue
    except Exception:
        font = None

    if font is None:
        font = ImageFont.load_default()

    text = f"📅 {date_str}"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    pad_x = max(8, int(font_size * 0.5))
    pad_y = max(4, int(font_size * 0.3))
    box_w = tw + pad_x * 2
    box_h = th + pad_y * 2
    box_x = max(10, int(w * 0.025))
    box_y = h - box_h - max(10, int(h * 0.025))

    # 半透明黑色背景框
    draw.rounded_rectangle(
        [(box_x, box_y), (box_x + box_w, box_y + box_h)],
        radius=max(4, int(font_size * 0.3)),
        fill=(0, 0, 0, 160)
    )

    # 白色文字
    text_x = box_x + pad_x
    text_y = box_y + (box_h - th) // 2 - bbox[1]
    draw.text((text_x, text_y), text, fill=(255, 255, 255, 240), font=font)

    return img


def _process_frame(
    photo_path: str,
    date_str: str,
    target_max_dim: int,
    watermark: bool,
    target_size: Optional[Tuple[int, int]] = None,
) -> Optional[Image.Image]:
    """读取单张图片，按目标最大边长缩放至偶数分辨率，并可选绘制水印。"""
    try:
        with Image.open(photo_path) as src_img:
            # 转为 RGB（防止 RGBA 或调色板模式）
            img = src_img.convert("RGB")
            orig_w, orig_h = img.size

            if target_size is not None:
                # 若已指定基准画幅（后续帧），严格保证与基准画幅尺寸一致
                if img.size != target_size:
                    img = img.resize(target_size, Image.Resampling.LANCZOS)
            else:
                # 计算等比例缩放尺寸
                scale = min(1.0, target_max_dim / max(orig_w, orig_h))
                new_w = int(orig_w * scale)
                new_h = int(orig_h * scale)

                # H.264 编码要求宽高必须为偶数
                new_w = (new_w // 2) * 2
                new_h = (new_h // 2) * 2
                if new_w < 2:
                    new_w = 2
                if new_h < 2:
                    new_h = 2

                if (new_w, new_h) != (orig_w, orig_h):
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            if watermark:
                img = _draw_watermark(img, date_str)

            return img
    except Exception as e:
        logger.warning("处理照片帧失败 %s (%s): %s", date_str, photo_path, e)
        return None


def export_timelapse(
    export_format: str = "mp4",
    quality: str = "hd",
    fps: float = 2.0,
    watermark: bool = True,
    max_frames: int = DEFAULT_MAX_FRAMES,
) -> str:
    """流式合成延时视频 (MP4) 或动图 (GIF)，返回生成的文件绝对路径。

    :param export_format: "mp4" 或 "gif"
    :param quality: "hd" (原图缩放至最高 1080p) 或 "sd" (最高 480p)
    :param fps: 帧率 (0.5 ~ 30.0)
    :param watermark: 是否包含日期水印
    :param max_frames: 最大帧数
    :return: 临时文件绝对路径
    """
    export_format = export_format.lower()
    if export_format not in ("mp4", "gif"):
        raise ValueError("Invalid format, must be 'mp4' or 'gif'")

    quality = quality.lower()
    if quality not in ("hd", "sd"):
        raise ValueError("Invalid quality, must be 'hd' or 'sd'")

    fps = max(0.5, min(30.0, float(fps)))
    max_frames = max(2, min(500, int(max_frames)))

    _clean_expired_cache()

    # 1. 查询数据库中按日期正序的所有照片
    rows = db.query_photos_asc()
    if not rows:
        raise ValueError("No photos found")

    # 过滤出磁盘上真实存在的文件
    valid_photos = []
    for date_str, filename in rows:
        if quality == "hd":
            fpath = os.path.join(state.PHOTO_DIR, filename)
            if not os.path.exists(fpath):
                # 兼容旧路径或以 date_str.jpg 命名的文件
                fpath = os.path.join(state.PHOTO_DIR, f"{date_str}.jpg")
        else:
            # SD 优先用缩略图，不存在则降级用原图
            fpath = os.path.join(state.THUMB_DIR, filename)
            if not os.path.exists(fpath):
                fpath = os.path.join(state.PHOTO_DIR, filename)
        if os.path.exists(fpath):
            valid_photos.append((date_str, fpath))

    if not valid_photos:
        raise ValueError("No valid photo files on disk")

    selected = select_frames(valid_photos, max_frames=max_frames)

    # 2. 计算缓存哈希（基于参数 + 选中的照片列表与文件最后修改时间）
    hash_payload = f"{export_format}:{quality}:{fps}:{watermark}:{len(selected)}:"
    for d, p in selected:
        try:
            mtime = os.path.getmtime(p)
        except OSError:
            mtime = 0
        hash_payload += f"{d}:{mtime};"

    cache_hash = hashlib.md5(hash_payload.encode()).hexdigest()
    output_filename = f"timelapse_{cache_hash}.{export_format}"
    output_path = os.path.join(state.EXPORT_CACHE_DIR, output_filename)

    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        logger.info("命中延时导出缓存: %s", output_path)
        return output_path

    # 3. 检查 ffmpeg 是否可用
    has_ffmpeg = shutil.which("ffmpeg") is not None

    if export_format == "mp4" and not has_ffmpeg:
        raise RuntimeError("ffmpeg is not installed on the system. Please run 'sudo apt install -y ffmpeg' on Raspberry Pi.")

    target_max_dim = 1920 if quality == "hd" else 640
    tmp_output_path = os.path.join(state.EXPORT_CACHE_DIR, f"tmp_{os.getpid()}_{output_filename}")

    try:
        if export_format == "mp4":
            # MP4 走 ffmpeg 流式管道输入
            cmd = [
                "ffmpeg", "-y",
                "-f", "image2pipe",
                "-vcodec", "mjpeg",
                "-framerate", str(fps),
                "-i", "-",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "22",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                tmp_output_path
            ]
            logger.info("开始合成 MP4 (共 %d 帧, 帧率 %.1f, 质量 %s)...", len(selected), fps, quality)
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            target_size = None
            for date_str, photo_path in selected:
                frame_img = _process_frame(photo_path, date_str, target_max_dim, watermark, target_size=target_size)
                if frame_img is None:
                    continue
                if target_size is None:
                    target_size = frame_img.size
                buf = io.BytesIO()
                frame_img.save(buf, format="JPEG", quality=90)
                try:
                    proc.stdin.write(buf.getvalue())
                except (BrokenPipeError, OSError):
                    break

            try:
                proc.stdin.close()
            except Exception:
                pass
            # 必须将 proc.stdin 设为 None，否则 communicate() 内部会再次尝试 flush 已经 close 的 stdin 导致 ValueError: flush of closed file
            proc.stdin = None
            stdout, stderr = proc.communicate(timeout=120)

            if proc.returncode != 0:
                logger.error("ffmpeg 编码失败 (code %d): %s", proc.returncode, stderr.decode('utf-8', errors='ignore'))
                raise RuntimeError(f"ffmpeg encoding failed with exit code {proc.returncode}")

        elif export_format == "gif":
            if has_ffmpeg:
                # 使用 ffmpeg palette 生成更高质量且体积较小的 GIF
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "image2pipe",
                    "-vcodec", "mjpeg",
                    "-framerate", str(fps),
                    "-i", "-",
                    "-vf", "split[s0][s1];[s0]palettegen=max_colors=128:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3",
                    tmp_output_path
                ]
                logger.info("使用 ffmpeg 开始合成 GIF (共 %d 帧, 帧率 %.1f)...", len(selected), fps)
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

                target_size = None
                for date_str, photo_path in selected:
                    frame_img = _process_frame(photo_path, date_str, target_max_dim, watermark, target_size=target_size)
                    if frame_img is None:
                        continue
                    if target_size is None:
                        target_size = frame_img.size
                    buf = io.BytesIO()
                    frame_img.save(buf, format="JPEG", quality=85)
                    try:
                        proc.stdin.write(buf.getvalue())
                    except (BrokenPipeError, OSError):
                        break

                try:
                    proc.stdin.close()
                except Exception:
                    pass
                proc.stdin = None
                stdout, stderr = proc.communicate(timeout=120)

                if proc.returncode != 0:
                    logger.error("ffmpeg 生成 GIF 失败: %s", stderr.decode('utf-8', errors='ignore'))
                    raise RuntimeError("ffmpeg GIF generation failed")
            else:
                # Fallback: 使用 Pillow 生成 GIF（限制分辨率防 OOM）
                logger.info("使用 Pillow fallback 开始合成 GIF (共 %d 帧)...", len(selected))
                gif_max_dim = min(480, target_max_dim)
                frames = []
                for date_str, photo_path in selected:
                    frame_img = _process_frame(photo_path, date_str, gif_max_dim, watermark)
                    if frame_img:
                        frames.append(frame_img.convert("P", palette=Image.Palette.ADAPTIVE, colors=128))

                if not frames:
                    raise RuntimeError("No frames generated for GIF")

                duration_ms = int(1000.0 / fps)
                frames[0].save(
                    tmp_output_path,
                    format="GIF",
                    save_all=True,
                    append_images=frames[1:],
                    duration=duration_ms,
                    loop=0,
                    optimize=True,
                )

        if not os.path.exists(tmp_output_path) or os.path.getsize(tmp_output_path) == 0:
            raise RuntimeError("Export output file was not created or empty")

        os.replace(tmp_output_path, output_path)
        logger.info("✅ 延时导出完成: %s (大小 %d KB)", output_filename, os.path.getsize(output_path) // 1024)
        return output_path

    except Exception:
        if os.path.exists(tmp_output_path):
            try:
                os.remove(tmp_output_path)
            except OSError:
                pass
        raise
