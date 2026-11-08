import { AccuracyRow, clock, ReportPeak, Summary, Track } from "./api";

/**
 * Three cards on the Report about AI's part in the review: the footage it skipped so nobody had to
 * watch it, what it detected and how a person judged that, and how well its guesses held up.
 * Everything comes from the saved review, nothing is made up.
 */
const UNIDENTIFIED = "Fish, unidentified";

type Bar = { label: string; n: number; color: string };

function StackBar({ parts, label, fmt = String }: { parts: Bar[]; label: string; fmt?: (n: number) => string }) {
  const total = parts.reduce((a, p) => a + p.n, 0);
  return (
    <>
      <div className="ai-bar" role="img" aria-label={`${label}: ${parts.map((p) => `${p.label} ${fmt(p.n)}`).join(", ")}`}>
        {total > 0 && parts.filter((p) => p.n > 0).map((p) => (
          <i key={p.label} style={{ flex: `${p.n} 0 0`, background: p.color }} title={`${p.label}: ${fmt(p.n)}`} />
        ))}
      </div>
      <ul className="ai-key">
        {parts.map((p) => (
          <li key={p.label}><i style={{ background: p.color }} />{p.label}<b className="num">{fmt(p.n)}</b></li>
        ))}
      </ul>
    </>
  );
}

const Row = ({ k, v, note }: { k: string; v: string; note?: string }) => (
  <div className="ai-row">
    <span>{k}{note && <small className="meta">{note}</small>}</span>
    <b className="num">{v}</b>
  </div>
);

export function AiImpact({ s, tracks, accuracy, nameOf }: { s: Summary; tracks: Track[] | null; accuracy: AccuracyRow | null; nameOf: (sp: string) => string }) {
  const duration = s.video.duration || 0;
  const queue = s.reviewed + s.could_not_see + s.pending;
  const skippedPct = duration ? Math.round((s.skipped / duration) * 100) : 0;

  const ai = (tracks ?? []).filter((t) => !t.manual);
  const decided = ai.filter((t) => t.state);
  const kept = ai.filter((t) => t.state === "Confirmed").length;
  const changed = ai.filter((t) => t.state === "Corrected").length;
  const rejected = ai.filter((t) => t.state === "Rejected").length;
  const open = ai.length - decided.length;

  // AI's first species guess, for every detection it could name.
  const guesses = new Map<string, number>();
  ai.forEach((t) => { const g = t.candidates?.[0]?.species; if (g) guesses.set(g, (guesses.get(g) ?? 0) + 1); });
  const topGuesses = [...guesses].sort((a, b) => b[1] - a[1]).slice(0, 3);

  // Its guess against the species a person settled on. Fish left unidentified can't be judged.
  const judged = ai.filter((t) => (t.state === "Confirmed" || t.state === "Corrected") && t.decided_species && t.decided_species !== UNIDENTIFIED && t.candidates?.length);
  const right = judged.filter((t) => t.candidates[0].species === t.decided_species).length;
  const inTop3 = judged.filter((t) => t.candidates.slice(0, 3).some((c) => c.species === t.decided_species)).length;
  const pct = (a: number, b: number) => (b ? `${Math.round((a / b) * 100)}%` : "—");
  const avgConf = ai.length ? ai.reduce((a, t) => a + t.conf, 0) / ai.length : null;
  const busiest = s.peaks.reduce<ReportPeak | null>((best, p) => (!best || p.ai_count > best.ai_count ? p : best), null);

  if (tracks && !ai.length && !s.skipped && !queue) {
    return <p className="panel meta ai-none">AI hasn't analysed this video yet, so there's nothing to show about its part in the review.</p>;
  }

  return (
    <div className="ai-cards">
      <section className="panel report-card ai-card">
        <div className="report-card-head"><h2>Footage AI skipped</h2></div>
        <div className="ai-big">
          <b className="num">{clock(s.skipped)}</b>
          <span>with no fish detected, so nobody had to watch it</span>
        </div>
        <StackBar
          label="Footage"
          fmt={clock}
          parts={[
            { label: "Skipped by AI", n: Math.round(s.skipped), color: "var(--skip)" },
            { label: "Left for a person", n: Math.round(queue), color: "var(--accent)" },
          ]}
        />
        <div className="ai-rows">
          <Row k="Footage" v={clock(duration)} />
          <Row k="Skipped" v={`${skippedPct}%`} />
          <Row k="Time a person spent reviewing" v={clock(s.review_seconds)} />
          {s.audit_total > 0 && (
            <Row k="Spot checks of skipped footage" v={`${s.audit_segments} of ${s.audit_total}`} note={s.audit_fish ? ` · ${s.audit_fish} fish found` : " · no fish found"} />
          )}
        </div>
      </section>

      <section className="panel report-card ai-card">
        <div className="report-card-head"><h2>What AI detected</h2></div>
        <div className="ai-pair">
          <div className="ai-big"><b className="num">{tracks ? ai.length : "…"}</b><span>fish detections</span></div>
          <div className="ai-big"><b className="num">{tracks ? guesses.size : "…"}</b><span>species suggested</span></div>
        </div>
        <StackBar
          label="What a person decided"
          parts={[
            { label: "Confirmed", n: kept, color: "var(--up)" },
            { label: "Corrected", n: changed, color: "var(--amber)" },
            { label: "Not a fish", n: rejected, color: "#dc2626" },
            { label: "Not decided yet", n: open, color: "var(--muted-2)" },
          ]}
        />
        {topGuesses.length > 0 && (
          <div className="ai-guesses">
            <span className="meta">Most suggested</span>
            {topGuesses.map(([sp, n]) => <span key={sp} className="pill muted">{nameOf(sp)} <b className="num">{n}</b></span>)}
          </div>
        )}
      </section>

      <section className="panel report-card ai-card">
        <div className="report-card-head"><h2>How AI's guesses held up</h2></div>
        <div className="ai-big">
          <b className="num">{pct(right, judged.length)}</b>
          <span>{judged.length ? `first species guess right, ${right} of ${judged.length} named fish` : "No fish named by a person yet"}</span>
        </div>
        <div className="ai-rows">
          <Row k="Right species in its top 3" v={pct(inTop3, judged.length)} />
          <Row k="False alarms" v={pct(rejected, decided.length)} note={decided.length ? ` · ${rejected} of ${decided.length} checked` : ""} />
          <Row k="Fish AI missed, added by a person" v={String(s.entries_added)} />
          {accuracy && accuracy.frames_blind > 0 && (
            <Row k="Fish found in blind counts" v={pct(accuracy.found, accuracy.fish)} note={` · ${accuracy.found} of ${accuracy.fish}`} />
          )}
          {avgConf !== null && <Row k="Average detection confidence" v={`${Math.round(avgConf * 100)}%`} />}
          {busiest && <Row k="Most fish AI saw at once" v={String(busiest.ai_count)} note={` · at ${clock(busiest.t)}`} />}
        </div>
      </section>
    </div>
  );
}
