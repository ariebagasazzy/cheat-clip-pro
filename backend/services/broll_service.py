"""
B-Roll Auto-Insert Service

Automatically inserts relevant stock footage (B-Roll) into videos
based on keyword analysis from transcript.

Features:
- Keyword extraction from transcript using AI
- Pixabay API integration for free stock videos (no approval needed)
- Smart timing detection for natural B-Roll insertion points
- Video download and caching
"""

import os
import re
import json
import time
import hashlib
import logging
import asyncio
import aiohttp
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
BROLL_CACHE_DIR = BASE_DIR / "broll_cache"
BROLL_CACHE_DIR.mkdir(exist_ok=True)

# Pixabay API (Free, get key at https://pixabay.com/api/docs/)
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")

@dataclass
class BRollSegment:
    """Represents a B-Roll segment to insert"""
    keyword: str
    start_time: float  # When to insert (in clip timeline)
    duration: float    # How long the B-Roll shows
    video_url: str     # URL or local path to B-Roll video
    video_path: str    # Local cached path
    insert_mode: str   # 'replace', 'pip', 'split'


def extract_visual_keywords(
    transcript: List[Dict[str, Any]],
    clip_start: float,
    clip_end: float,
    max_keywords: int = 5
) -> List[Dict[str, Any]]:
    """
    Extract visual keywords from transcript that would benefit from B-Roll.
    Returns keywords with their timestamps.
    
    Keywords are nouns, actions, and concepts that can be visualized.
    """
    # Common visual keyword patterns (expandable)
    visual_patterns = {
        # Work & Business
        r'\b(kerja|bekerja|kantor|office|meeting|rapat|deadline|project|bisnis|business)\b': 'work office business',
        r'\b(stress|stres|burnout|kelelahan|capek|lelah|exhausted|tired)\b': 'stress tired exhausted',
        r'\b(sukses|success|berhasil|achieve|achievement|goal|target)\b': 'success achievement celebration',
        r'\b(uang|money|gaji|salary|income|pendapatan|investasi|investment)\b': 'money finance investment',
        
        # Education & Learning
        r'\b(belajar|study|sekolah|school|kuliah|university|pendidikan|education)\b': 'education study learning',
        r'\b(buku|book|membaca|reading|literasi|library)\b': 'books reading library',
        r'\b(guru|teacher|mengajar|teaching|mentor)\b': 'teacher teaching classroom',
        
        # Technology
        r'\b(komputer|computer|laptop|teknologi|technology|digital|internet)\b': 'technology computer digital',
        r'\b(smartphone|handphone|hp|gadget|device)\b': 'smartphone mobile device',
        r'\b(AI|artificial intelligence|robot|automation|otomasi)\b': 'artificial intelligence robot',
        
        # Health & Wellness
        r'\b(sehat|healthy|kesehatan|health|olahraga|exercise|gym|fitness)\b': 'health fitness exercise',
        r'\b(makan|food|makanan|diet|nutrisi|nutrition)\b': 'healthy food nutrition',
        r'\b(tidur|sleep|istirahat|rest|relax|relaxasi)\b': 'sleep rest relaxation',
        r'\b(mental|psikolog|psychology|therapy|terapi|mindfulness)\b': 'mental health therapy meditation',
        
        # Nature & Environment
        r'\b(alam|nature|lingkungan|environment|pohon|tree|hutan|forest)\b': 'nature forest trees',
        r'\b(laut|ocean|pantai|beach|air|water)\b': 'ocean beach water',
        r'\b(gunung|mountain|hiking|adventure|petualangan)\b': 'mountain hiking adventure',
        
        # Emotions & Concepts
        r'\b(bahagia|happy|happiness|senang|joy|kegembiraan)\b': 'happy joy celebration',
        r'\b(sedih|sad|depresi|depression|menangis|crying)\b': 'sad emotional',
        r'\b(marah|angry|anger|frustasi|frustrated)\b': 'angry frustrated',
        r'\b(takut|fear|cemas|anxiety|worried|khawatir)\b': 'anxiety worried fear',
        r'\b(cinta|love|kasih|sayang|relationship|hubungan)\b': 'love relationship couple',
        
        # Time & Progress
        r'\b(waktu|time|jam|clock|deadline|schedule|jadwal)\b': 'time clock schedule',
        r'\b(masa depan|future|planning|rencana|goal)\b': 'future planning goals',
        r'\b(perubahan|change|transformasi|transformation|growth)\b': 'change transformation growth',
        
        # Social & People
        r'\b(keluarga|family|orang tua|parents|anak|children|kids)\b': 'family parents children',
        r'\b(teman|friend|sahabat|friendship|komunitas|community)\b': 'friends community social',
        r'\b(tim|team|teamwork|kolaborasi|collaboration)\b': 'teamwork collaboration team',
    }
    
    keywords_found = []
    
    # Filter transcript to clip range
    clip_lines = [
        line for line in transcript
        if clip_start - 1 <= float(line.get('start', 0)) <= clip_end + 1
    ]
    
    # Combine text
    full_text = ' '.join([line.get('text', '') for line in clip_lines]).lower()
    
    # Find matching keywords with their approximate timestamps
    for pattern, search_query in visual_patterns.items():
        matches = list(re.finditer(pattern, full_text, re.IGNORECASE))
        if matches:
            # Find the timestamp for this keyword
            for match in matches[:2]:  # Max 2 per pattern
                keyword_text = match.group(0)
                
                # Find which transcript line contains this keyword
                for line in clip_lines:
                    if keyword_text.lower() in line.get('text', '').lower():
                        line_start = float(line.get('start', clip_start))
                        # Convert to relative time within clip
                        relative_time = max(0, line_start - clip_start)
                        
                        keywords_found.append({
                            'keyword': keyword_text,
                            'search_query': search_query,
                            'timestamp': relative_time,
                            'line_text': line.get('text', '')
                        })
                        break
    
    # Remove duplicates and sort by timestamp
    seen_queries = set()
    unique_keywords = []
    for kw in sorted(keywords_found, key=lambda x: x['timestamp']):
        if kw['search_query'] not in seen_queries:
            seen_queries.add(kw['search_query'])
            unique_keywords.append(kw)
            if len(unique_keywords) >= max_keywords:
                break
    
    logger.info(f"Extracted {len(unique_keywords)} visual keywords from transcript")
    return unique_keywords


