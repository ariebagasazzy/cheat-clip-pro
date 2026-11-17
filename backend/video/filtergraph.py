import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.video_engine import FONTS_DIR, get_ffmpeg_safe_font_path

logger = logging.getLogger("cheat-clip-pro.filtergraph")


def _build_dynamic_crop_expr(keyframes: List[Dict[str, Any]], default_cx: float = 0.5) -> str:
    """
    Build FFmpeg expression for dynamic crop position based on keyframes.
    Uses linear interpolation between keyframes for smooth transitions.
    
    keyframes: [{"t": 0.0, "cx": 0.5}, {"t": 5.0, "cx": 0.3}, ...]
    Returns expression like: if(lt(t,5),0.5+(0.3-0.5)*(t-0)/5,if(lt(t,10),...))
    """
    if not keyframes or len(keyframes) == 0:
        return str(default_cx)
    
    if len(keyframes) == 1:
        return f"{keyframes[0]['cx']:.3f}"
    
    # Sort by time
    kfs = sorted(keyframes, key=lambda k: k["t"])
    
    # Build nested if expression with linear interpolation
    # For smooth transitions, interpolate between keyframes
    expr_parts = []
    
    for i in range(len(kfs) - 1):
        t_start = kfs[i]["t"]
        t_end = kfs[i + 1]["t"]
        cx_start = kfs[i]["cx"]
        cx_end = kfs[i + 1]["cx"]
        
        duration = t_end - t_start
        if duration <= 0:
            continue
        
        # Linear interpolation: cx_start + (cx_end - cx_start) * (t - t_start) / duration
        # But add smooth transition zone (0.5s ease)
        ease_duration = min(0.5, duration / 2)
        
        if abs(cx_end - cx_start) < 0.05:
            # No significant change, just use start value
            interp = f"{cx_start:.3f}"
        else:
            # Smooth step using smoothstep-like formula
            # progress = clamp((t - t_start) / duration, 0, 1)
            # smoothstep = progress * progress * (3 - 2 * progress)
            interp = f"({cx_start:.3f}+({cx_end:.3f}-{cx_start:.3f})*clip((t-{t_start:.2f})/{duration:.2f},0,1))"
        
        if i == 0:
            expr_parts.append(f"if(lt(t,{t_end:.2f}),{interp},")
        else:
            expr_parts.append(f"if(lt(t,{t_end:.2f}),{interp},")
    
    # Last segment continues with last value
    last_cx = kfs[-1]["cx"]
    expr_parts.append(f"{last_cx:.3f}")
    
    # Close all if statements
    expr_parts.append(")" * (len(kfs) - 1))
    
    return "".join(expr_parts)


