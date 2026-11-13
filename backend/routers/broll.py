"""
B-Roll API Router

Endpoints for B-Roll auto-insert functionality.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import logging

from backend.services.broll_service import (
    extract_visual_keywords,
    search_pixabay_videos,
    prepare_broll_segments,
    get_broll_cache_stats,
    clear_broll_cache,
    PIXABAY_API_KEY
)

logger = logging.getLogger(__name__)
router = APIRouter()


class KeywordExtractionRequest(BaseModel):
    transcript: List[Dict[str, Any]]
    clip_start: float
    clip_end: float
    max_keywords: int = 5


class BRollSearchRequest(BaseModel):
    query: str
    per_page: int = 3
    orientation: str = "vertical"


class BRollPrepareRequest(BaseModel):
    transcript: List[Dict[str, Any]]
    clip_start: float
    clip_end: float
    clip_duration: float
    insert_mode: str = "replace"  # 'replace', 'pip', 'split'
    broll_duration: float = 3.0
    max_segments: int = 3


@router.get("/api/broll/status")
async def get_broll_status():
    """Check B-Roll service status and configuration."""
    return {
        "enabled": bool(PIXABAY_API_KEY),
        "api_configured": bool(PIXABAY_API_KEY),
        "cache_stats": get_broll_cache_stats(),
        "supported_modes": ["replace", "pip", "split"],
        "message": "B-Roll service ready" if PIXABAY_API_KEY else "Set PIXABAY_API_KEY to enable B-Roll"
    }


@router.post("/api/broll/extract-keywords")
async def extract_keywords(request: KeywordExtractionRequest):
    """Extract visual keywords from transcript for B-Roll search."""
    try:
        keywords = extract_visual_keywords(
            request.transcript,
            request.clip_start,
            request.clip_end,
            request.max_keywords
        )
        return {
            "success": True,
            "keywords": keywords,
            "count": len(keywords)
        }
    except Exception as e:
        logger.error(f"Keyword extraction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/broll/search")
async def search_broll(request: BRollSearchRequest):
    """Search Pixabay for stock videos matching query."""
    if not PIXABAY_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Pixabay API key not configured. Set PIXABAY_API_KEY environment variable."
        )
    
    try:
        results = await search_pixabay_videos(
            request.query,
            request.per_page,
            request.orientation
        )
        return {
            "success": True,
            "videos": results,
            "count": len(results),
            "query": request.query
        }
    except Exception as e:
        logger.error(f"B-Roll search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/broll/prepare")
async def prepare_broll(request: BRollPrepareRequest):
    """
    Prepare B-Roll segments for a clip.
    Downloads and caches videos, returns segment info for rendering.
    """
    if not PIXABAY_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Pixabay API key not configured"
        )
    
    try:
        segments = await prepare_broll_segments(
            request.transcript,
            request.clip_start,
            request.clip_end,
            request.clip_duration,
            request.insert_mode,
            request.broll_duration,
            request.max_segments
        )
        
        return {
            "success": True,
            "segments": [
                {
                    "keyword": seg.keyword,
                    "start_time": seg.start_time,
                    "duration": seg.duration,
                    "video_path": seg.video_path,
                    "insert_mode": seg.insert_mode
                }
                for seg in segments
            ],
            "count": len(segments)
        }
    except Exception as e:
        logger.error(f"B-Roll prepare error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/broll/cache")
async def get_cache_info():
    """Get B-Roll cache statistics."""
    return get_broll_cache_stats()


@router.delete("/api/broll/cache")
async def clear_cache(max_age_hours: int = 72):
    """Clear old cached B-Roll videos."""
    deleted = clear_broll_cache(max_age_hours)
    return {
        "success": True,
        "deleted_count": deleted,
        "message": f"Deleted {deleted} cached B-Roll files older than {max_age_hours} hours"
    }