async def search_pixabay_videos(
    query: str,
    per_page: int = 3,
    orientation: str = "vertical"  # vertical for 9:16 videos
) -> List[Dict[str, Any]]:
    """
    Search Pixabay API for stock videos matching the query.
    Returns list of video results with download URLs.
    
    Pixabay is free and doesn't require approval for API key.
    Get key at: https://pixabay.com/api/docs/
    """
    if not PIXABAY_API_KEY:
        logger.warning("PIXABAY_API_KEY not set, B-Roll search disabled")
        return []
    
    url = "https://pixabay.com/api/videos/"
    params = {
        "key": PIXABAY_API_KEY,
        "q": query,
        "per_page": per_page,
        "safesearch": "true",
        "video_type": "film",  # film quality videos
    }
    
    # Add orientation filter if vertical preferred
    # Note: Pixabay doesn't have explicit orientation filter, but we can filter by dimensions
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    videos = data.get('hits', [])
                    
                    results = []
                    for video in videos:
                        # Get video files - Pixabay provides multiple sizes
                        video_files = video.get('videos', {})
                        
                        # Prefer medium or small for faster download
                        # Available sizes: large, medium, small, tiny
                        best_file = None
                        for size in ['medium', 'small', 'large']:
                            if size in video_files:
                                best_file = video_files[size]
                                break
                        
                        if best_file and best_file.get('url'):
                            # Filter for vertical-ish videos if orientation is vertical
                            width = best_file.get('width', 1920)
                            height = best_file.get('height', 1080)
                            
                            # For vertical mode, prefer videos that aren't too wide
                            # (we'll crop them anyway, but closer to vertical is better)
                            if orientation == "vertical" and width > height * 2:
                                continue  # Skip very wide videos
                            
                            results.append({
                                'id': video.get('id'),
                                'url': video.get('pageURL'),
                                'download_url': best_file.get('url'),
                                'width': width,
                                'height': height,
                                'duration': video.get('duration'),
                                'tags': video.get('tags', ''),
                                'user': video.get('user', '')
                            })
                    
                    logger.info(f"Pixabay search '{query}': found {len(results)} videos")
                    return results
                else:
                    error_text = await resp.text()
                    logger.warning(f"Pixabay API error: {resp.status} - {error_text}")
                    return []
    except Exception as e:
        logger.error(f"Pixabay search error: {e}")
        return []


