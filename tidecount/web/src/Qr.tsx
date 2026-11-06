import qrcode from "qrcode-generator";
import { useEffect, useMemo } from "react";
import { isLocal } from "./api";

/** Where the QR codes lead. It follows the address in use, so it works on any host. */
export const startUrl = () => `${window.location.origin}/start`;

const QUIET = 4;  // the blank margin a scanner needs, in QR squares

export function QrCode({ value, size = 220 }: { value: string; size?: number }) {
  const { count, path } = useMemo(() => {
    const qr = qrcode(0, "M");
    qr.addData(value);
    qr.make();
    const count = qr.getModuleCount();
    let path = "";
    for (let row = 0; row < count; row++) {
      for (let col = 0; col < count; col++) {
        if (qr.isDark(row, col)) path += `M${col} ${row}h1v1h-1z`;
      }
    }
    return { count, path };
  }, [value]);
  const side = count + QUIET * 2;

  return (
    <svg className="qr" width={size} height={size} viewBox={`${-QUIET} ${-QUIET} ${side} ${side}`} role="img" aria-label={`QR code for ${value}`} shapeRendering="crispEdges">
      <rect x={-QUIET} y={-QUIET} width={side} height={side} fill="#fff" />
      <path d={path} fill="#101828" />
    </svg>
  );
}

/** A code big enough to scan from across a table, for showing the app to a room. */
export function QrDialog({ onClose }: { onClose: () => void }) {
  const url = startUrl();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="help-back" onClick={onClose}>
      <div className="help qr-dialog" role="dialog" aria-label="Open on your phone" onClick={(e) => e.stopPropagation()}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>Open on your phone</h2>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
        <QrCode value={url} size={320} />
        <p className="num meta">{url}</p>
        {isLocal && <p className="meta" style={{ color: "var(--warn)" }}>This address only works on this computer, so a phone can't open it. Show this code from the public site.</p>}
      </div>
    </div>
  );
}
