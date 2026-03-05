import { Box } from '@mantine/core';
import { useState } from 'react';
import type { AnimatedGlowOrbProps } from "./AnimatedGlowOrb.types";
 
export default function AnimatedGlowOrb({
  size = 120,
}: AnimatedGlowOrbProps) {
  const [isHovered, setIsHovered] = useState(false);
  return (
    <Box
      style={{
        position: 'relative',
        width: size,
        height: size,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        perspective: '1000px',
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Holographic Pastel Ring - Clockwise Rotation */}
      <Box
        style={{
          position: 'absolute',
          inset: '-30%', // Extended further outward for more visible ring
          width: '160%',
          height: '160%',
          borderRadius: '50%',
          // 8-color pastel palette in clockwise rotation
          background: `conic-gradient(from 0deg,
            #dde6f2, #e1ece9, #ceeabaff, #e8f4d9, #e8f4da, #e3eee5, #dee8ee, #c4d6ecff, #dde6f2
          )`,
          // Wider ring - transparent center (0-50%), visible ring (55%+)
          mask: 'radial-gradient(transparent 50%, black 55%)',
          WebkitMask: 'radial-gradient(transparent 50%, black 55%)',
          filter: 'blur(6px)', // Reduced blur for more defined colors
          zIndex: 0,
          opacity: 1,
          animation: 'spin 10s linear infinite',
        }}
      />
 
      {/* 2. THE REFERENCE ORB IMAGE - Replacing CSS layers */}
      <Box
        style={{
          position: 'absolute',
          width: '100%',
          height: '100%',
          borderRadius: '50%',
          backgroundImage: 'url(/images/glow-orb.png)',
          backgroundSize: 'cover',
          backgroundPosition: 'center',
          zIndex: 2,
          animation: 'wobble 10s ease-in-out infinite, subtle-pulse 6s ease-in-out infinite',
          // Blend mode allows the rotating background to show through white areas
          mixBlendMode: 'multiply',
          filter: 'drop-shadow(0 0 15px rgba(221, 229, 242, 0.6))', // Matches background #dde5f2
        }}
      />
 
      {/* Rotating Color Effect - Only on Hover */}
      {isHovered && (
        <Box
          style={{
            position: 'absolute',
            width: '100%',
            height: '100%',
            borderRadius: '50%',
            background: `conic-gradient(from 0deg,
              #d4e9ff 0%,
              #e8d4ff 25%,
              #ffd4f4 50%,
              #d4fff0 75%,
              #d4e9ff 100%
            )`,
            zIndex: 3,
            pointerEvents: 'none',
            animation: 'spin 8s linear infinite',
            opacity: 0.6,
          }}
        />
      )}
 
      {/* 3. Subtle Outer Glass Shell (Overlay for depth) */}
      <Box
        style={{
          position: 'absolute',
          width: '102%',
          height: '102%',
          borderRadius: '50%',
          border: '1px solid rgba(255, 255, 255, 0.3)',
          boxShadow: 'inset 0 0 15px rgba(255, 255, 255, 0.1)',
          zIndex: 3,
          pointerEvents: 'none',
          animation: 'wobble 8s ease-in-out infinite',
        }}
      />
 
      <style dangerouslySetInnerHTML={{
        __html: `
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
                @keyframes subtle-pulse {
                    0%, 100% { transform: scale(1.0); }
                    50% { transform: scale(1.03); }
                }
                @keyframes wobble {
                    0%, 100% { border-radius: 50% 50% 50% 50%; transform: rotate(0deg); }
                    25% { border-radius: 51% 49% 51% 49%; transform: rotate(0.4deg); }
                    50% { border-radius: 49% 51% 51% 49%; transform: rotate(-0.4deg); }
                    75% { border-radius: 50% 50% 49% 51%; transform: rotate(0.2deg); }
                }
            `}} />
    </Box>
  );
}