async def download_broll_video(
    video_url: str,
    keyword: str,
    max_duration: float = 5.0
) -> Optional[str]:
    """
    Download B-Roll video from URL and cache locally.
    Trims to max_duration if needed.
    Returns local file path.
    """
    # Generate cache filename based on URL hash
    url_hash = hashlib.md5(video_url.encode()).hexdigest()[:12]
    safe_keyword = re.sub(r'[^a-zA-Z0-9]', '_', keyword)[:20]
    cache_filename = f"broll_{safe_keyword}_{url_hash}.mp4"
    cache_path = BROLL_CACHE_DIR / cache_filename
    
    # Return cached file if exists
    if cache_path.exists() and cache_path.stat().st_size > 10000:
        logger.info(f"Using cached B-Roll: {cache_filename}")
        return str(cache_path)
    
    try:
        # Download video
        temp_path = BROLL_CACHE_DIR / f"temp_{url_hash}.mp4"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(video_url, timeout=60) as resp:
                if resp.status == 200:
                    with open(temp_path, 'wb') as f:
                        async for chunk in resp.content.iter_chunked(8192):
                            f.write(chunk)
                else:
                    logger.error(f"Failed to download B-Roll: HTTP {resp.status}")
                    return None
        
        # Trim to max duration using FFmpeg
        import subprocess
        trim_cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(temp_path),
            "-t", str(max_duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(cache_path)
        ]
        
        result = subprocess.run(trim_cmd, capture_output=True, timeout=60)
        
        # Clean up temp file
        if temp_path.exists():
            temp_path.unlink()
        
        if result.returncode == 0 and cache_path.exists():
            logger.info(f"Downloaded and cached B-Roll: {cache_filename}")
            return str(cache_path)
        else:
            logger.error(f"FFmpeg trim failed: {result.stderr.decode()}")
            return None
            
    except Exception as e:
        logger.error(f"B-Roll download error: {e}")
        return None


async def prepare_broll_segments(
    transcript: List[Dict[str, Any]],
    clip_start: float,
    clip_end: float,
    clip_duration: float,
    insert_mode: str = "replace",
    broll_duration: float = 3.0,
    max_segments: int = 3,
    min_gap: float = 8.0  # Minimum seconds between B-Roll inserts
) -> List[BRollSegment]:
    """
    Prepare B-Roll segments for a clip.
    
    Args:
        transcript: Full video transcript
        clip_start: Clip start time in original video
        clip_end: Clip end time in original video
        clip_duration: Duration of the clip
        insert_mode: 'replace', 'pip', or 'split'
        broll_duration: How long each B-Roll shows
        max_segments: Maximum number of B-Roll inserts
        min_gap: Minimum gap between B-Roll inserts
    
    Returns:
        List of BRollSegment objects ready for rendering
    """
    segments = []
    
    # Extract keywords from transcript
    keywords = extract_visual_keywords(transcript, clip_start, clip_end, max_keywords=max_segments + 2)
    
    if not keywords:
        logger.info("No visual keywords found for B-Roll")
        return []
    
    last_insert_time = -min_gap
    
    for kw in keywords:
        if len(segments) >= max_segments:
            break
        
        # Ensure minimum gap between B-Roll inserts
        insert_time = kw['timestamp']
        if insert_time - last_insert_time < min_gap:
            continue
        
        # Don't insert too close to start or end
        if insert_time < 2.0 or insert_time > clip_duration - broll_duration - 1.0:
            continue
        
        # Search for B-Roll video
        search_results = await search_pixabay_videos(kw['search_query'], per_page=2)
        
        if not search_results:
            continue
        
        # Download first result
        video_result = search_results[0]
        local_path = await download_broll_video(
            video_result['download_url'],
            kw['keyword'],
            max_duration=broll_duration + 1.0
        )
        
        if local_path:
            segment = BRollSegment(
                keyword=kw['keyword'],
                start_time=insert_time,
                duration=broll_duration,
                video_url=video_result['download_url'],
                video_path=local_path,
                insert_mode=insert_mode
            )
            segments.append(segment)
            last_insert_time = insert_time
            logger.info(f"Prepared B-Roll for '{kw['keyword']}' at {insert_time:.1f}s")
    
    return segments


