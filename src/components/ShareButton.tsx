/**
 * ShareButton Component
 * 
 * Provides easy sharing functionality using Web Share API and quick links to social platforms.
 * No API keys required - uses native device sharing capabilities.
 */

import React, { useState, useRef, useEffect } from 'react';
import { Share2, X, ExternalLink, Copy, Check, Smartphone } from 'lucide-react';

interface ShareButtonProps {
  videoUrl: string;           // URL or blob URL of the video to share
  videoTitle?: string;        // Title for the shared content
  fileName?: string;          // Filename for download reference
  variant?: 'icon' | 'button'; // Display style
  size?: 'sm' | 'md' | 'lg';  // Size variant
  className?: string;
}

interface SocialPlatform {
  id: string;
  name: string;
  icon: string;
  color: string;
  uploadUrl: string;
  description: string;
}

const SOCIAL_PLATFORMS: SocialPlatform[] = [
  {
    id: 'tiktok',
    name: 'TikTok',
    icon: '🎵',
    color: '#000000',
    uploadUrl: 'https://www.tiktok.com/upload',
    description: 'Upload to TikTok'
  },
  {
    id: 'youtube',
    name: 'YouTube',
    icon: '▶️',
    color: '#FF0000',
    uploadUrl: 'https://studio.youtube.com/channel/UC/videos/upload',
    description: 'Upload to YouTube Studio'
  },
  {
    id: 'instagram',
    name: 'Instagram',
    icon: '📸',
    color: '#E4405F',
    uploadUrl: 'https://www.instagram.com/',
    description: 'Open Instagram (upload via mobile app)'
  },
  {
    id: 'facebook',
    name: 'Facebook',
    icon: '📘',
    color: '#1877F2',
    uploadUrl: 'https://www.facebook.com/reels/create',
    description: 'Create Facebook Reel'
  },
  {
    id: 'twitter',
    name: 'X / Twitter',
    icon: '𝕏',
    color: '#000000',
    uploadUrl: 'https://twitter.com/compose/tweet',
    description: 'Post to X'
  }
];

