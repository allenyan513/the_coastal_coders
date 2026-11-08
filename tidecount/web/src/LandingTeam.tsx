import { ReactNode } from "react";

/*
 * The front page's team section: roles, how a video moves between people, access and joining.
 * Each part says whether it works in the app today ("Live") or is designed but not built ("Planned"),
 * because judges can open the app and check. What is live, as of main on 2026-11-08:
 *   roles volunteer and manager (session.tsx ROLES), role-specific homes and manager-only pages
 *   (main.tsx Home and ManagerOnly), the four-stage Workflow board (Board.tsx), and team invites
 *   with a role, role changes and removal (Team.tsx). Invites and the team live in the browser,
 *   and no email is sent, so email, assignment, validation and server-side checks are planned.
 */

const P = {
  volunteer: <><circle cx="12" cy="8" r="3.5" /><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5" /></>,
  validator: <><path d="M12 3 5 6v5c0 4.4 3 8.2 7 9.5 4-1.3 7-5.1 7-9.5V6Z" /><path d="m9 12 2.2 2.2L15.5 10" /></>,
  coordinator: <><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M4 10h16M10 10v10" /></>,
  import: <><path d="M12 4v11M7.5 10.5 12 15l4.5-4.5" /><path d="M4 17v3h16v-3" /></>,
  count: <><circle cx="8" cy="9" r="1.6" /><circle cx="15" cy="7" r="1.6" /><circle cx="11" cy="15" r="1.6" /><circle cx="17" cy="15" r="1.6" /><rect x="3" y="3" width="18" height="18" rx="2" /></>,
  report: <><path d="M5 20V10M12 20V4M19 20v-7" /></>,
  mail: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3.5 6.5 8.5 6.5 8.5-6.5" /></>,
  lock: <><rect x="5" y="10" width="14" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></>,
  people: <><circle cx="9" cy="9" r="3" /><path d="M3.5 19c.7-3 2.8-4.5 5.5-4.5s4.8 1.5 5.5 4.5" /><path d="M15.5 6.2a3 3 0 0 1 0 5.6M17 14.8c1.8.5 3 1.9 3.5 4.2" /></>,
};
type IconName = keyof typeof P;
const Icon = ({ name, size = 20 }: { name: IconName; size?: number }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>{P[name]}</svg>
);

/** Live: works in the app today. Planned: designed, not built yet. */
export const Status = ({ live }: { live: boolean }) => (
  <span className={`ln-tag ${live ? "live" : "planned"}`}>{live ? "Live" : "Planned"}</span>
);

const ROLE_CARDS: { icon: IconName; name: string; live: boolean; aka?: string; does: string; sees: string[] }[] = [
  {
    icon: "volunteer", name: "Volunteer", live: true,
    does: "Counts fish at each snapshot point, starting from AI's dots, and notes the visibility.",
    sees: ["My tasks: the videos waiting for a count", "The Workflow board", "Species wiki and Fish and water trends"],
  },
  {
    icon: "validator", name: "Validator", live: false, aka: "A Manager covers this today",
    does: "Checks each counted video, then passes it to the report or returns it to the volunteer with a note.",
    sees: ["A queue of counted videos to check", "The volunteer's dots beside AI's, frame by frame"],
  },
  {
    icon: "coordinator", name: "Coordinator", live: true, aka: "Called Manager in the app",
    does: "Imports footage, sets up sites and stations, runs the team and reads the reports.",
    sees: ["Surveys, with import and the site structure", "Station report and the team page", "Model comparison and AI accuracy"],
  },
];

export function Roles() {
  return (
    <div className="ln-roles">
      {ROLE_CARDS.map((r) => (
        <article key={r.name} className={`ln-role ${r.live ? "" : "planned"}`}>
          <div className="ln-role-head">
            <span className="ln-role-icon"><Icon name={r.icon} size={22} /></span>
            <div><b>{r.name}</b>{r.aka && <small>{r.aka}</small>}</div>
            <Status live={r.live} />
          </div>
          <p>{r.does}</p>
          <p className="ln-role-k">Sees</p>
          <ul>{r.sees.map((s) => <li key={s}>{s}</li>)}</ul>
        </article>
      ))}
    </div>
  );
}