def build_broll_ffmpeg_filter(
    segments: List[BRollSegment],
    main_video_duration: float,
    canvas_width: int = 1080,
    canvas_height: int = 1920
) -> Tuple[List[str], str]:
    """
    Build FFmpeg filter complex for B-Roll insertion.
    
    Returns:
        Tuple of (input_args, filter_complex_string)
    """
    if not segments:
        return [], ""
    
    input_args = []
    filter_parts = []
    
    # Add B-Roll inputs
    for i, seg in enumerate(segments):
        input_args.extend(["-i", seg.video_path])
    
    # Build filter complex
    # Main video is input 0, B-Roll videos are inputs 1, 2, 3...
    
    n_broll = len(segments)
    
    # Scale all B-Roll to canvas size
    for i, seg in enumerate(segments):
        broll_idx = i + 1  # B-Roll input index (main video is 0)
        filter_parts.append(
            f"[{broll_idx}:v]scale={canvas_width}:{canvas_height}:force_original_aspect_ratio=increase,"
            f"crop={canvas_width}:{canvas_height},setpts=PTS-STARTPTS[broll{i}]"
        )
    
    # Create timeline with overlays
    # For 'replace' mode: switch between main and B-Roll
    if segments[0].insert_mode == "replace":
        # Build overlay chain
        current_stream = "0:v"
        
        for i, seg in enumerate(segments):
            # Enable B-Roll during its time window
            start_t = seg.start_time
            end_t = seg.start_time + seg.duration
            
            filter_parts.append(
                f"[{current_stream}][broll{i}]overlay=0:0:"
                f"enable='between(t,{start_t},{end_t})'[v{i}]"
            )
            current_stream = f"v{i}"
        
        final_video = current_stream
    
    elif segments[0].insert_mode == "pip":
        # Picture-in-Picture: B-Roll in corner
        pip_x = int(canvas_width * 0.55)
        pip_y = int(canvas_height * 0.05)
        pip_w = int(canvas_width * 0.42)
        pip_h = int(canvas_height * 0.25)
        
        current_stream = "0:v"
        
        for i, seg in enumerate(segments):
            start_t = seg.start_time
            end_t = seg.start_time + seg.duration
            
            # Scale B-Roll to PiP size
            filter_parts.append(
                f"[broll{i}]scale={pip_w}:{pip_h}[broll_pip{i}]"
            )
            
            filter_parts.append(
                f"[{current_stream}][broll_pip{i}]overlay={pip_x}:{pip_y}:"
                f"enable='between(t,{start_t},{end_t})'[v{i}]"
            )
            current_stream = f"v{i}"
        
        final_video = current_stream
    
    else:  # split mode
        # 50/50 split screen
        split_h = canvas_height // 2
        current_stream = "0:v"
        
        for i, seg in enumerate(segments):
            start_t = seg.start_time
            end_t = seg.start_time + seg.duration
            
            # Scale B-Roll to top half
            filter_parts.append(
                f"[broll{i}]scale={canvas_width}:{split_h}[broll_top{i}]"
            )
            
            # Scale main to bottom half during B-Roll
            filter_parts.append(
                f"[{current_stream}]split[main_copy{i}][main_for_split{i}];"
                f"[main_for_split{i}]scale={canvas_width}:{split_h}[main_bottom{i}];"
                f"[broll_top{i}][main_bottom{i}]vstack[split{i}];"
                f"[main_copy{i}][split{i}]overlay=0:0:"
                f"enable='between(t,{start_t},{end_t})'[v{i}]"
            )
            current_stream = f"v{i}"
        
        final_video = current_stream
    
    filter_complex = ";".join(filter_parts)
    
    return input_args, filter_complex, final_video


def get_broll_cache_stats() -> Dict[str, Any]:
    """Get statistics about cached B-Roll videos."""
    if not BROLL_CACHE_DIR.exists():
        return {"count": 0, "total_size_mb": 0}
    
    files = list(BROLL_CACHE_DIR.glob("broll_*.mp4"))
    total_size = sum(f.stat().st_size for f in files)
    
    return {
        "count": len(files),
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "cache_path": str(BROLL_CACHE_DIR)
    }


def clear_broll_cache(max_age_hours: int = 72) -> int:
    """Clear old cached B-Roll videos. Returns number of files deleted."""
    if not BROLL_CACHE_DIR.exists():
        return 0
    
    deleted = 0
    cutoff_time = time.time() - (max_age_hours * 3600)
    
    for f in BROLL_CACHE_DIR.glob("broll_*.mp4"):
        try:
            if f.stat().st_mtime < cutoff_time:
                f.unlink()
                deleted += 1
        except Exception:
            pass
    
    logger.info(f"Cleared {deleted} old B-Roll cache files")
    return deleted
