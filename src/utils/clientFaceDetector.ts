/**
 * Fast Client-Side Face & Salient Object Detector
 * 
 * Runs 100% in the user's browser via:
 * 1. Native Shape Detection API (window.FaceDetector) if supported (Chrome, Edge).
 * 2. Canvas-based skin-tone centroid & luminosity tracker (160x90 thumbnail sample, ~1-2ms, universal fallback).
 * 
 * NEW: Active Speaker Detection (ASD) support for multiple faces.
 * When multiple faces are detected, analyzes motion in mouth region to identify the speaker.
 * 
 * Ensures 0 server load for local file uploads, with instantaneous tracking and no server roundtrips.
 */

export interface DetectedFaceBox {
  found: boolean;
  cx: number; // 0.0 to 1.0 (horizontal center)
  cy: number; // 0.0 to 1.0 (vertical center)
  w: number;  // normalized width
  h: number;  // normalized height
  type: 'face' | 'salient_object';
  isActiveSpeaker?: boolean; // NEW: indicates if this face is the active speaker
  facesDetected?: number;    // NEW: total number of faces found
}

// Store previous frame data for motion detection
let previousFrameData: ImageData | null = null;

/**
 * Analyzes mouth region motion between frames to detect speaking
 */
function analyzeMouthMotion(
  currentData: ImageData,
  previousData: ImageData,
  faceBox: { x: number; y: number; width: number; height: number },
  canvasWidth: number,
  canvasHeight: number
): number {
  // Extract mouth region (lower 40% of face)
  const mouthY = Math.floor(faceBox.y + faceBox.height * 0.55);
  const mouthX = Math.floor(faceBox.x + faceBox.width * 0.2);
  const mouthW = Math.floor(faceBox.width * 0.6);
  const mouthH = Math.floor(faceBox.height * 0.35);
  
  if (mouthW < 5 || mouthH < 3) return 0;
  
  let totalDiff = 0;
  let pixelCount = 0;
  
  for (let y = mouthY; y < Math.min(mouthY + mouthH, canvasHeight); y++) {
    for (let x = mouthX; x < Math.min(mouthX + mouthW, canvasWidth); x++) {
      const idx = (y * canvasWidth + x) * 4;
      
      // Calculate grayscale difference
      const currGray = (currentData.data[idx] * 0.299 + currentData.data[idx + 1] * 0.587 + currentData.data[idx + 2] * 0.114);
      const prevGray = (previousData.data[idx] * 0.299 + previousData.data[idx + 1] * 0.587 + previousData.data[idx + 2] * 0.114);
      
      totalDiff += Math.abs(currGray - prevGray);
      pixelCount++;
    }
  }
  
  return pixelCount > 0 ? totalDiff / pixelCount : 0;
}

