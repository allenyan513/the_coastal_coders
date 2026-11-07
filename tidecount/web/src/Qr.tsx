import qrcode from "qrcode-generator";
import { useMemo } from "react";

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
