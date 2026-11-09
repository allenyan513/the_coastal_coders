/*
 * What the front page's "Join as a volunteer" banner needs: the Live and Planned tag, and the steps
 * for joining. Each says whether it works in the app today ("Live") or is designed but not built
 * ("Planned"), because judges can open the app and check. What is live, as of main on 2026-11-08:
 * team invites with a role (Team.tsx) and the volunteer's My tasks home (main.tsx Home). Invites and
 * the team live in the browser, and no email is sent, so email and online applications are planned.
 */

/** Live: works in the app today. Planned: designed, not built yet. */
export const Status = ({ live }: { live: boolean }) => (
  <span className={`ln-tag ${live ? "live" : "planned"}`}>{live ? "Live" : "Planned"}</span>
);

export const JOIN_STEPS: { title: string; text: string; live: boolean }[] = [
  { title: "Get an invite", text: "A coordinator invites you by email, or you sign in to the demo as a volunteer.", live: true },
  { title: "Open a video", text: "My tasks lists the videos waiting. Tideflow takes you to each snapshot point in turn.", live: true },
  { title: "Count what you see", text: "Confirm AI's dots, add the fish it missed, note the visibility. That's one point done.", live: true },
  { title: "Or apply online", text: "Send a short application, and a coordinator approves it on a review page.", live: false },
];
