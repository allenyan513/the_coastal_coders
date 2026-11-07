import { ReactNode, useState } from "react";

/** How the footage is drawn, to make fish easier to see. Each is a percentage; 100 (0 for sharpness) leaves it as filmed. */
export type Picture = { brightness: number; contrast: number; saturation: number; sharpness: number };

export const AS_FILMED: Picture = { brightness: 100, contrast: 100, saturation: 100, sharpness: 0 };

const PRESETS: { name: string; hint: string; p: Picture }[] = [
  { name: "Murky water", hint: "More contrast and edge, for green or cloudy footage", p: { brightness: 112, contrast: 145, saturation: 125, sharpness: 45 } },
  { name: "Dark footage", hint: "Lifts shadows, for dusk or deep footage", p: { brightness: 165, contrast: 115, saturation: 110, sharpness: 20 } },
  { name: "Outlines", hint: "Grayscale with strong contrast, to pick out shapes", p: { brightness: 105, contrast: 150, saturation: 0, sharpness: 60 } },
];

const SLIDERS: { key: keyof Picture; label: string; min: number; max: number }[] = [
  { key: "brightness", label: "Brightness", min: 50, max: 200 },
  { key: "contrast", label: "Contrast", min: 50, max: 200 },
  { key: "saturation", label: "Saturation", min: 0, max: 200 },
  { key: "sharpness", label: "Sharpness", min: 0, max: 100 },
];

const STORE = "tidecount.picture";
const same = (a: Picture, b: Picture) => SLIDERS.every(({ key }) => a[key] === b[key]);

/** The viewer's picture settings, kept in this browser so they carry over to the next video. */
export function usePicture(): [Picture, (p: Picture) => void] {
  const [p, setP] = useState<Picture>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE) ?? "null");
      return saved ? { ...AS_FILMED, ...saved } : AS_FILMED;
    } catch {
      return AS_FILMED;
    }
  });
  const save = (next: Picture) => {
    setP(next);
    try { localStorage.setItem(STORE, JSON.stringify(next)); } catch { /* private window: settings last this visit */ }
  };
  return [p, save];
}

/** The CSS filter for a picture. Sharpness has no CSS filter, so it points at the SVG one SharpenFilter draws. */
export function pictureFilter(p: Picture, sharpenId: string): string {
  const parts = [
    p.brightness !== 100 && `brightness(${p.brightness / 100})`,
    p.contrast !== 100 && `contrast(${p.contrast / 100})`,
    p.saturation !== 100 && `saturate(${p.saturation / 100})`,
    p.sharpness > 0 && `url(#${sharpenId})`,
  ].filter(Boolean);
  return parts.join(" ") || "none";
}

/** An unsharp kernel: the centre pixel pushed away from its four neighbours, more as the amount rises. */
export function SharpenFilter({ id, amount }: { id: string; amount: number }) {
  const a = (amount / 100) * 1.2;
  const kernel = [0, -a, 0, -a, 1 + 4 * a, -a, 0, -a, 0].map((n) => n.toFixed(3)).join(" ");
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
      <filter id={id} colorInterpolationFilters="sRGB">
        <feConvolveMatrix order="3" kernelMatrix={kernel} preserveAlpha="true" edgeMode="duplicate" />
      </filter>
    </svg>
  );
}

/** children: more switches for what is drawn over the video, listed under Grayscale. top: tools above the presets. */
type Props = { value: Picture; onChange: (p: Picture) => void; onCompare: (showing: boolean) => void; children?: ReactNode; top?: ReactNode };

/** Sliders and presets for how the footage looks. Nothing here changes the video or any count. */
export function PicturePanel({ value, onChange, onCompare, children, top }: Props) {
  const gray = value.saturation === 0;
  const changed = !same(value, AS_FILMED);
  const hold = { onPointerDown: () => onCompare(true), onPointerUp: () => onCompare(false), onPointerLeave: () => onCompare(false) };

  return (
    <aside className="panel picture-col" aria-label="Picture">
      <div className="picture-head">
        <h2>Picture</h2>
        <button className="btn quiet" disabled={!changed} onClick={() => onChange(AS_FILMED)}>Reset</button>
      </div>

      {top}

      <div className="picture-presets" role="group" aria-label="Presets">
        {PRESETS.map((x) => (
          <button key={x.name} className="chip" aria-pressed={same(value, x.p)} title={x.hint} onClick={() => onChange(x.p)}>{x.name}</button>
        ))}
      </div>

      <div className="picture-sliders">
        {SLIDERS.map((s) => (
          <label key={s.key} className="slider">
            <span className="slider-head">
              <span>{s.label}</span>
              <span className="num meta">{value[s.key]}%</span>
            </span>
            <input
              type="range"
              min={s.min}
              max={s.max}
              step={5}
              value={value[s.key]}
              onChange={(e) => onChange({ ...value, [s.key]: Number(e.target.value) })}
              onDoubleClick={() => onChange({ ...value, [s.key]: AS_FILMED[s.key] })}
              title="Double-click to reset"
            />
          </label>
        ))}
      </div>

      <div className="switches">
        <label className="switch">
          <input type="checkbox" checked={gray} onChange={() => onChange({ ...value, saturation: gray ? 100 : 0 })} />
          <span>Grayscale</span>
        </label>
        {children}
      </div>

      <button className="btn" disabled={!changed} {...hold}>Hold to see original</button>
    </aside>
  );
}
