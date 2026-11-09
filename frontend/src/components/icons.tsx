import type { ReactNode } from "react";

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

// 功能一 1-2 的 9 個在意事項圖示（線條，stroke 2，跟著 currentColor）
function Line({ className, children }: IconProps & { children: ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" {...stroke} strokeWidth="2" aria-hidden="true" className={className}>
      {children}
    </svg>
  );
}

/** 突然生病就醫 */
export function MedIcon(props: IconProps) {
  return (
    <Line {...props}>
      <rect x="3.5" y="3.5" width="17" height="17" rx="4" />
      <path d="M12 8v8M8 12h8" />
    </Line>
  );
}

/** 需要緊急送醫或家屬趕來 */
export function PulseIcon(props: IconProps) {
  return (
    <Line {...props}>
      <path d="M2.5 12.5h4l2.5-6 4 11 2.5-5h6" />
    </Line>
  );
}

/** 行程取消或更改 */
export function XCalIcon(props: IconProps) {
  return (
    <Line {...props}>
      <rect x="3.5" y="5" width="17" height="15.5" rx="2.5" />
      <path d="M3.5 10h17M8 3v4M16 3v4M10 13.5l4 4M14 13.5l-4 4" />
    </Line>
  );
}

/** 班機延誤 */
export function ClockIcon(props: IconProps) {
  return (
    <Line {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5.2l3.2 2" />
    </Line>
  );
}

/** 行李延誤 */
export function BagIcon(props: IconProps) {
  return (
    <Line {...props}>
      <rect x="4.5" y="7.5" width="15" height="13" rx="2.5" />
      <path d="M9 7.5V5a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 5v2.5M9 11.5v5M15 11.5v5" />
    </Line>
  );
}

/** 行李遺失或損壞 */
export function BagWarnIcon(props: IconProps) {
  return (
    <Line {...props}>
      <rect x="4.5" y="7.5" width="15" height="13" rx="2.5" />
      <path d="M9 7.5V5a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 5v2.5M12 11.5v3.2M12 17.2v.1" />
    </Line>
  );
}

/** 證件遺失 */
export function IdIcon(props: IconProps) {
  return (
    <Line {...props}>
      <rect x="3" y="5" width="18" height="14" rx="2.5" />
      <circle cx="8.5" cy="11" r="2" />
      <path d="M5.8 16c.6-1.6 1.6-2.3 2.7-2.3s2.1.7 2.7 2.3M14 10h4.5M14 13.5h3" />
    </Line>
  );
}

/** 信用卡盜刷 */
export function CardIcon(props: IconProps) {
  return (
    <Line {...props}>
      <rect x="3" y="5.5" width="18" height="13" rx="2.5" />
      <path d="M3 10h18M7 15h3.5" />
    </Line>
  );
}

/** 不小心弄傷別人或弄壞東西 */
export function WarnIcon(props: IconProps) {
  return (
    <Line {...props}>
      <path d="M12 3.5 21.5 19.5h-19z" />
      <path d="M12 10v4.2M12 16.8v.1" />
    </Line>
  );
}

/** 名詞按鈕後面的 ⓘ */
export function InfoIcon(props: IconProps) {
  return (
    <Line {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5.2M12 7.8v.1" />
    </Line>
  );
}
