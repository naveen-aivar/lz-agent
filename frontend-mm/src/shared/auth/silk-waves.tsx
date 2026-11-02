import { useId } from 'react';

// Six softly drifting wave paths behind a radial highlight: the blue panel beside the sign-in form (the unified dashboard's "Silk Waves",
// light only). Decorative, so hidden from screen readers; the drift stops under reduced motion (see globals.css).
const WAVE_COUNT = 6;

export function SilkWaves({
  color = '#1570ef',
  highlight = '#ffffff',
  speed = 14,
  intensity = 0.6,
  angle = -16,
}: {
  color?: string;
  highlight?: string;
  speed?: number;
  intensity?: number;
  angle?: number;
}) {
  const id = useId().replaceAll(':', '');
  const duration = Math.max(3, speed);
  return (
    <div
      className="silk-root"
      aria-hidden
      style={{ '--silk-speed': `${duration}s`, '--silk-angle': `${angle}deg` } as React.CSSProperties}
    >
      <div className="silk-fabric" style={{ opacity: intensity }}>
        <svg viewBox="0 0 1200 800" preserveAspectRatio="xMidYMid slice">
          <defs>
            <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
              <stop stopColor={color} stopOpacity="0" />
              <stop offset=".48" stopColor={color} stopOpacity=".25" />
              <stop offset=".58" stopColor={highlight} stopOpacity=".9" />
              <stop offset=".64" stopColor={color} stopOpacity=".3" />
              <stop offset="1" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          {Array.from({ length: WAVE_COUNT }, (_, i) => (
            <path
              key={i}
              className="silk-wave"
              fill={`url(#${id})`}
              style={{ animationDelay: `${i * -1.7}s`, animationDuration: `${duration + i * 0.7}s` }}
              d={`M-200 ${70 + i * 130} C180 ${-170 + i * 130} 440 ${300 + i * 85} 760 ${90 + i * 100} S1200 ${-50 + i * 120} 1500 ${180 + i * 120} L1500 ${410 + i * 120} C1150 ${140 + i * 120} 1040 ${430 + i * 100} 700 ${300 + i * 100} S160 ${60 + i * 130} -200 ${300 + i * 130}Z`}
            />
          ))}
        </svg>
      </div>
    </div>
  );
}
