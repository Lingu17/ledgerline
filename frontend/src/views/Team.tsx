import { Fragment, useState } from "react";
import { del, get, post, type Role } from "../api";
import { ROLE_HELP, ROLE_LABEL, useAuth } from "../auth";
import { Card, Empty, ErrorNote, Field, Loading, Modal, useAction, useLoad } from "../components/ui";
import { day, when } from "../format";

interface TeamData {
  members: { user_id: string; email: string; name: string; role: Role; created_at: string }[];
  invitations: { id: string; email: string; role: Role; created_at: string; expires_at: string }[];
  you: string;
  role: Role;
}

export function Team() {
  const t = useLoad(() => get<TeamData>("/team"), []);
  const { can } = useAuth();
  const { run, busy } = useAction();
  const [inviting, setInviting] = useState(false);
  const [removing, setRemoving] = useState<TeamData["members"][number] | null>(null);
  const [resetFor, setResetFor] = useState<TeamData["members"][number] | null>(null);
  const owner = can("owner");
  if (t.error) return <ErrorNote error={t.error} onRetry={t.reload} />;
  if (!t.data) return <div className="card"><Loading /></div>;
  const d = t.data;
  return (
    <div className="stack">
      <Card title="Members" pad={false} actions={owner && <button className="btn primary small" onClick={() => setInviting(true)}>Invite member</button>}>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Name</th><th>Role</th><th className="hide-sm">Member since</th><th /></tr></thead>
            <tbody>
              {d.members.map((m) => (
                <tr key={m.user_id}>
                  <td><div className="primary-text">{m.name}{m.user_id === d.you && <span className="muted"> (you)</span>}</div><div className="secondary">{m.email}</div></td>
                  <td>
                    {owner ? (
                      <select aria-label={`Role for ${m.email}`} value={m.role} disabled={!!busy}
                        onChange={(e) => run("role", () => post(`/team/members/${m.user_id}`, { role: e.target.value }, "PUT"), `${m.email} is now ${e.target.value}`)}>
                        {(["owner", "operator", "viewer"] as Role[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                      </select>
                    ) : ROLE_LABEL[m.role]}
                  </td>
                  <td className="hide-sm small">{day(m.created_at)}</td>
                  <td className="num nowrap">{owner && m.user_id !== d.you && <>
                    <button className="btn small" onClick={() => setResetFor(m)}>Reset link…</button>{" "}
                    <button className="btn small danger" onClick={() => setRemoving(m)}>Remove</button>
                  </>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {owner && (
        <Card title="Open invitations" pad={false}>
          {d.invitations.length === 0 ? <Empty title="No open invitations">Money leaving needs a second person, so invite at least one Operator.</Empty> : (
            <table>
              <thead><tr><th>Email</th><th>Role</th><th className="hide-sm">Expires</th><th /></tr></thead>
              <tbody>
                {d.invitations.map((i) => (
                  <tr key={i.id}>
                    <td>{i.email}</td><td>{ROLE_LABEL[i.role]}</td><td className="hide-sm small">{when(i.expires_at)}</td>
                    <td className="num"><button className="btn small" disabled={!!busy} onClick={() => run("rev", () => del(`/team/invitations/${i.id}`), "Invitation revoked")}>Revoke</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}

      <Card title="Roles">
        <dl className="kv small">
          {(["owner", "operator", "viewer"] as Role[]).map((r) => (<Fragment key={r}><dt>{ROLE_LABEL[r]}</dt><dd>{ROLE_HELP[r]}</dd></Fragment>))}
        </dl>
        <p className="small muted" style={{ marginBottom: 0 }}>Whoever proposes a refund cannot approve it. Any operator can pause money-out; only an owner can resume it.</p>
      </Card>

      {inviting && <InviteModal onClose={() => setInviting(false)} />}
      {resetFor && <ResetLinkModal member={resetFor} onClose={() => setResetFor(null)} />}
      {removing && (
        <Modal title="Remove member" onClose={() => setRemoving(null)}>
          <p style={{ marginTop: 0 }}>{removing.name} ({removing.email}) will lose access to this organization immediately. Their past actions stay in the audit trail.</p>
          <div className="form-actions">
            <button className="btn" onClick={() => setRemoving(null)}>Cancel</button>
            <button className="btn danger solid" disabled={!!busy} onClick={async () => {
              await run("rm", () => del(`/team/members/${removing.user_id}`), "Member removed");
              setRemoving(null);
            }}>Remove</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function InviteModal({ onClose }: { onClose: () => void }) {
  const { run, busy } = useAction();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("operator");
  const [link, setLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  return (
    <Modal title="Invite a team member" onClose={onClose}>
      {link ? (
        <div className="stack" style={{ gap: 12 }}>
          <p style={{ margin: 0 }}>Send this one-time link to <b>{email}</b>. It expires in 3 days. Ledgerline does not send email in this build.</p>
          <input type="text" readOnly value={link} aria-label="Invitation link" className="mono" onFocus={(e) => e.target.select()} />
          <div className="form-actions">
            <button className="btn" onClick={() => navigator.clipboard?.writeText(link).then(() => setCopied(true))}>{copied ? "Copied" : "Copy link"}</button>
            <button className="btn primary" onClick={onClose}>Done</button>
          </div>
        </div>
      ) : (
        <form onSubmit={async (e) => {
          e.preventDefault();
          const r = await run("inv", () => post<{ invite_path: string }>("/team/invitations", { email, role }));
          if (r) setLink(window.location.origin + r.invite_path);
        }}>
          <div className="form-grid">
            <Field id="iv-email" label="Email" wide><input id="iv-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
            <Field id="iv-role" label="Role" wide hint={ROLE_HELP[role]}>
              <select id="iv-role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
                <option value="operator">Operator</option><option value="viewer">Viewer</option><option value="owner">Owner</option>
              </select>
            </Field>
          </div>
          <div className="form-actions"><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!!busy}>Create invitation</button></div>
        </form>
      )}
    </Modal>
  );
}

/** Ledgerline sends no email, so a member who forgot their password gets a one-hour link from an Owner, shown once. */
function ResetLinkModal({ member, onClose }: { member: TeamData["members"][number]; onClose: () => void }) {
  const { run, busy } = useAction();
  const [link, setLink] = useState<{ url: string; expires_at: string } | null>(null);
  return (
    <Modal title={`Reset link for ${member.name}`} onClose={onClose}>
      {!link ? (
        <>
          <p style={{ marginTop: 0 }}>
            This makes a single-use link, valid for one hour, that lets {member.email} choose a new password. Every place they are
            signed in is signed out. Give it to them directly; anyone holding it can set the password. It is recorded in the
            organization's changes.
          </p>
          <div className="form-actions">
            <button className="btn" onClick={onClose}>Cancel</button>
            <button className="btn primary" disabled={!!busy} onClick={async () => {
              const r = await run("reset", () => post<{ path: string; expires_at: string }>(`/team/members/${member.user_id}/reset-link`), "Reset link created");
              if (r) setLink({ url: `${window.location.origin}/${r.path}`, expires_at: r.expires_at });
            }}>Create link</button>
          </div>
        </>
      ) : (
        <>
          <Field id="reset-url" label="Reset link" hint={`Valid until ${when(link.expires_at)}. It is shown only now.`}>
            <input id="reset-url" readOnly value={link.url} onFocus={(e) => e.currentTarget.select()} />
          </Field>
          <div className="form-actions">
            <button className="btn" onClick={() => navigator.clipboard?.writeText(link.url)}>Copy</button>
            <button className="btn primary" onClick={onClose}>Done</button>
          </div>
        </>
      )}
    </Modal>
  );
}
