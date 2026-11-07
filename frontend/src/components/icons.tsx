// 設計稿（UI v1.8）的 inline SVG icon；顏色跟著 currentColor，大小由使用處用 className 決定。

type IconProps = { className?: string };

const stroke = {
  fill: "none",
  stroke: "currentColor",
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

export function PlaneIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className={className}>
      <path
        d="M21.5 15.2v-1.9l-8.3-5.2V3.3c0-.8-.6-1.5-1.3-1.5s-1.3.7-1.3 1.5v4.8l-8.3 5.2v1.9l8.3-2.6v4.8l-2.2 1.6v1.5l3.5-1 3.5 1v-1.5l-2.2-1.6v-4.8z"
        transform="rotate(45 12 12)"
      />
    </svg>
  );
}

export function ShieldIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" {...stroke} strokeWidth="2" aria-hidden="true" className={className}>
      <path d="M12 2.8 4.5 5.6v6c0 4.6 3.1 8.2 7.5 9.6 4.4-1.4 7.5-5 7.5-9.6v-6z" />
      <path d="m8.6 12 2.4 2.4 4.6-4.8" />
    </svg>
  );
}

export function DocIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" {...stroke} strokeWidth="2" aria-hidden="true" className={className}>
      <path d="M14 2.8H6.5A1.5 1.5 0 0 0 5 4.3v15.4a1.5 1.5 0 0 0 1.5 1.5h11a1.5 1.5 0 0 0 1.5-1.5V7.8z" />
      <path d="M14 2.8v5h5M8.5 12.5h7M8.5 16.5h7" />
    </svg>
  );
}

export function ArrowIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" {...stroke} strokeWidth="2.4" aria-hidden="true" className={className}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

export function ChevronIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" {...stroke} strokeWidth="2.6" aria-hidden="true" className={className}>
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}

export function UserIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 40 40" aria-hidden="true" className={className}>
      <circle cx="20" cy="20" r="18" fill="none" stroke="currentColor" strokeWidth="3" />
      <circle cx="20" cy="15.5" r="6" fill="currentColor" />
      <path
        d="M8.5 31c2.4-5 6.6-7.2 11.5-7.2S29.1 26 31.5 31A16 16 0 0 1 8.5 31z"
        fill="currentColor"
      />
    </svg>
  );
}
