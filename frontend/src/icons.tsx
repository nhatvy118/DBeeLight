/**
 * Icon set — clean 1.75 stroke line icons, ported from the Chat/ design
 * prototype (Chat/icons.jsx). Each icon takes { size, className, style,
 * strokeWidth, fill }.
 */
import type { CSSProperties, ReactNode } from 'react';
import beePng from './assets/icons/bee.png';

export type IconProps = {
  size?: number;
  className?: string;
  style?: CSSProperties;
  strokeWidth?: number;
  fill?: string;
};

export type IconComponent = (props: IconProps) => JSX.Element;

const Ic =
  (paths: ReactNode, vb = '0 0 24 24'): IconComponent =>
  ({ size = 20, className = '', style, strokeWidth = 1.75, fill = 'none' }: IconProps) => (
    <svg
      width={size}
      height={size}
      viewBox={vb}
      className={className}
      style={style}
      fill={fill}
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths}
    </svg>
  );

export const Icons: Record<string, IconComponent> = {
  NewChat: Ic([<path key="a" d="M12 20h9" />, <path key="b" d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />]),
  Database: Ic([<ellipse key="a" cx={12} cy={5} rx={8} ry={3} />, <path key="b" d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />, <path key="c" d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />]),
  FolderPlus: Ic([<path key="a" d="M3 7a2 2 0 0 1 2-2h4l2 2.5h6a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />, <path key="b" d="M12 11v5" />, <path key="c" d="M9.5 13.5h5" />]),
  Folder: Ic([<path key="a" d="M3 7a2 2 0 0 1 2-2h4l2 2.5h6a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />]),
  Sidebar: Ic([<rect key="a" x={3} y={4} width={18} height={16} rx={2.5} />, <path key="b" d="M9 4v16" />]),
  Share: Ic([<path key="a" d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7" />, <path key="b" d="M16 6l-4-4-4 4" />, <path key="c" d="M12 2v13" />]),
  Export: Ic([<path key="a" d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />, <path key="b" d="M7 10l5 5 5-5" />, <path key="c" d="M12 15V3" />]),
  Plus: Ic([<path key="a" d="M12 5v14" />, <path key="b" d="M5 12h14" />]),
  Mic: Ic([<rect key="a" x={9} y={3} width={6} height={11} rx={3} />, <path key="b" d="M5 11a7 7 0 0 0 14 0" />, <path key="c" d="M12 18v3" />]),
  ArrowUp: Ic([<path key="a" d="M12 19V5" />, <path key="b" d="M6 11l6-6 6 6" />]),
  Stop: Ic([<rect key="a" x={6} y={6} width={12} height={12} rx={2.5} />]),
  Send: Ic([<path key="a" d="M12 19V5" />, <path key="b" d="M6 11l6-6 6 6" />]),
  Sun: Ic([<circle key="a" cx={12} cy={12} r={4} />, <path key="b" d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />]),
  Moon: Ic([<path key="a" d="M21 12.8A8.5 8.5 0 1 1 11.2 3a6.5 6.5 0 0 0 9.8 9.8Z" />]),
  Close: Ic([<path key="a" d="M18 6 6 18" />, <path key="b" d="M6 6l12 12" />]),
  Check: Ic([<path key="a" d="M20 6 9 17l-5-5" />]),
  ChevronDown: Ic([<path key="a" d="M6 9l6 6 6-6" />]),
  ChevronRight: Ic([<path key="a" d="M9 6l6 6-6 6" />]),
  Sparkle: Ic([<path key="a" d="M12 3l1.8 4.9L19 9.7l-4.2 1.8L12 16l-2.8-4.5L5 9.7l5.2-1.8Z" />, <path key="b" d="M19 14l.8 2.2L22 17l-2.2.8L19 20l-.8-2.2L16 17l2.2-.8Z" />]),
  Table: Ic([<rect key="a" x={3} y={4} width={18} height={16} rx={2} />, <path key="b" d="M3 10h18" />, <path key="c" d="M3 15h18" />, <path key="d" d="M9 4v16" />, <path key="e" d="M15 4v16" />]),
  Chart: Ic([<path key="a" d="M4 20V4" />, <path key="b" d="M4 20h16" />, <rect key="c" x={7} y={11} width={3} height={6} rx={0.6} fill="currentColor" stroke="none" />, <rect key="d" x={12} y={7} width={3} height={10} rx={0.6} fill="currentColor" stroke="none" />, <rect key="e" x={17} y={13} width={3} height={4} rx={0.6} fill="currentColor" stroke="none" />]),
  Code: Ic([<path key="a" d="M8 6 2 12l6 6" />, <path key="b" d="M16 6l6 6-6 6" />]),
  Refresh: Ic([<path key="a" d="M3 12a9 9 0 0 1 15-6.7L21 8" />, <path key="b" d="M21 3v5h-5" />, <path key="c" d="M21 12a9 9 0 0 1-15 6.7L3 16" />, <path key="d" d="M3 21v-5h5" />]),
  Copy: Ic([<rect key="a" x={9} y={9} width={12} height={12} rx={2.5} />, <path key="b" d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />]),
  File: Ic([<path key="a" d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" />, <path key="b" d="M14 3v5h5" />]),
  Upload: Ic([<path key="a" d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />, <path key="b" d="M7 9l5-5 5 5" />, <path key="c" d="M12 4v12" />]),
  Download: Ic([<path key="a" d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />, <path key="b" d="M7 10l5 5 5-5" />, <path key="c" d="M12 15V3" />]),
  Lightning: Ic([<path key="a" d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z" />]),
  Search: Ic([<circle key="a" cx={11} cy={11} r={7} />, <path key="b" d="M21 21l-4-4" />]),
  Dots: Ic([<circle key="a" cx={5} cy={12} r={1.4} fill="currentColor" stroke="none" />, <circle key="b" cx={12} cy={12} r={1.4} fill="currentColor" stroke="none" />, <circle key="c" cx={19} cy={12} r={1.4} fill="currentColor" stroke="none" />]),
  Link: Ic([<path key="a" d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1.5 1.5" />, <path key="b" d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1.5-1.5" />]),
  Trash: Ic([<path key="a" d="M3 6h18" />, <path key="b" d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />, <path key="c" d="M6 6l1 14a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-14" />]),
  Eye: Ic([<path key="a" d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />, <circle key="b" cx={12} cy={12} r={3} />]),
  Pencil: Ic([<path key="a" d="M12 20h9" />, <path key="b" d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />]),
  Hash: Ic([<path key="a" d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18" />]),
  Calendar: Ic([<rect key="a" x={3} y={4} width={18} height={17} rx={2.5} />, <path key="b" d="M3 9h18M8 2v4M16 2v4" />]),
  Text: Ic([<path key="a" d="M4 6h16M4 12h16M4 18h10" />]),
  Server: Ic([<rect key="a" x={3} y={4} width={18} height={7} rx={2} />, <rect key="b" x={3} y={13} width={18} height={7} rx={2} />, <path key="c" d="M7 7.5h.01M7 16.5h.01" />]),
  HardDrive: Ic([<path key="a" d="M3 13h18" />, <path key="b" d="M5 13 7 5h10l2 8v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1Z" />, <path key="c" d="M8 17h.01M12 17h.01" />]),
  Info: Ic([<circle key="a" cx={12} cy={12} r={9} />, <path key="b" d="M12 11v5M12 8h.01" />]),
  Settings: Ic([<circle key="a" cx={12} cy={12} r={3} />, <path key="b" d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 0 1-4 0v-.1A1.6 1.6 0 0 0 7 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0-1.1-2.7H1a2 2 0 0 1 0-4h.1A1.6 1.6 0 0 0 2.6 7a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H7a1.6 1.6 0 0 0 1-1.5V1a2 2 0 0 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V7a1.6 1.6 0 0 0 1.5 1H23a2 2 0 0 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1Z" />]),
  Logout: Ic([<path key="a" d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />, <path key="b" d="M16 17l5-5-5-5" />, <path key="c" d="M21 12H9" />]),
  Pin: Ic([<path key="a" d="M9 4h6l-1 6 3 3v2H7v-2l3-3-1-6Z" />, <path key="b" d="M12 18v3" />]),
  Question: Ic([<circle key="a" cx={12} cy={12} r={9} />, <path key="b" d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.8.4-1 .9-1 1.7" />, <path key="c" d="M12 16h.01" />]),
  Cloud: Ic([<path key="a" d="M7 18a4 4 0 0 1-.5-7.97 5.5 5.5 0 0 1 10.6-1.2A4.5 4.5 0 0 1 17 18Z" />]),
  Drive: Ic([<path key="a" d="M8 3h8l5.5 9.5L17 21H7L1.5 12.5 8 3Z" />, <path key="b" d="M8 3 1.5 12.5h11M16 3l5.5 9.5M12.5 12.5 7 21M21.5 12.5H10" />]),
  Monitor: Ic([<rect key="a" x={3} y={4} width={18} height={13} rx={2} />, <path key="b" d="M8 21h8M12 17v4" />]),
};

/** The honey bee badge used throughout the app. */
export function BeeBadge({ size = 36, style }: { size?: number; style?: CSSProperties }) {
  return (
    <div className="bee-badge" style={{ width: size, height: size, ...style }}>
      <img src={beePng} alt="LightDBee" />
    </div>
  );
}
