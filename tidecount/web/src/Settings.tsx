import { FormEvent, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Avatar, ROLES, useSession, useUser } from "./session";

const AVATAR_SIZE = 128;

/** Crop to a small square, so the photo fits in browser storage. */
function toAvatar(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      const side = Math.min(image.width, image.height);
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = AVATAR_SIZE;
      canvas.getContext("2d")!.drawImage(image, (image.width - side) / 2, (image.height - side) / 2, side, side, 0, 0, AVATAR_SIZE, AVATAR_SIZE);
      URL.revokeObjectURL(url);
      resolve(canvas.toDataURL("image/jpeg", 0.85));
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("That file isn't an image this browser can read."));
    };
    image.src = url;
  });
}

function Profile() {
  const user = useUser();
  const { updateProfile } = useSession();
  const [name, setName] = useState(user.name);
  const [message, setMessage] = useState("");
  const input = useRef<HTMLInputElement>(null);

  const save = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return setMessage("Enter a name.");
    updateProfile({ name: name.trim() });
    setMessage("Saved in this browser.");
  };

  const pick = async (file?: File) => {
    if (!file) return;
    try {
      updateProfile({ avatar: await toAvatar(file) });
      setMessage("Saved in this browser.");
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  return (
    <form className="panel panel-pad settings-card" onSubmit={save}>
      <h2>Profile</h2>
      <div className="row" style={{ gap: 12 }}>
        <Avatar user={{ name: name || user.name, avatar: user.avatar }} size={64} />
        <button className="btn" type="button" onClick={() => input.current?.click()}>Change photo</button>
        {user.avatar && <button className="btn quiet" type="button" onClick={() => updateProfile({ avatar: "" })}>Remove</button>}
        <input
          ref={input}
          type="file"
          accept="image/*"
          hidden
          aria-label="Profile photo"
          onChange={(e) => {
            pick(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </div>
      <label className="field">Display name
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="field">Email
        <input value={user.email} readOnly />
      </label>
      <div className="stack" style={{ gap: 4 }}>
        <span className="meta">Role</span>
        <div className="row"><span className="pill accent">{ROLES[user.role].label}</span></div>
        <span className="meta">{ROLES[user.role].about} A manager changes roles.</span>
      </div>
      <div className="row">
        <button className="btn go" type="submit">Save</button>
        {message && <span className="meta" role="status">{message}</span>}
      </div>
    </form>
  );
}

function Password() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!current || !next) return setMessage("Fill in every field.");
    if (next.length < 8) return setMessage("Use at least 8 characters.");
    if (next !== confirm) return setMessage("The new passwords don't match.");
    setCurrent("");
    setNext("");
    setConfirm("");
    setMessage("Demo only: no password was changed.");
  };

  return (
    <form className="panel panel-pad settings-card" onSubmit={submit}>
      <h2>Change password</h2>
      <label className="field">Current password
        <input type="password" autoComplete="off" value={current} onChange={(e) => setCurrent(e.target.value)} />
      </label>
      <label className="field">New password
        <input type="password" autoComplete="off" value={next} onChange={(e) => setNext(e.target.value)} />
      </label>
      <label className="field">Confirm new password
        <input type="password" autoComplete="off" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      </label>
      <div className="row">
        <button className="btn go" type="submit">Update password</button>
        {message && <span className="meta" role="status">{message}</span>}
      </div>
    </form>
  );
}

export function Settings() {
  const { signOut } = useSession();
  const navigate = useNavigate();
  // Go to sign-in first: the next person starts on their own home, not on this page.
  const leave = () => {
    navigate("/login", { replace: true });
    signOut();
  };
  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="pagehead">
        <div>
          <h1>Settings</h1>
          <p className="lede">Your profile and sign-in.</p>
        </div>
        <button className="btn" onClick={leave}>Sign out</button>
      </div>
      <div className="settings-grid">
        <Profile />
        <Password />
      </div>
    </div>
  );
}
