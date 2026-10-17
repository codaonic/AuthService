import { SVGProps, useId } from "react";

export interface AuthIconProps extends SVGProps<SVGSVGElement> {
  size?: number;
}

/**
 * Official Auth Service Brand Icon.
 * Features the cryptographic aerodynamic shield, ambient beacon,
 * and the central Auth Key & Token Core.
 */
export function AuthIcon({ size = 24, className, style, ...props }: AuthIconProps) {
  const rawId = useId();
  const id = rawId.replace(/[^a-zA-Z0-9]/g, "");

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      style={{ display: "inline-block", verticalAlign: "middle", flexShrink: 0, ...style }}
      aria-label="Auth Service"
      role="img"
      {...props}
    >
      <defs>
        <linearGradient id={`asShield-${id}`} x1="16" y1="5.5" x2="48" y2="58" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#6366F1" />
          <stop offset="55%" stopColor="#4F46E5" />
          <stop offset="100%" stopColor="#312E81" />
        </linearGradient>

        <linearGradient id={`asRim-${id}`} x1="32" y1="5.5" x2="32" y2="58" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.65" />
          <stop offset="40%" stopColor="#FFFFFF" stopOpacity="0.2" />
          <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0.03" />
        </linearGradient>

        <linearGradient id={`asCore-${id}`} x1="32" y1="16" x2="32" y2="44" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#FFFFFF" />
          <stop offset="100%" stopColor="#EEF2FF" />
        </linearGradient>

        <filter id={`asShadow-${id}`} x="-10%" y="-10%" width="120%" height="120%">
          <feDropShadow dx="0" dy="2" stdDeviation="2.5" floodColor="#312E81" floodOpacity="0.35" />
        </filter>
      </defs>

      {/* Aerodynamic Shield Contour */}
      <path
        d="M32 5.5C38 6.2 45 8.5 49.5 11.2C51.8 12.5 52.5 14.5 52.5 17.5V31C52.5 43.5 43.5 52.8 32.5 58C32.2 58.2 31.8 58.2 31.5 58C20.5 52.8 11.5 43.5 11.5 31V17.5C11.5 14.5 12.2 12.5 14.5 11.2C19 8.5 26 6.2 32 5.5Z"
        fill={`url(#asShield-${id})`}
        filter={`url(#asShadow-${id})`}
      />

      {/* Outer Precision Rim Stroke */}
      <path
        d="M32 6.8C37.8 7.5 44.5 9.7 48.8 12.3C50.6 13.4 51.2 15 51.2 17.5V31C51.2 42.8 42.8 51.6 32 56.6C21.2 51.6 12.8 42.8 12.8 31V17.5C12.8 15 13.4 13.4 15.2 12.3C19.5 9.7 26.2 7.5 32 6.8Z"
        fill="none"
        stroke={`url(#asRim-${id})`}
        strokeWidth="1.2"
      />

      {/* Concentric Token Validation Ring */}
      <path
        d="M22 23.5C22 18 26.5 13.5 32 13.5C37.5 13.5 42 18 42 23.5"
        fill="none"
        stroke="#FFFFFF"
        strokeOpacity="0.28"
        strokeWidth="1.8"
        strokeDasharray="2 3"
      />

      {/* Azure Token Beacon Dot */}
      <circle cx="32" cy="11.2" r="1.8" fill="#38BDF8" />

      {/* Key & Token Head */}
      <circle cx="32" cy="23.5" r="7.5" fill={`url(#asCore-${id})`} />
      {/* Keyway Inner Aperture */}
      <circle cx="32" cy="23.5" r="3.6" fill="#3730A3" />

      {/* Key Stem */}
      <rect x="29.6" y="27" width="4.8" height="16.5" rx="2.4" fill={`url(#asCore-${id})`} />

      {/* Authorization Bits (OAuth 2.1 & OIDC tokens) */}
      <rect x="33.5" y="32.5" width="5.5" height="3.2" rx="1.6" fill={`url(#asCore-${id})`} />
      <rect x="33.5" y="38" width="4" height="3.2" rx="1.6" fill={`url(#asCore-${id})`} />
      <rect x="25" y="34.8" width="5.5" height="3.2" rx="1.6" fill={`url(#asCore-${id})`} />
    </svg>
  );
}