def build_ffmpeg_filtergraph(
    aspect_ratio: str,
    background_style: str,
    face_center_ratio: float = 0.5,
    streamer_preset: str = "none",
    title_text: Optional[str] = None,
    title_position: str = "auto",
    ass_subtitles_path: Optional[str] = None,
    face_box: Optional[Dict[str, Any]] = None,
    title_y_percent: Optional[float] = None,
    crop_x_percent: Optional[float] = None,
    face_keyframes: Optional[List[Dict[str, Any]]] = None
) -> Tuple[str, str]:
    """
    Constructs the FFmpeg -filter_complex chain with proper aspect ratio center-cropping.
    Canvas is always 1080x1920 (9:16).
    
    If face_keyframes is provided, uses dynamic crop that changes over time.
    """
    filters = []
    aspect_ratio = (aspect_ratio or "9:16").strip().lower()
    # Guarantee video presentation timestamp strictly begins at 0.000 to eliminate initial subtitle offset / delay
    filters.append("[0:v]setpts=PTS-STARTPTS[v_pts]")

    face_cx = float(face_box.get("cx", face_center_ratio)) if face_box else face_center_ratio
    face_cy = float(face_box.get("cy", 0.78 if streamer_preset in ["split_top_cam", "pip_corner"] else 0.35)) if face_box else 0.35
    
    # Check if we have dynamic keyframes
    use_dynamic_crop = face_keyframes and len(face_keyframes) > 1

    # 1. Base Layout & Scaling
    if streamer_preset == "split_top_cam":
        if aspect_ratio == "16:9":
            # 16:9 split: top cam 1080x608 (16:9) tightly cropped around face, bottom feed 1080x608 (16:9)
            cam_h = "min(ih, max(240, ih*0.38))"
            cam_w = f"min(iw, ({cam_h})*16/9)"
            cam_x = f"max(0, min(iw-ow, iw*{face_cx:.3f}-ow/2))"
            cam_y = f"max(0, min(ih-oh, ih*{face_cy:.3f}-oh/2))"
            filters.append(
                f"[v_pts]split=2[cam_raw][game_raw];"
                f"[cam_raw]crop='{cam_w}':'{cam_h}':'{cam_x}':'{cam_y}',scale=1080:608[cam_box];"
                f"[game_raw]crop='min(iw,ih*16/9)':'min(ih,iw*9/16)':'(iw-min(iw,ih*16/9))/2':'(ih-min(ih,iw*9/16))/2',scale=1080:608[game_box];"
                f"[cam_box][game_box]vstack=inputs=2[both_split]"
            )
            if background_style == "blurred":
                filters.append(
                    f"[v_pts]scale=360:640:force_original_aspect_ratio=increase,crop=360:640,boxblur=12:2,scale=1080:1920,eq=saturation=1.2:contrast=1.05[bg_blurred];"
                    f"[bg_blurred][both_split]overlay=0:352[layout_base]"
                )
            else:
                filters.append(f"[both_split]pad=1080:1920:0:352:black[layout_base]")

        elif aspect_ratio == "1:1":
            # 1:1 split: top cam 960x960 (1:1) tightly cropped around face, bottom feed 960x960 (1:1)
            cam_h = "min(ih, max(280, ih*0.38))"
            cam_w = f"min(iw, {cam_h})"
            cam_x = f"max(0, min(iw-ow, iw*{face_cx:.3f}-ow/2))"
            cam_y = f"max(0, min(ih-oh, ih*{face_cy:.3f}-oh/2))"
            filters.append(
                f"[v_pts]split=2[cam_raw][game_raw];"
                f"[cam_raw]crop='{cam_w}':'{cam_h}':'{cam_x}':'{cam_y}',scale=960:960[cam_box];"
                f"[game_raw]crop='min(iw,ih)':'min(iw,ih)':'(iw-min(iw,ih))/2':'(ih-min(ih,iw))/2',scale=960:960[game_box];"
                f"[cam_box][game_box]vstack=inputs=2[both_split]"
            )
            if background_style == "blurred":
                filters.append(
                    f"[v_pts]scale=360:640:force_original_aspect_ratio=increase,crop=360:640,boxblur=12:2,scale=1080:1920,eq=saturation=1.2:contrast=1.05[bg_blurred];"
                    f"[bg_blurred][both_split]overlay=60:0[layout_base]"
                )
            else:
                filters.append(f"[both_split]pad=1080:1920:60:0:black[layout_base]")

        elif aspect_ratio == "4:3":
            # 4:3 split: top cam 1080x810 (4:3) tightly cropped around face, bottom feed 1080x810 (4:3)
            cam_h = "min(ih, max(280, ih*0.38))"
            cam_w = f"min(iw, ({cam_h})*4/3)"
            cam_x = f"max(0, min(iw-ow, iw*{face_cx:.3f}-ow/2))"
            cam_y = f"max(0, min(ih-oh, ih*{face_cy:.3f}-oh/2))"
            filters.append(
                f"[v_pts]split=2[cam_raw][game_raw];"
                f"[cam_raw]crop='{cam_w}':'{cam_h}':'{cam_x}':'{cam_y}',scale=1080:810[cam_box];"
                f"[game_raw]crop='min(iw,ih*4/3)':'min(ih,iw*3/4)':'(iw-min(iw,ih*4/3))/2':'(ih-min(ih,iw*3/4))/2',scale=1080:810[game_box];"
                f"[cam_box][game_box]vstack=inputs=2[both_split]"
            )
            if background_style == "blurred":
                filters.append(
                    f"[v_pts]scale=360:640:force_original_aspect_ratio=increase,crop=360:640,boxblur=12:2,scale=1080:1920,eq=saturation=1.2:contrast=1.05[bg_blurred];"
                    f"[bg_blurred][both_split]overlay=0:150[layout_base]"
                )
            else:
                filters.append(f"[both_split]pad=1080:1920:0:150:black[layout_base]")

        else:  # 9:16
            # 9:16 Split: full bleed 1080x1920 with crisp facecam on top and centered gameplay on bottom
            cam_h = "min(ih, max(280, ih*0.38))"
            cam_w = f"min(iw, ({cam_h})*4/3)"
            cam_x = f"max(0, min(iw-ow, iw*{face_cx:.3f}-ow/2))"
            cam_y = f"max(0, min(ih-oh, ih*{face_cy:.3f}-oh/2))"

            game_w = "min(iw, ih*1080/1110)"
            game_h = "ih"
            game_x = "(iw-ow)/2"
            game_y = "(ih-oh)/2"

            filters.append(
                f"[v_pts]split=2[cam_raw][game_raw];"
                f"[cam_raw]crop='{cam_w}':'{cam_h}':'{cam_x}':'{cam_y}',scale=1080:810[cam_box];"
                f"[game_raw]crop='{game_w}':'{game_h}':'{game_x}':'{game_y}',scale=1080:1110[game_box];"
                f"[cam_box][game_box]vstack=inputs=2[layout_base]"
            )

        current_v = "[layout_base]"

    elif streamer_preset == "pip_corner":
        # PIP Box tightly cropped on face (320x240)
        pip_cam_h = "min(ih, max(220, ih*0.35))"
        pip_cam_w = f"min(iw, ({pip_cam_h})*4/3)"
        pip_cam_x = f"max(0, min(iw-ow, iw*{face_cx:.3f}-ow/2))"
        pip_cam_y = f"max(0, min(ih-oh, ih*{face_cy:.3f}-oh/2))"
        pip_crop = f"[pip_raw]crop='{pip_cam_w}':'{pip_cam_h}':'{pip_cam_x}':'{pip_cam_y}',scale=320:240[pip_box];"

        if aspect_ratio == "1:1":
            crop_main = "crop='min(iw,ih)':'min(iw,ih)':'(iw-min(iw,ih))/2':'(ih-min(ih,iw))/2',scale=1080:1080"
            pip_x, pip_y = 736, 444
            if background_style == "blurred":
                filters.append(
                    f"[v_pts]split=3[bg_raw][main_raw][pip_raw];"
                    f"[bg_raw]scale=360:640:force_original_aspect_ratio=increase,crop=360:640,boxblur=12:2,scale=1080:1920,eq=saturation=1.2:contrast=1.05[bg_blurred];"
                    f"[main_raw]{crop_main}[fg_square];"
                    f"[bg_blurred][fg_square]overlay=0:420[main_base];"
                    f"{pip_crop}"
                    f"[main_base][pip_box]overlay=x={pip_x}:y={pip_y}[layout_base]"
                )
            else:
                filters.append(
                    f"[v_pts]split=2[main_raw][pip_raw];"
                    f"[main_raw]{crop_main},pad=1080:1920:0:420:black[main_base];"
                    f"{pip_crop}"
                    f"[main_base][pip_box]overlay=x={pip_x}:y={pip_y}[layout_base]"
                )

        elif aspect_ratio == "4:3":
            crop_main = "crop='min(iw,ih*4/3)':'min(ih,iw*3/4)':'(iw-min(iw,ih*4/3))/2':'(ih-min(ih,iw*3/4))/2',scale=1080:810"
            pip_x, pip_y = 736, 579
            if background_style == "blurred":
                filters.append(
                    f"[v_pts]split=3[bg_raw][main_raw][pip_raw];"
                    f"[bg_raw]scale=360:640:force_original_aspect_ratio=increase,crop=360:640,boxblur=12:2,scale=1080:1920,eq=saturation=1.2:contrast=1.05[bg_blurred];"
                    f"[main_raw]{crop_main}[fg_43];"
                    f"[bg_blurred][fg_43]overlay=0:555[main_base];"
                    f"{pip_crop}"
                    f"[main_base][pip_box]overlay=x={pip_x}:y={pip_y}[layout_base]"
                )
            else:
                filters.append(
                    f"[v_pts]split=2[main_raw][pip_raw];"
                    f"[main_raw]{crop_main},pad=1080:1920:0:555:black[main_base];"
                    f"{pip_crop}"
                    f"[main_base][pip_box]overlay=x={pip_x}:y={pip_y}[layout_base]"
                )

        elif aspect_ratio == "16:9_landscape":
            crop_main = "crop='min(iw,ih*16/9)':'min(ih,iw*9/16)':'(iw-min(iw,ih*16/9))/2':'(ih-min(ih,iw*9/16))/2',scale=1920:1080"
            pip_x, pip_y = 1550, 780
            filters.append(
                f"[v_pts]split=2[main_raw][pip_raw];"
                f"[main_raw]{crop_main}[main_base];"
                f"{pip_crop}"
                f"[main_base][pip_box]overlay=x={pip_x}:y={pip_y}[layout_base]"
            )

        elif aspect_ratio == "16:9":
            crop_main = "crop='min(iw,ih*16/9)':'min(ih,iw*9/16)':'(iw-min(iw,ih*16/9))/2':'(ih-min(ih,iw*9/16))/2',scale=1080:608"
            pip_x, pip_y = 736, 676
            if background_style == "blurred":
                filters.append(
                    f"[v_pts]split=3[bg_raw][main_raw][pip_raw];"
                    f"[bg_raw]scale=360:640:force_original_aspect_ratio=increase,crop=360:640,boxblur=12:2,scale=1080:1920,eq=saturation=1.2:contrast=1.05[bg_blurred];"
                    f"[main_raw]{crop_main}[fg_169];"
                    f"[bg_blurred][fg_169]overlay=0:656[main_base];"
                    f"{pip_crop}"
                    f"[main_base][pip_box]overlay=x={pip_x}:y={pip_y}[layout_base]"
                )
            else:
                filters.append(
                    f"[v_pts]split=2[main_raw][pip_raw];"
                    f"[main_raw]{crop_main},pad=1080:1920:0:656:black[main_base];"
                    f"{pip_crop}"
                    f"[main_base][pip_box]overlay=x={pip_x}:y={pip_y}[layout_base]"
                )

        else:  # 9:16
            pip_x, pip_y = 736, 120
            if crop_x_percent is not None:
                crop_ratio_safe = max(0.0, min(1.0, float(crop_x_percent) / 100.0))
                filters.append(
                    f"[v_pts]split=2[main_raw][pip_raw];"
                    f"[main_raw]crop=ih*9/16:ih:(iw-ih*9/16)*{crop_ratio_safe:.3f}:0,scale=1080:1920[main_base];"
                    f"{pip_crop}"
                    f"[main_base][pip_box]overlay=x={pip_x}:y={pip_y}[layout_base]"
                )
            else:
                # Smart face centering: center the crop window on face_cx
                safe_cx = float(face_cx)
                if 0.46 <= safe_cx <= 0.54:
                    safe_cx = 0.50
                safe_cx = max(0.15, min(0.85, safe_cx))
                filters.append(
                    f"[v_pts]split=2[main_raw][pip_raw];"
                    f"[main_raw]crop=ih*9/16:ih:'max(0,min(iw-ih*9/16,iw*{safe_cx:.3f}-ih*9/32))':0,scale=1080:1920[main_base];"
                    f"{pip_crop}"
                    f"[main_base][pip_box]overlay=x={pip_x}:y={pip_y}[layout_base]"
                )

        current_v = "[layout_base]"

    elif aspect_ratio == "9:16":
        # Check if this is a podcast layout (needs special handling for no face detected)
        is_podcast_split = face_box and face_box.get("type") == "podcast_split"
        
        if is_podcast_split:
            # NO FACE DETECTED / PODCAST MODE:
            # Instead of split screen, show full video with blurred background
            # Background: 9:16 crop from center, blurred
            # Foreground: Full video letterbox 16:9, scaled to fit width (1080), 
            #             with padding top/bottom (centered vertically)
            
            logger.info(f"9:16 NO FACE MODE: Full video with blurred background letterbox")
            
            # Calculate 16:9 video height when width is 1080: 1080 * 9/16 = 607.5 ~ 608
            # Vertical padding: (1920 - 608) / 2 = 656 top/bottom
            # But we want it centered, so overlay at y = (1920 - 608) / 2 = 656
            
            filters.append(
                f"[v_pts]split=2[bg_raw][fg_raw];"
                # Background: crop 9:16 from center, blur heavily
                f"[bg_raw]crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920,boxblur=25:5,eq=brightness=-0.05:saturation=0.8[bg_blurred];"
                # Foreground: scale full video to fit 1080 width (letterbox 16:9)
                f"[fg_raw]scale=1080:-2:force_original_aspect_ratio=decrease,pad=1080:608:(ow-iw)/2:(oh-ih)/2:black[fg_letterbox];"
                # Overlay letterbox on blurred background, centered vertically
                f"[bg_blurred][fg_letterbox]overlay=0:(1920-608)/2[layout_base]"
            )
        elif crop_x_percent is not None:
            # Manual override: treat as percentage of available horizontal space
            crop_ratio_safe = max(0.0, min(1.0, float(crop_x_percent) / 100.0))
            logger.info(f"9:16 crop with manual X%: {crop_x_percent}% -> ratio={crop_ratio_safe:.3f}")
            filters.append(
                f"[v_pts]crop=ih*9/16:ih:(iw-ih*9/16)*{crop_ratio_safe:.3f}:0,scale=1080:1920[layout_base]"
            )
        elif use_dynamic_crop and face_keyframes:
            # Check if any keyframe indicates podcast layout
            has_podcast_segments = any(kf.get("type", "").startswith("podcast") for kf in face_keyframes)
            
            if has_podcast_segments:
                # Mixed content: some podcast, some single speaker
                # For simplicity, use dynamic crop but detect podcast segments
                # and use split screen for those time ranges
                # TODO: For now, just use the dynamic expression
                pass
            
            # Progressive/Dynamic face tracking with time-based crop position
            cx_expr = _build_dynamic_crop_expr(face_keyframes, face_cx)
            crop_x_expr = f"max(0,min(iw-ih*9/16,iw*({cx_expr})-ih*9/32))"
            logger.info(f"9:16 DYNAMIC face crop with {len(face_keyframes)} keyframes")
            for kf in face_keyframes:
                logger.info(f"  Keyframe t={kf['t']:.1f}s: cx={kf['cx']:.3f}")
            filters.append(
                f"[v_pts]crop=w=ih*9/16:h=ih:x='{crop_x_expr}':y=0,scale=1080:1920[layout_base]"
            )
        else:
            # Smart face centering: center the crop window on face_cx
            safe_cx = float(face_cx)
            original_cx = safe_cx
            if 0.46 <= safe_cx <= 0.54:
                safe_cx = 0.50
            safe_cx = max(0.15, min(0.85, safe_cx))
            logger.info(f"9:16 smart face crop: face_cx={original_cx:.3f} -> safe_cx={safe_cx:.3f}")
            filters.append(
                f"[v_pts]crop=ih*9/16:ih:'max(0,min(iw-ih*9/16,iw*{safe_cx:.3f}-ih*9/32))':0,scale=1080:1920[layout_base]"
            )
        current_v = "[layout_base]"

    elif aspect_ratio == "1:1":
        # 1:1 Square (1080x1080) - Smart crop with speaker/object centering then scale to 1080x1080
        safe_cx = float(face_cx)
        if 0.46 <= safe_cx <= 0.54:
            safe_cx = 0.50
        safe_cx = max(0.15, min(0.85, safe_cx))
        crop_11 = f"crop='min(iw,ih)':'min(iw,ih)':'max(0,min(iw-ih,iw*{safe_cx:.3f}-ih/2))':'(ih-min(iw,ih))/2',scale=1080:1080"
        if background_style == "blurred":
            filters.append(
                f"[v_pts]split=2[bg_raw][fg_raw];"
                f"[bg_raw]scale=360:640:force_original_aspect_ratio=increase,crop=360:640,boxblur=12:2,scale=1080:1920,eq=saturation=1.2:contrast=1.05[bg_blurred];"
                f"[fg_raw]{crop_11}[fg_square];"
                f"[bg_blurred][fg_square]overlay=0:420[layout_base]"
            )
        else:
            filters.append(
                f"[v_pts]{crop_11},pad=1080:1920:0:420:black[layout_base]"
            )
        current_v = "[layout_base]"

    elif aspect_ratio == "4:3":
        # 4:3 Standard (1080x810) - Smart crop with speaker/object centering then scale to 1080x810
        safe_cx = float(face_cx)
        if 0.46 <= safe_cx <= 0.54:
            safe_cx = 0.50
        safe_cx = max(0.15, min(0.85, safe_cx))
        crop_43 = f"crop='min(iw,ih*4/3)':'min(ih,iw*3/4)':'max(0,min(iw-ih*4/3,iw*{safe_cx:.3f}-(ih*4/3)/2))':'(ih-min(ih,iw*3/4))/2',scale=1080:810"
        if background_style == "blurred":
            filters.append(
                f"[v_pts]split=2[bg_raw][fg_raw];"
                f"[bg_raw]scale=360:640:force_original_aspect_ratio=increase,crop=360:640,boxblur=12:2,scale=1080:1920,eq=saturation=1.2:contrast=1.05[bg_blurred];"
                f"[fg_raw]{crop_43}[fg_43];"
                f"[bg_blurred][fg_43]overlay=0:555[layout_base]"
            )
        else:
            filters.append(
                f"[v_pts]{crop_43},pad=1080:1920:0:555:black[layout_base]"
            )
        current_v = "[layout_base]"

    elif aspect_ratio == "16:9_landscape":
        # True 16:9 Landscape (1920x1080)
        safe_cx = float(face_cx)
        if 0.46 <= safe_cx <= 0.54:
            safe_cx = 0.50
        safe_cx = max(0.15, min(0.85, safe_cx))
        crop_169_land = f"crop='min(iw,ih*16/9)':'min(ih,iw*9/16)':'max(0,min(iw-ih*16/9,iw*{safe_cx:.3f}-(ih*16/9)/2))':'(ih-min(ih,iw*9/16))/2',scale=1920:1080"
        filters.append(
            f"[v_pts]{crop_169_land}[layout_base]"
        )
        current_v = "[layout_base]"

    else:  # 16:9 Letterbox
        # 16:9 Letterbox (1080x608) - Smart crop with speaker/object centering for ultrawide sources
        safe_cx = float(face_cx)
        if 0.46 <= safe_cx <= 0.54:
            safe_cx = 0.50
        safe_cx = max(0.15, min(0.85, safe_cx))
        crop_169 = f"crop='min(iw,ih*16/9)':'min(ih,iw*9/16)':'max(0,min(iw-ih*16/9,iw*{safe_cx:.3f}-(ih*16/9)/2))':'(ih-min(ih,iw*9/16))/2',scale=1080:608"
        if background_style == "blurred":
            filters.append(
                f"[v_pts]split=2[bg_raw][fg_raw];"
                f"[bg_raw]scale=360:640:force_original_aspect_ratio=increase,crop=360:640,boxblur=12:2,scale=1080:1920,eq=saturation=1.2:contrast=1.05[bg_blurred];"
                f"[fg_raw]{crop_169}[fg_169];"
                f"[bg_blurred][fg_169]overlay=0:656[layout_base]"
            )
        else:
            filters.append(
                f"[v_pts]{crop_169},pad=1080:1920:0:656:black[layout_base]"
            )
        current_v = "[layout_base]"

    # 2. Subtitles & Title Burning via libass (.ass)
    # (If ass_subtitles_path is provided, it contains BOTH the title and subtitles rendered with exact matching fonts)
    if ass_subtitles_path and os.path.exists(ass_subtitles_path):
        has_dialogue = False
        try:
            with open(ass_subtitles_path, "r", encoding="utf-8", errors="ignore") as f_ass:
                has_dialogue = any(line.strip().startswith("Dialogue:") for line in f_ass)
        except Exception:
            has_dialogue = True

        if has_dialogue:
            raw_ass = str(Path(ass_subtitles_path).resolve()).replace("\\", "/")
            escaped_ass = raw_ass.replace(":", "\\:").replace("'", "'\\''")
            if FONTS_DIR.exists() and (any(FONTS_DIR.glob("*.ttf")) or any(FONTS_DIR.glob("*.otf")) or any(FONTS_DIR.glob("*.woff*"))):
                raw_fonts = str(FONTS_DIR.resolve()).replace("\\", "/")
                escaped_fonts = raw_fonts.replace("'", "'\\''").replace(":", "\\:")
                sub_filter = f"{current_v}subtitles=filename='{escaped_ass}':fontsdir='{escaped_fonts}'[v_final]"
            else:
                sub_filter = f"{current_v}subtitles=filename='{escaped_ass}'[v_final]"
            filters.append(sub_filter)
            current_v = "[v_final]"
    elif title_text and title_position != "none":
        # Fallback drawtext if no ASS was generated
        clean_title = title_text.replace("'", "").replace(":", "-").replace('"', "").strip()
        if title_y_percent is not None:
            canvas_h = 1080 if aspect_ratio == "16:9_landscape" else 1920
            y_pos = int(round(canvas_h * (float(title_y_percent) / 100.0)))
        elif streamer_preset == "split_top_cam":
            y_pos = int(round(1920 * 0.045))
        else:
            y_pos = 80 if aspect_ratio == "16:9_landscape" else (345 if aspect_ratio == "1:1" else (480 if aspect_ratio in ["4:3", "9:16"] else 581))
        box_style = "box=0"
        safe_font = get_ffmpeg_safe_font_path()
        font_arg = f":fontfile='{safe_font}'" if safe_font else ""
        title_filter = (
            f"{current_v}drawtext=text='{clean_title}'{font_arg}:fontsize=60:fontcolor=white:"
            f"x=(w-text_w)/2:y={y_pos}:borderw=2.5:bordercolor=black@0.8:{box_style}[v_with_title]"
        )
        filters.append(title_filter)
        current_v = "[v_with_title]"

    full_filter_str = ";".join(filters)
    return full_filter_str, current_v
