import { ROLES, useUser } from "./session";

// Sample names. The server has no accounts yet, so this list is for the demo only.
const OTHERS = [
  { name: "Volunteer A", role: "volunteer" as const, status: "Counting" },
  { name: "Volunteer B", role: "volunteer" as const, status: "Invited" },
  { name: "Volunteer C", role: "volunteer" as const, status: "Active" },
  { name: "Manager B", role: "manager" as const, status: "Active" },
];

export function Team() {
  const user = useUser();
  const people = [{ name: user.name, role: user.role, status: "You" }, ...OTHERS];
  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="pagehead">
        <div>
          <h1>Team</h1>
          <p className="lede">Who works in this Tideflow. Volunteers count; managers validate, coordinate and report.</p>
        </div>
        <button className="btn primary" disabled title="Invites aren't connected in this demo">Invite</button>
      </div>
      <div className="panel">
        <table className="cards">
          <thead><tr><th>Name</th><th>Role</th><th>Status</th></tr></thead>
          <tbody>
            {people.map((p) => (
              <tr key={p.name}>
                <td>{p.name}</td>
                <td data-label="Role">{ROLES[p.role].label}</td>
                <td data-label="Status">{p.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="meta">Sample people for the demo. Invites and role changes aren't connected yet.</p>
    </div>
  );
}
