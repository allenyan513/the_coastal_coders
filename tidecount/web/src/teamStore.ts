import { useSyncExternalStore } from "react";
import type { Role } from "./session";

/**
 * The people in this Tideflow besides the signed-in person, and the invites still open.
 * Like the survey structure it lives in this browser, because the server has no accounts yet.
 */
export type Member = { id: string; name: string; email: string; role: Role; status: "active" | "invited"; since: string };

const KEY = "tideflow-team-v1";
const today = () => new Date().toISOString().slice(0, 10);

/** Sample people for the demo. */
function seed(): Member[] {
  const member = (id: string, name: string, email: string, role: Role, status: Member["status"], since: string): Member => ({ id, name, email, role, status, since });
  return [
    member("m-a", "Volunteer A", "volunteer.a@example.org", "volunteer", "active", "2026-09-14"),
    member("m-b", "Volunteer B", "volunteer.b@example.org", "volunteer", "invited", "2026-11-02"),
    member("m-c", "Volunteer C", "volunteer.c@example.org", "volunteer", "active", "2026-10-03"),
    member("m-d", "Manager B", "manager.b@example.org", "manager", "active", "2026-08-21"),
  ];
}

function read(): Member[] {
  try {
    const stored = localStorage.getItem(KEY);
    return stored ? JSON.parse(stored) : seed();
  } catch {
    return seed();
  }
}

let members = read();
const listeners = new Set<() => void>();

function commit(next: Member[]) {
  members = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // Private windows can refuse storage. Changes then last until the page reloads.
  }
  listeners.forEach((listen) => listen());
}

export function useTeam() {
  return useSyncExternalStore((listen) => {
    listeners.add(listen);
    return () => listeners.delete(listen);
  }, () => members);
}

export const findMember = (id: string | null) => members.find((m) => m.id === id);

/** A readable name until the person signs in and sets their own: jane.doe@x.org becomes Jane Doe. */
const nameFrom = (email: string) => email.split("@")[0].split(/[._-]+/).filter(Boolean).map((w) => w[0].toUpperCase() + w.slice(1)).join(" ") || email;

export function invite(emails: string[], role: Role) {
  const added = emails.map((email): Member => ({ id: `m-${Math.random().toString(36).slice(2, 10)}`, name: nameFrom(email), email, role, status: "invited", since: today() }));
  commit([...members, ...added]);
  return added;
}

export const setRole = (id: string, role: Role) => commit(members.map((m) => (m.id === id ? { ...m, role } : m)));
export const resend = (id: string) => commit(members.map((m) => (m.id === id ? { ...m, since: today() } : m)));
export const removeMember = (id: string) => commit(members.filter((m) => m.id !== id));
export const acceptInvite = (id: string) => commit(members.map((m) => (m.id === id ? { ...m, status: "active", since: today() } : m)));
export const resetTeam = () => commit(seed());

export const inviteLink = (m: Member) => `${window.location.origin}/login?invite=${m.id}`;