export const ShareButton: React.FC<ShareButtonProps> = ({
  videoUrl,
  videoTitle = 'Cheat Clip Pro Video',
  fileName = 'video.mp4',
  variant = 'button',
  size = 'md',
  className = ''
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [shareSupported, setShareSupported] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Check if Web Share API is supported
    setShareSupported('share' in navigator && 'canShare' in navigator);
  }, []);

  useEffect(() => {
    // Close menu when clicking outside
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen]);

  // Native Web Share API (works best on mobile)
  const handleNativeShare = async () => {
    try {
      // Try to fetch video as blob for file sharing
      const response = await fetch(videoUrl);
      const blob = await response.blob();
      const file = new File([blob], fileName, { type: 'video/mp4' });

      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        await navigator.share({
          title: videoTitle,
          text: `Check out this clip: ${videoTitle}`,
          files: [file]
        });
      } else {
        // Fallback: share URL only
        await navigator.share({
          title: videoTitle,
          text: `Check out this clip: ${videoTitle}`,
          url: videoUrl
        });
      }
      setIsOpen(false);
    } catch (err) {
      // User cancelled or error
      console.log('Share cancelled or failed:', err);
    }
  };

  // Open social platform upload page
  const handlePlatformClick = (platform: SocialPlatform) => {
    window.open(platform.uploadUrl, '_blank', 'noopener,noreferrer');
    setIsOpen(false);
  };

  // Copy video URL to clipboard
  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(videoUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  const sizeStyles = {
    sm: { padding: '0.25rem 0.5rem', fontSize: '0.7rem', iconSize: 14 },
    md: { padding: '0.35rem 0.7rem', fontSize: '0.75rem', iconSize: 16 },
    lg: { padding: '0.5rem 1rem', fontSize: '0.85rem', iconSize: 18 }
  };

  const currentSize = sizeStyles[size];

  return (
    <div style={{ position: 'relative', display: 'inline-block' }} ref={menuRef}>
      {/* Share Button */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className={`share-btn ${className}`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '0.35rem',
          padding: currentSize.padding,
          fontSize: currentSize.fontSize,
          fontWeight: 600,
          background: 'linear-gradient(135deg, #8b5cf6 0%, #6d28d9 100%)',
          border: '1px solid rgba(139, 92, 246, 0.5)',
          borderRadius: '6px',
          color: '#fff',
          cursor: 'pointer',
          boxShadow: '0 0 12px rgba(139, 92, 246, 0.3)',
          transition: 'all 0.2s ease'
        }}
        title="Share to social media"
      >
        <Share2 size={currentSize.iconSize} />
        {variant === 'button' && <span>Share</span>}
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            right: 0,
            marginTop: '0.5rem',
            width: '280px',
            background: 'linear-gradient(180deg, #1a1a2e 0%, #16162a 100%)',
            border: '1px solid rgba(139, 92, 246, 0.3)',
            borderRadius: '12px',
            boxShadow: '0 10px 40px rgba(0, 0, 0, 0.5)',
            zIndex: 1000,
            overflow: 'hidden'
          }}
        >
          {/* Header */}
          <div
            style={{
              padding: '0.75rem 1rem',
              borderBottom: '1px solid rgba(255,255,255,0.1)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between'
            }}
          >
            <span style={{ fontWeight: 700, fontSize: '0.85rem', color: '#fff' }}>
              📤 Share Video
            </span>
            <button
              onClick={() => setIsOpen(false)}
              style={{
                background: 'transparent',
                border: 'none',
                color: '#888',
                cursor: 'pointer',
                padding: '0.2rem'
              }}
            >
              <X size={16} />
            </button>
          </div>

          {/* Native Share (Mobile) */}
          {shareSupported && (
            <button
              onClick={handleNativeShare}
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                gap: '0.75rem',
                padding: '0.75rem 1rem',
                background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
                border: 'none',
                color: '#fff',
                cursor: 'pointer',
                fontSize: '0.8rem',
                fontWeight: 600,
                textAlign: 'left'
              }}
            >
              <Smartphone size={20} />
              <div>
                <div>Share via Device</div>
                <div style={{ fontSize: '0.7rem', opacity: 0.8, fontWeight: 400 }}>
                  Use native share menu (best for mobile)
                </div>
              </div>
            </button>
          )}

          {/* Social Platforms */}
          <div style={{ padding: '0.5rem' }}>
            <div
              style={{
                fontSize: '0.7rem',
                color: '#888',
                padding: '0.25rem 0.5rem',
                marginBottom: '0.25rem'
              }}
            >
              Quick Upload Links
            </div>
            {SOCIAL_PLATFORMS.map((platform) => (
              <button
                key={platform.id}
                onClick={() => handlePlatformClick(platform)}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.75rem',
                  padding: '0.6rem 0.75rem',
                  background: 'transparent',
                  border: 'none',
                  color: '#fff',
                  cursor: 'pointer',
                  fontSize: '0.8rem',
                  textAlign: 'left',
                  borderRadius: '8px',
                  transition: 'background 0.15s ease'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'rgba(255,255,255,0.08)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'transparent';
                }}
              >
                <span style={{ fontSize: '1.2rem' }}>{platform.icon}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600 }}>{platform.name}</div>
                  <div style={{ fontSize: '0.68rem', color: '#888' }}>
                    {platform.description}
                  </div>
                </div>
                <ExternalLink size={14} style={{ color: '#666' }} />
              </button>
            ))}
          </div>

          {/* Copy Link */}
          <div
            style={{
              padding: '0.5rem 0.75rem 0.75rem',
              borderTop: '1px solid rgba(255,255,255,0.1)'
            }}
          >
            <button
              onClick={handleCopyLink}
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '0.5rem',
                padding: '0.5rem',
                background: copied ? 'rgba(16, 185, 129, 0.2)' : 'rgba(255,255,255,0.05)',
                border: `1px solid ${copied ? 'rgba(16, 185, 129, 0.5)' : 'rgba(255,255,255,0.1)'}`,
                borderRadius: '8px',
                color: copied ? '#10b981' : '#ccc',
                cursor: 'pointer',
                fontSize: '0.75rem',
                fontWeight: 500,
                transition: 'all 0.2s ease'
              }}
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
              {copied ? 'Link Copied!' : 'Copy Video Link'}
            </button>
          </div>

          {/* Tip */}
          <div
            style={{
              padding: '0.5rem 0.75rem 0.75rem',
              fontSize: '0.65rem',
              color: '#666',
              textAlign: 'center',
              lineHeight: 1.4
            }}
          >
            💡 Tip: Download video first, then upload to your chosen platform
          </div>
        </div>
      )}
    </div>
  );
};

export default ShareButton;