export async function detectFaceClientSide(
  videoElement: HTMLVideoElement | null,
  facecamPosition: string = 'auto',
  _streamerPreset: string = 'none'
): Promise<DetectedFaceBox> {
  // Preset defaults if manual position selected
  if (facecamPosition === 'left') {
    return { found: true, cx: 0.28, cy: 0.35, w: 0.25, h: 0.35, type: 'face' };
  }
  if (facecamPosition === 'right') {
    return { found: true, cx: 0.72, cy: 0.35, w: 0.25, h: 0.35, type: 'face' };
  }
  if (facecamPosition === 'center') {
    return { found: true, cx: 0.50, cy: 0.35, w: 0.25, h: 0.35, type: 'face' };
  }

  if (!videoElement || videoElement.readyState < 2 || videoElement.videoWidth === 0) {
    return { found: false, cx: 0.50, cy: 0.35, w: 0.25, h: 0.35, type: 'face' };
  }

  const vWidth = videoElement.videoWidth;
  const vHeight = videoElement.videoHeight;

  // 1. Try Native Browser FaceDetector API (Shape Detection API)
  if (typeof (window as any).FaceDetector === 'function') {
    try {
      const detector = new (window as any).FaceDetector({ fastMode: true, maxDetectedFaces: 5 });
      const faces: any[] = await detector.detect(videoElement);
      
      if (faces && faces.length > 0) {
        // ACTIVE SPEAKER DETECTION for multiple faces
        if (faces.length >= 2) {
          // Create canvas for motion analysis
          const canvas = document.createElement('canvas');
          const sampleW = 320;
          const sampleH = 180;
          canvas.width = sampleW;
          canvas.height = sampleH;
          const ctx = canvas.getContext('2d', { willReadFrequently: true });
          
          if (ctx) {
            ctx.drawImage(videoElement, 0, 0, sampleW, sampleH);
            const currentFrameData = ctx.getImageData(0, 0, sampleW, sampleH);
            
            if (previousFrameData) {
              // Analyze mouth motion for each face
              const faceMotionScores: Array<{ face: any; motionScore: number; area: number }> = [];
              
              for (const face of faces) {
                const box = face.boundingBox;
                
                // Scale face coordinates to canvas size
                const scaledBox = {
                  x: Math.floor((box.x / vWidth) * sampleW),
                  y: Math.floor((box.y / vHeight) * sampleH),
                  width: Math.floor((box.width / vWidth) * sampleW),
                  height: Math.floor((box.height / vHeight) * sampleH)
                };
                
                const motionScore = analyzeMouthMotion(
                  currentFrameData,
                  previousFrameData,
                  scaledBox,
                  sampleW,
                  sampleH
                );
                
                const area = box.width * box.height;
                faceMotionScores.push({ face, motionScore, area });
              }
              
              // Select face with highest combined score (motion * 0.7 + size * 0.3)
              const maxMotion = Math.max(...faceMotionScores.map(f => f.motionScore), 1);
              const maxArea = Math.max(...faceMotionScores.map(f => f.area), 1);
              
              let bestFace = faceMotionScores[0];
              let bestScore = 0;
              
              for (const faceData of faceMotionScores) {
                const normalizedMotion = faceData.motionScore / maxMotion;
                const normalizedArea = faceData.area / maxArea;
                const combinedScore = normalizedMotion * 0.7 + normalizedArea * 0.3;
                
                if (combinedScore > bestScore) {
                  bestScore = combinedScore;
                  bestFace = faceData;
                }
              }
              
              previousFrameData = currentFrameData;
              
              const box = bestFace.face.boundingBox;
              const cx = Math.max(0.15, Math.min(0.85, (box.x + box.width / 2) / vWidth));
              const cy = Math.max(0.15, Math.min(0.85, (box.y + box.height / 2) / vHeight));
              const w = box.width / vWidth;
              const h = box.height / vHeight;
              
              return { 
                found: true, 
                cx, 
                cy, 
                w, 
                h, 
                type: 'face',
                isActiveSpeaker: true,
                facesDetected: faces.length
              };
            }
            
            previousFrameData = currentFrameData;
          }
        }
        
        // Single face or fallback: pick the largest detected face
        let largestFace = faces[0];
        let maxArea = largestFace.boundingBox.width * largestFace.boundingBox.height;
        for (let i = 1; i < faces.length; i++) {
          const area = faces[i].boundingBox.width * faces[i].boundingBox.height;
          if (area > maxArea) {
            maxArea = area;
            largestFace = faces[i];
          }
        }

        const box = largestFace.boundingBox;
        const cx = Math.max(0.15, Math.min(0.85, (box.x + box.width / 2) / vWidth));
        const cy = Math.max(0.15, Math.min(0.85, (box.y + box.height / 2) / vHeight));
        const w = box.width / vWidth;
        const h = box.height / vHeight;

        return { 
          found: true, 
          cx, 
          cy, 
          w, 
          h, 
          type: 'face',
          facesDetected: faces.length
        };
      }
    } catch (e) {
      // Shape detection api failed or permission denied, fall back to canvas
    }
  }

  // 2. High-performance canvas skin-tone & upper-body centroid fallback (~1.5ms)
  try {
    const canvas = document.createElement('canvas');
    const sampleW = 160;
    const sampleH = 90;
    canvas.width = sampleW;
    canvas.height = sampleH;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) {
      return { found: false, cx: 0.50, cy: 0.35, w: 0.25, h: 0.35, type: 'face' };
    }

    ctx.drawImage(videoElement, 0, 0, sampleW, sampleH);
    const imgData = ctx.getImageData(0, 0, sampleW, sampleH);
    const data = imgData.data;

    let sumX = 0;
    let sumY = 0;
    let count = 0;

    // Scan top 70% of frame (faces and speakers are almost always in upper-middle area)
    const scanRows = Math.floor(sampleH * 0.70);

    for (let y = 5; y < scanRows; y++) {
      for (let x = 5; x < sampleW - 5; x++) {
        const idx = (y * sampleW + x) * 4;
        const r = data[idx];
        const g = data[idx + 1];
        const b = data[idx + 2];

        // Standard skin tone classifier in RGB color space
        const isSkin =
          r > 95 &&
          g > 40 &&
          b > 20 &&
          r > g &&
          r > b &&
          r - g > 15 &&
          Math.max(r, g, b) - Math.min(r, g, b) > 15;

        if (isSkin) {
          sumX += x;
          sumY += y;
          count++;
        }
      }
    }

    if (count > 25) {
      const avgX = sumX / count;
      const avgY = sumY / count;
      const cx = Math.max(0.18, Math.min(0.82, avgX / sampleW));
      const cy = Math.max(0.15, Math.min(0.70, avgY / sampleH));

      return {
        found: true,
        cx,
        cy,
        w: 0.25,
        h: 0.35,
        type: 'face',
      };
    }
  } catch (canvasErr) {
    // Cross-origin or read error
  }

  // 3. Clean fallback to center
  return { found: false, cx: 0.50, cy: 0.35, w: 0.25, h: 0.35, type: 'face' };
}

/**
 * Reset the frame buffer (call when switching videos)
 */
export function resetFaceDetectionBuffer(): void {
  previousFrameData = null;
}
