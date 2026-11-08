import { RefObject, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

/*
 * The front page's "underwater" footer (issue #50). The page content sits in a raised <main>
 * and this footer is `position: sticky; bottom: 0` underneath it, so as the content scrolls
 * away the footer is uncovered, like dropping below the water's surface. Pure CSS: no
 * smooth-scroll library, and the footer keeps its natural height.
 */

/** True while the element is no taller than the window. A taller sticky footer would have its top
 *  covered by the content above for good, so the reveal only turns on when the footer fits. */
function useFits(ref: RefObject<HTMLElement>) {
  const [fits, setFits] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => setFits(el.offsetHeight <= window.innerHeight);
    const ro = new ResizeObserver(check);
    ro.observe(el);
    window.addEventListener("resize", check);
    check();
    return () => { ro.disconnect(); window.removeEventListener("resize", check); };
  }, [ref]);
  return fits;
}

/** The water's surface: a white wave hanging off the bottom of <main>, over the top of the footer. */
export function Surface() {
  return (
    <svg className="ln-surface" viewBox="0 0 1440 80" preserveAspectRatio="none" aria-hidden>
      <path d="M0 0H1440V36C1200 76 960 4 720 36S240 76 0 36Z" fill="#fff" />
      <path d="M0 36C240 76 480 4 720 36S1200 76 1440 36" fill="none" stroke="#8fb4ff" strokeWidth="1.5" opacity=".5" />
    </svg>
  );
}

/** Bubbles rising through the footer: [left %, size px, duration s, delay s]. */
const BUBBLES: [number, number, number, number][] = [
  [6, 6, 11, 0], [14, 10, 14, 3], [27, 5, 9, 6], [38, 8, 13, 1], [52, 4, 10, 4],
  [63, 9, 15, 7], [71, 5, 8, 2], [82, 12, 16, 5], [91, 6, 12, 8],
];

export function RevealFooter() {
  const ref = useRef<HTMLElement>(null);
  const reveal = useFits(ref);
  // A sticky footer counts as "in view" to the browser even while <main> still covers it, so tabbing
  // into a link wouldn't scroll. Jump to the end of the page instead, where the footer is uncovered.
  const uncover = () => {
    const end = document.documentElement.scrollHeight - window.innerHeight;
    if (reveal && window.scrollY < end - 1) window.scrollTo({ top: end });
  };
  return (
    <footer ref={ref} className={`ln-deep ${reveal ? "reveal" : ""}`} onFocus={uncover}>
      <div className="ln-deep-rays" aria-hidden />
      <div className="ln-deep-bubbles" aria-hidden>
        {BUBBLES.map(([left, size, dur, delay]) => (
          <i key={left} style={{ left: `${left}%`, width: size, height: size, animationDuration: `${dur}s`, animationDelay: `-${delay}s` }} />
        ))}
      </div>

      <div className="ln-wrap ln-deep-grid">
        <div className="stack" style={{ gap: 14 }}>
          <Link to="/" className="ln-brand"><img src="/favicon.svg" alt="" />Tideflow</Link>
          <p className="ln-deep-text">Underwater video in, confirmed fish counts out, for the people who survey Nova Scotia's living shorelines.</p>
          <div className="ln-deep-built">
            <span className="ln-eyebrow">Built by</span>
            <b>The Coastal Coders</b>
            <span>NSCC IT Programming for AI</span>
            <span>At RBC HubHacks 2026, with Coastal Action</span>
          </div>
        </div>
        <div className="ln-deep-col"><b>Platform</b><Link to="/workspace">Workspace</Link><Link to="/workflow">Workflow board</Link><Link to="/analysis">Data analysis</Link><Link to="/login">Sign in</Link></div>
        <div className="ln-deep-col"><b>Explore</b><Link to="/species">Species wiki</Link><Link to="/analysis/trends">Fish and water trends</Link><a href="#ai">How the computer vision works</a></div>
        <div className="ln-deep-col"><b>Project</b><a href="https://github.com/allenyan513/the_coastal_coders" target="_blank" rel="noreferrer">Source on GitHub</a><a href="#top">Back to the surface ↑</a></div>
      </div>

      <div className="ln-wrap ln-deep-word" aria-hidden>Tideflow</div>

      <div className="ln-wrap ln-deep-fine">
        <span>Fish detection by the Community Fish Detector and other open models; species suggestions by BioCLIP. Species list from iNaturalist and OBIS records.</span>
        <span>© 2026 Tideflow</span>
      </div>
    </footer>
  );
}