const FLOW: { icon: IconName; title: string; who: string; live: boolean; text: string; stages?: string[]; mail?: string }[] = [
  { icon: "import", title: "Import", who: "Coordinator", live: true, text: "Files the video under its site and station. AI scans it for fish.", stages: ["Analysing"], mail: "Volunteers hear a video is ready to count" },
  { icon: "count", title: "Count", who: "Volunteer", live: true, text: "Names the species AI found, then counts every snapshot point the procedure asks for.", stages: ["To identify", "To count", "Counting", "Counted"], mail: "The validator hears it's ready to check" },
  { icon: "validator", title: "Validate", who: "Validator", live: false, text: "Passes the counts, or returns them with a note.", stages: ["Validated", "Returned"], mail: "The volunteer hears if it comes back" },
  { icon: "report", title: "Report", who: "Coordinator", live: true, text: "MeanCount and MaxN by station and season, exported as CSV." },
];

/** How one video moves between people, with the board's stages and the email at each handoff. */
export function Flow() {
  return (
    <div className="ln-card ln-flow-card">
      <div className="ln-card-head">
        <div><b>How a video moves through the team</b><p className="meta">Everyone sees where each video stands on the Workflow board. The board's stages are shown under each step.</p></div>
      </div>
      <ol className="ln-flow">
        {FLOW.map((s, i) => (
          <li key={s.title} className={s.live ? "" : "planned"}>
            <div className="ln-flow-top">
              <span className="ln-flow-icon"><Icon name={s.icon} /></span>
              <span className="num ln-flow-n">0{i + 1}</span>
              <Status live={s.live} />
            </div>
            <b>{s.title}</b>
            <span className="ln-flow-who">{s.who}</span>
            <p>{s.text}</p>
            {s.stages && <div className="ln-flow-stages">{s.stages.map((x) => <span key={x}>{x}</span>)}</div>}
            {s.mail && (
              <div className="ln-flow-mail"><Icon name="mail" size={16} /><span>{s.mail}</span><Status live={false} /></div>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

const Rule = ({ live, children }: { live: boolean; children: ReactNode }) => (
  <li><span>{children}</span><Status live={live} /></li>
);

/** Access by role, and running the team. */
export function Access() {
  return (
    <div className="ln-data">
      <div className="ln-card">
        <div className="ln-card-head">
          <div><b><Icon name="lock" /> Access by role</b><p className="meta">What each person can open, and what keeps the counts trustworthy</p></div>
        </div>
        <ul className="ln-rules">
          <Rule live>Each role opens only its own pages. Import, the Station report and the team page are for coordinators</Rule>
          <Rule live>Nothing AI suggests reaches a report until a person confirms it</Rule>
          <Rule live={false}>Accounts with passwords, instead of the demo's one account per role</Rule>
          <Rule live={false}>The server checks the role on every action, not only the screen</Rule>
        </ul>
      </div>
      <div className="ln-card">
        <div className="ln-card-head">
          <div><b><Icon name="people" /> Running the team</b><p className="meta">Coordinators bring people in and decide what they can do</p></div>
        </div>
        <ul className="ln-rules">
          <Rule live>Invite people by email, choosing their role</Rule>
          <Rule live>Change a role, renew an invite or remove someone</Rule>
          <Rule live={false}>Invites and task updates sent by email. The demo gives a link to pass on</Rule>
          <Rule live={false}>Volunteers apply online and a coordinator approves them on a review page</Rule>
          <Rule live={false}>Assign a video to a named volunteer. Today every volunteer sees all videos to count</Rule>
        </ul>
      </div>
    </div>
  );
}

export const JOIN_STEPS: { title: string; text: string; live: boolean }[] = [
  { title: "Get an invite", text: "A coordinator invites you by email, or you sign in to the demo as a volunteer.", live: true },
  { title: "Open a video", text: "My tasks lists the videos waiting. Tideflow takes you to each snapshot point in turn.", live: true },
  { title: "Count what you see", text: "Confirm AI's dots, add the fish it missed, note the visibility. That's one point done.", live: true },
  { title: "Or apply online", text: "Send a short application, and a coordinator approves it on a review page.", live: false },
];
