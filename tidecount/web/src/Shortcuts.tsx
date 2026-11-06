import { useEffect, useState } from "react";

export type KeyGroup = { title: string; keys: [string, string][] };

/** A button and the ? key open one panel listing every shortcut on the page. */
export function Shortcuts({ groups }: { groups: KeyGroup[] }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (["INPUT", "SELECT", "TEXTAREA"].includes((e.target as HTMLElement).tagName)) return;
      if (e.key === "?") setOpen((v) => !v);
      else if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <button className="btn quiet" onClick={() => setOpen(true)} title="Press ? to open"><kbd>?</kbd>Shortcuts</button>
      {open && (
        <div className="help-back" onClick={() => setOpen(false)}>
          <div className="help" role="dialog" aria-label="Keyboard shortcuts" onClick={(e) => e.stopPropagation()}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h2>Keyboard shortcuts</h2>
              <button className="btn" onClick={() => setOpen(false)}>Close</button>
            </div>
            {groups.map((g) => (
              <section key={g.title} className="stack" style={{ gap: 6 }}>
                <p className="side-label" style={{ padding: 0 }}>{g.title}</p>
                <div className="help-grid">
                  {g.keys.map(([keys, label]) => (
                    <div className="help-row" key={label}>
                      <span>{label}</span>
                      <span>{keys.split(" ").map((k) => <kbd key={k}>{k}</kbd>)}</span>
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
