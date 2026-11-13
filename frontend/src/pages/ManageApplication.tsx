import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Modal } from "../components/Modal";
import { Badge } from "../components/Badge";
import { Switch } from "../components/Switch";
import { CopyableId } from "../components/CopyableId";
import { PasswordInput } from "../components/PasswordInput";
import { LinkListInput } from "../components/LinkListInput";
import { CloseIcon } from "../components/Icons";
import { useConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/ToastProvider";
import { useFocusTrap } from "../components/useFocusTrap";
import { teamSummary, useTeams } from "../components/TeamPicker";
import { AccessGrant, AccessReview, api, ApiError, AppUser, Client, Pool, Team, UserPage, UserRoleRow } from "../api";
import {
  appendLine,
  CLIENT_TYPE_LABELS,
  describeDuration,
  DurationUnit,
  durationSeconds,
  EmbedOriginsField,
  GRANT_LABELS,
  PostLogoutUrisField,
  QuickRedirects,
  SessionTimeoutField,
  splitDuration,
} from "./applicationFields";

type Section = "general" | "signin" | "people" | "roles" | "appearance" | "advanced";

const SECTION_LABELS: Record<Section, string> = {
  general: "General",
  signin: "Sign-in & signup",
  people: "People & access",
  roles: "Roles",
  appearance: "Appearance",
  advanced: "Advanced",
};

const APPLICATION_TYPE_LABELS: Record<string, string> = {
  web: "Website or backend app",
  native: "Mobile app, CLI tool, or AI assistant",
  service: "Machine-to-machine service",
};

// Everything edited through the save bar. On/off settings (signup, restricted
// access, roles) and the login group take effect straight away instead.
interface Draft {
  name: string;
  grants: string[];
  redirectUris: string;
  ttlEnabled: boolean;
  ttlValue: string;
  ttlUnit: DurationUnit;
  postLogoutUris: string;
  logoUrl: string;
  brandColor: string;
  embedOrigins: string;
  scope: string;
  thumbprint: string;
  backchannelUri: string;
  signupTeamId: string;
  rolesClaim: string;
}

function draftFrom(client: Client): Draft {
  const ttl = splitDuration(client.session_ttl_seconds);
  return {
    name: client.client_name ?? "",
    grants: client.grant_types,
    redirectUris: client.redirect_uris.join("\n"),
    ttlEnabled: client.session_ttl_seconds > 0,
    ttlValue: ttl.value,
    ttlUnit: ttl.unit,
    postLogoutUris: client.post_logout_redirect_uris.join("\n"),
    logoUrl: client.logo_url ?? "",
    brandColor: client.brand_color ?? "",
    embedOrigins: client.embed_origins.join("\n"),
    scope: client.allowed_scope,
    thumbprint: client.mtls_cert_thumbprint ?? "",
    backchannelUri: client.backchannel_logout_uri ?? "",
    signupTeamId: client.signup_team_id ?? "",
    rolesClaim: client.roles_claim || "roles",
  };
}

const ttlSeconds = (d: Draft) => (d.ttlEnabled ? durationSeconds(d.ttlValue, d.ttlUnit) : 0);
const sameSet = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));

/** Which sections hold unsaved edits -- each gets a dot in the section list. */
function changedSections(draft: Draft, client: Client): Set<Section> {
  const saved = draftFrom(client);
  const changed = new Set<Section>();
  if (draft.name !== saved.name || !sameSet(draft.grants, saved.grants)) changed.add("general");
  if (
    draft.redirectUris !== saved.redirectUris ||
    ttlSeconds(draft) !== client.session_ttl_seconds ||
    draft.postLogoutUris !== saved.postLogoutUris ||
    draft.backchannelUri !== saved.backchannelUri ||
    draft.signupTeamId !== saved.signupTeamId
  )
    changed.add("signin");
  if (draft.rolesClaim !== saved.rolesClaim) changed.add("roles");
  if (draft.logoUrl !== saved.logoUrl || draft.brandColor !== saved.brandColor) changed.add("appearance");
  if (draft.scope !== saved.scope || draft.thumbprint !== saved.thumbprint || draft.embedOrigins !== saved.embedOrigins)
    changed.add("advanced");
  return changed;
}

export function displayName(client: Client) {
  return client.client_name || "Unnamed application";
}

export function ManageApplication({
  client,
  allClients,
  onClose,
  onUpdated,
  onChanged,
  onToggleEnabled,
  onDelete,
}: {
  client: Client;
  allClients: Client[];
  onClose: () => void;
  /** Replaces this application in the list with what the server returned. */
  onUpdated: (client: Client) => void;
  /** Reloads the whole list, for changes that touch other applications too. */
  onChanged: () => Promise<unknown>;
  onToggleEnabled: () => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const editable = client.registration_method !== "cimd";
  const [draft, setDraft] = useState<Draft>(() => draftFrom(client));
  const [section, setSection] = useState<Section>("general");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const resetAfterReload = useRef(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const { confirm, dialog } = useConfirmDialog();
  const { show } = useToast();
  useFocusTrap(panelRef);

  // After a save the list updates; start again from what the server stored
  // (it trims URLs, normalizes origins, upper-cases the thumbprint...).
  useEffect(() => {
    if (resetAfterReload.current) {
      resetAfterReload.current = false;
      setDraft(draftFrom(client));
    }
  }, [client]);

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const changed = useMemo(() => changedSections(draft, client), [draft, client]);
  const dirty = changed.size > 0;

  const signsPeopleIn = draft.grants.includes("authorization_code");
  const sections: Section[] = editable
    ? ["general", ...(signsPeopleIn ? (["signin", "people", "roles", "appearance"] as Section[]) : []), "advanced"]
    : ["general"];
  const current = sections.includes(section) ? section : "general";

  const requestClose = () => {
    if (!dirty) return onClose();
    confirm({
      title: "Discard unsaved changes?",
      description: `Your edits to ${[...changed].map((s) => SECTION_LABELS[s]).join(", ")} haven't been saved.`,
      confirmLabel: "Discard",
      danger: true,
      onConfirm: onClose,
    });
  };

  // Escape closes the panel, but not while a dialog on top of it has focus.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && panelRef.current?.contains(document.activeElement)) requestClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  const save = async () => {
    const saved = draftFrom(client);
    setSaving(true);
    setSaveError(null);
    try {
      // One request for every field, whichever section it's in.
      const updated = await api.patch<Client>(`/clients/${client.client_id}`, {
        client_name: draft.name,
        redirect_uris: draft.redirectUris,
        scope: draft.scope,
        session_ttl_seconds: ttlSeconds(draft),
        post_logout_redirect_uris: draft.postLogoutUris,
        embed_origins: draft.embedOrigins,
        logo_url: draft.logoUrl,
        brand_color: draft.brandColor,
        mtls_thumbprint: draft.thumbprint,
        backchannel_logout_uri: draft.backchannelUri,
        signup_team_id: draft.signupTeamId,
        roles_claim: draft.rolesClaim,
        ...(sameSet(draft.grants, saved.grants) ? {} : { grant_types: draft.grants }),
      });
      resetAfterReload.current = true;
      onUpdated(updated);
      show("Changes saved");
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "Couldn't save your changes");
    } finally {
      setSaving(false);
    }
  };

  // On/off settings apply as soon as they're flipped.
  const [flipping, setFlipping] = useState<string | null>(null);
  const flip = async (endpoint: string, done: string) => {
    setFlipping(endpoint);
    try {
      onUpdated(await api.post<Client>(`/clients/${client.client_id}/${endpoint}`));
      show(done);
    } catch (err) {
      show(err instanceof ApiError ? err.message : "Couldn't change that setting");
    } finally {
      setFlipping(null);
    }
  };

  return (
    <>
      <div
        className="sheet-backdrop"
        onClick={(e) => {
          if (e.target === e.currentTarget) requestClose();
        }}
      >
        <div className="sheet" role="dialog" aria-modal="true" aria-label={`Manage ${displayName(client)}`} ref={panelRef}>
          <header className="sheet__header">
            <div className="sheet__title-row">
              <div style={{ minWidth: 0 }}>
                <h2 className="sheet__title">{displayName(client)}</h2>
                <CopyableId value={client.client_id} max={48} />
              </div>
              <Badge variant={client.enabled ? "success" : "neutral"}>{client.enabled ? "Active" : "Disabled"}</Badge>
              <button type="button" className="modal__close" aria-label="Close" onClick={requestClose}>
                <CloseIcon width={18} height={18} />
              </button>
            </div>
            <Summary client={client} allClients={allClients} onOpen={(s) => sections.includes(s) && setSection(s)} />
          </header>

          <div className="sheet__layout">
            <nav className="sheet__nav" aria-label="Settings sections">
              {sections.map((s) => (
                <button
                  key={s}
                  type="button"
                  className={`sheet__nav-item${s === current ? " is-active" : ""}`}
                  aria-current={s === current ? "page" : undefined}
                  onClick={() => setSection(s)}
                >
                  {SECTION_LABELS[s]}
                  {changed.has(s) && <span className="sheet__nav-dot" aria-label="unsaved changes" />}
                </button>
              ))}
            </nav>

            <div className="sheet__body">
              {!editable && (
                <div className="alert">
                  This application registered itself from a metadata document on its own website, so its
                  settings come from there. You can still disable or remove it from the list.
                </div>
              )}

              {current === "general" && (
                <GeneralSection client={client} draft={draft} set={set} editable={editable} />
              )}
              {current === "signin" && (
                <SignInSection client={client} draft={draft} set={set} flip={flip} flipping={flipping} confirm={confirm} />
              )}
              {current === "people" && (
                <PeopleSection client={client} allClients={allClients} flip={flip} flipping={flipping} onChanged={onChanged} confirm={confirm} />
              )}
              {current === "roles" && <RolesSection client={client} draft={draft} set={set} flip={flip} flipping={flipping} />}
              {current === "appearance" && <AppearanceSection draft={draft} set={set} />}
              {current === "advanced" && (
                <AdvancedSection
                  client={client}
                  draft={draft}
                  set={set}
                  onDisable={() =>
                    confirm({
                      title: `${client.enabled ? "Disable" : "Re-enable"} ${displayName(client)}?`,
                      description: client.enabled
                        ? "This immediately blocks anyone from logging in or refreshing a token with this application, without deleting it or losing its history. You can re-enable it any time."
                        : "This lets the application accept logins and token refreshes again.",
                      danger: client.enabled,
                      confirmLabel: client.enabled ? "Disable" : "Re-enable",
                      onConfirm: onToggleEnabled,
                    })
                  }
                  onDelete={() =>
                    confirm({
                      title: `Remove ${displayName(client)}?`,
                      description:
                        "Permanently removes this application and the accounts created through it, and immediately blocks all logins and token refreshes. This cannot be undone.",
                      danger: true,
                      confirmLabel: "Remove",
                      onConfirm: onDelete,
                    })
                  }
                />
              )}
            </div>
          </div>

          {(dirty || saveError) && (
            <footer className="sheet__savebar" role="region" aria-label="Unsaved changes">
              <span className={saveError ? "sheet__savebar-error" : "sheet__savebar-text"}>
                {saveError ?? "You have unsaved changes"}
              </span>
              <button
                type="button"
                className="btn btn--ghost"
                disabled={saving}
                onClick={() => {
                  setDraft(draftFrom(client));
                  setSaveError(null);
                }}
              >
                Discard
              </button>
              <button type="button" className="btn btn--primary" disabled={saving || !dirty} onClick={save}>
                {saving ? "Saving…" : "Save changes"}
              </button>
            </footer>
          )}
        </div>
      </div>
      {dialog}
    </>
  );
}

/** What this application does right now, in plain words. Each line opens the
 * section that changes it. */
function Summary({
  client,
  allClients,
  onOpen,
}: {
  client: Client;
  allClients: Client[];
  onOpen: (section: Section) => void;
}) {
  const signsPeopleIn = client.grant_types.includes("authorization_code");
  const facts: { text: string; section: Section; tone?: "warn" }[] = [];

  if (!client.enabled) facts.push({ text: "Disabled: no one can log in", section: "advanced", tone: "warn" });
  if (!signsPeopleIn) {
    facts.push({ text: "Server-to-server only, no one logs in", section: "general" });
  } else {
    facts.push(
      client.allow_signup
        ? { text: "Anyone can create an account", section: "signin" }
        : { text: "Only admins can add accounts", section: "signin" },
    );
    facts.push(
      client.require_verified_email
        ? { text: "Email must be verified first", section: "signin" }
        : { text: "Unverified emails can get in", section: "signin", tone: "warn" },
    );
    const others = allClients
      .filter((c) => c.pool_name && c.pool_name === client.pool_name && c.id !== client.id)
      .map(displayName);
    facts.push({
      text: !client.pool_name
        ? "Has its own accounts"
        : others.length
          ? `Shares accounts with ${others.join(", ")}`
          : `In login group ${client.pool_name}, no other apps yet`,
      section: "people",
    });
    if (client.restrict_access) facts.push({ text: "Only people you choose can log in", section: "people" });
    facts.push({
      text: client.session_ttl_seconds
        ? `Asks people to log in again every ${describeDuration(client.session_ttl_seconds)}`
        : "No sign-in time limit of its own",
      section: "signin",
    });
  }

  return (
    <ul className="sheet__summary">
      {facts.map((f) => (
        <li key={f.text}>
          <button type="button" className={`sheet__fact${f.tone === "warn" ? " sheet__fact--warn" : ""}`} onClick={() => onOpen(f.section)}>
            {f.text}
          </button>
        </li>
      ))}
    </ul>
  );
}

/** One setting: what it does on the left, its control on the right, and
 * anything it reveals underneath. */
function SettingRow({
  title,
  hint,
  control,
  children,
}: {
  title: ReactNode;
  hint?: ReactNode;
  control?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="setting">
      <div className="setting__main">
        <div className="setting__text">
          <div className="setting__title">{title}</div>
          {hint && <div className="setting__hint">{hint}</div>}
        </div>
        {control && <div className="setting__control">{control}</div>}
      </div>
      {children && <div className="setting__extra">{children}</div>}
    </div>
  );
}

function SectionHeading({ title, lead }: { title: string; lead?: ReactNode }) {
  return (
    <div className="sheet__section-heading">
      <h3>{title}</h3>
      {lead && <p>{lead}</p>}
    </div>
  );
}

type SetDraft = <K extends keyof Draft>(key: K, value: Draft[K]) => void;
type Flip = (endpoint: string, done: string) => Promise<void>;

function GeneralSection({
  client,
  draft,
  set,
  editable,
}: {
  client: Client;
  draft: Draft;
  set: SetDraft;
  editable: boolean;
}) {
  // A public app has no secret to prove who it is, so it can't talk to the
  // server on its own (the API refuses this too).
  const grantOptions = Object.keys(GRANT_LABELS).filter(
    (g) => g !== "client_credentials" || (client.client_type === "confidential" && client.registration_method === "static"),
  );
  const toggleGrant = (g: string) =>
    set("grants", draft.grants.includes(g) ? draft.grants.filter((x) => x !== g) : [...draft.grants, g]);

  return (
    <>
      <SectionHeading title="General" />
      {editable && (
        <div className="field">
          <label htmlFor="manage-name">Name</label>
          <input id="manage-name" value={draft.name} onChange={(e) => set("name", e.target.value)} placeholder="Unnamed application" />
          <span className="field__hint">Shown on its login page and in this console.</span>
        </div>
      )}

      <SettingRow
        title="What kind of app it is"
        hint={
          <>
            {APPLICATION_TYPE_LABELS[client.application_type] ?? client.application_type}.{" "}
            {CLIENT_TYPE_LABELS[client.client_type] ?? client.client_type}. This is fixed once the app
            exists, because it decides whether it has a secret. To change it, add a new application.
          </>
        }
      />

      <div className="field" style={{ marginTop: 16 }}>
        <label>What it's allowed to do</label>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {grantOptions.map((g) => (
            <label key={g} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, fontWeight: 400 }}>
              <input
                type="checkbox"
                disabled={!editable || (g === "refresh_token" && !draft.grants.includes("authorization_code"))}
                checked={draft.grants.includes(g)}
                onChange={() => toggleGrant(g)}
              />
              {GRANT_LABELS[g]}
            </label>
          ))}
        </div>
        {draft.grants.length === 0 && <span className="field__hint field__hint--error">Choose at least one.</span>}
        {draft.grants.includes("authorization_code") && !client.grant_types.includes("authorization_code") && (
          <span className="field__hint">Add where people are sent back to after login under Sign-in &amp; signup.</span>
        )}
      </div>
    </>
  );
}

function SignInSection({
  client,
  draft,
  set,
  flip,
  flipping,
  confirm,
}: {
  client: Client;
  draft: Draft;
  set: SetDraft;
  flip: Flip;
  flipping: string | null;
  confirm: ReturnType<typeof useConfirmDialog>["confirm"];
}) {
  // Turning it on holds back everyone not yet verified, so say how many first.
  const toggleVerifiedEmail = async (on: boolean) => {
    if (!on) return flip("toggle-require-verified-email", "People can get in before verifying their email");
    const { count } = await api.get<{ count: number }>(`/clients/${client.client_id}/unverified-users`);
    if (count === 0) return flip("toggle-require-verified-email", "A verified email is now required");
    confirm({
      title: "Require a verified email?",
      description: `${count === 1 ? "1 person" : `${count} people`} who can log in to ${displayName(client)} haven't verified their email. Next time they try, they'll be asked to open the link we email them first. You can verify someone by hand on the Users page.`,
      confirmLabel: "Require it",
      onConfirm: () => flip("toggle-require-verified-email", "A verified email is now required"),
    });
  };

  return (
    <>
      <SectionHeading title="Sign-in & signup" />
      <SettingRow
        title="Require a verified email"
        hint={
          client.require_verified_email
            ? "On: after signing up or logging in, people who haven't confirmed their email see \"Check your email\" and carry on once they open the link."
            : "Off: people get in straight away; the verification email is only informational."
        }
        control={
          <Switch
            label="Require a verified email"
            checked={client.require_verified_email}
            disabled={flipping !== null}
            onChange={toggleVerifiedEmail}
          />
        }
      />
      <SettingRow
        title="Let people create their own account"
        hint={
          client.allow_signup
            ? client.pool_name
              ? `On: anyone can sign up from this app's login page. Their account works in every app in the ${client.pool_name} login group.`
              : "On: anyone can sign up from this app's login page."
            : "Off: the login page has no signup link. You add accounts under People & access, or on the Users page."
        }
        control={
          <Switch
            label="Let people create their own account"
            checked={client.allow_signup}
            disabled={flipping !== null}
            onChange={(on) => flip("toggle-signup", on ? "Signup turned on" : "Signup turned off")}
          />
        }
      />
      {client.allow_signup && client.roles_enabled && (
        <SettingRow
          title="Let people choose a role when they sign up"
          hint="Off: new accounts start with no role, and you assign one under Roles."
          control={
            <Switch
              label="Let people choose a role when they sign up"
              checked={client.allow_signup_role_selection}
              disabled={flipping !== null}
              onChange={(on) =>
                flip("toggle-signup-role-selection", on ? "Role choice added to signup" : "Role choice removed from signup")
              }
            />
          }
        />
      )}

      <div className="sheet__fields">
        <div className="field">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
            <label htmlFor="manage-redirects">
              Where people are sent back to after login
            </label>
            {client.application_type === "native" && (
              <QuickRedirects onAdd={(uri) => set("redirectUris", appendLine(draft.redirectUris, uri))} />
            )}
          </div>
          <LinkListInput
            id="manage-redirects"
            placeholder="https://yourapp.com/callback"
            value={draft.redirectUris}
            onChange={(v) => set("redirectUris", v)}
          />
        </div>
        <SessionTimeoutField
          enabled={draft.ttlEnabled}
          value={draft.ttlValue}
          unit={draft.ttlUnit}
          onChange={(on, v, u) => {
            set("ttlEnabled", on);
            set("ttlValue", v);
            set("ttlUnit", u);
          }}
        />
        <PostLogoutUrisField value={draft.postLogoutUris} onChange={(v) => set("postLogoutUris", v)} />
        {client.allow_signup && <SignupTeamField value={draft.signupTeamId} onChange={(v) => set("signupTeamId", v)} />}
        <div className="field">
          <label htmlFor="manage-backchannel">
            Back-channel logout URL <span className="field__hint">(optional)</span>
          </label>
          <input
            id="manage-backchannel"
            type="url"
            inputMode="url"
            placeholder="https://yourapp.com/auth/backchannel-logout"
            value={draft.backchannelUri}
            onChange={(e) => set("backchannelUri", e.target.value)}
          />
          <span className="field__hint">Your server is told when someone is signed out of this app. Other apps aren't affected.</span>
        </div>
      </div>
    </>
  );
}

function SignupTeamField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const teams = useTeams();
  if (!teams || teams.length === 0) return null;
  return (
    <div className="field">
      <label htmlFor="manage-signup-team">
        New signups join a team <span className="field__hint">(optional)</span>
      </label>
      <select id="manage-signup-team" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">No team</option>
        {teams.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
            {teamSummary(t) ? ` (${teamSummary(t)})` : ""}
          </option>
        ))}
      </select>
    </div>
  );
}

const OWN_ACCOUNTS = "";
const NEW_GROUP = "\u0000new";

function PeopleSection({
  client,
  allClients,
  flip,
  flipping,
  onChanged,
  confirm,
}: {
  client: Client;
  allClients: Client[];
  flip: Flip;
  flipping: string | null;
  onChanged: () => Promise<unknown>;
  confirm: ReturnType<typeof useConfirmDialog>["confirm"];
}) {
  const { show } = useToast();
  const [pools, setPools] = useState<Pool[]>([]);
  const [groupChoice, setGroupChoice] = useState(client.pool_name ?? OWN_ACCOUNTS);
  const [grants, setGrants] = useState<AccessGrant[] | null>(null);
  // Teams that let their members in here, as well as the people listed one by one.
  const [teamsWithAccess, setTeamsWithAccess] = useState<Team[]>([]);
  const [otherTeams, setOtherTeams] = useState<Team[]>([]);
  const [grantTeamId, setGrantTeamId] = useState("");
  const [poolUsers, setPoolUsers] = useState<AppUser[]>([]);
  const [grantUserId, setGrantUserId] = useState("");
  // Optional: the day their access ends by itself (e.g. a contractor).
  const [grantUntil, setGrantUntil] = useState("");
  const [reviewOpen, setReviewOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [addUserOpen, setAddUserOpen] = useState(false);

  useEffect(() => {
    api.get<Pool[]>("/pools").then(setPools);
  }, []);

  useEffect(() => setGroupChoice(client.pool_name ?? OWN_ACCOUNTS), [client.pool_name]);

  const teamAccess = async (team: Team, on: boolean) => {
    setBusy(true);
    try {
      if (on) await api.post(`/teams/${team.id}/apps`, { client_id: client.client_id });
      else await api.delete(`/teams/${team.id}/apps/${encodeURIComponent(client.client_id)}`);
      show(on ? `Everyone in ${team.name} can log in now` : `${team.name} is no longer let in`);
      setGrantTeamId("");
      loadAccess();
    } catch (err) {
      show(err instanceof ApiError ? err.message : "Something went wrong", "error");
    } finally {
      setBusy(false);
    }
  };

  const loadAccess = () => {
    if (!client.restrict_access) return;
    api.get<AccessGrant[]>(`/clients/${client.client_id}/access`).then(setGrants);
    api
      .get<Team[]>("/teams")
      .then((all) => {
        const has = (t: Team) => t.apps.some((a) => a.client_id === client.client_id);
        setTeamsWithAccess(all.filter(has));
        setOtherTeams(all.filter((t) => !has(t)));
      });
  };

  useEffect(() => {
    const userParam = client.pool_name
      ? `pool=${encodeURIComponent(client.pool_name)}`
      : `client=${encodeURIComponent(client.client_id)}`;
    api.get<UserPage>(`/users?${userParam}&page_size=500`).then((p) => setPoolUsers(p.items));
    loadAccess();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client.restrict_access, client.client_id, client.pool_name]);

  // Each login group, described by the apps already in it.
  const groupLabel = (name: string) => {
    const members = allClients.filter((c) => c.pool_name === name && c.id !== client.id).map(displayName);
    return members.length ? `${name}: same accounts as ${members.join(", ")}` : `${name} (no other apps yet)`;
  };
  const newGroupName = pools.some((p) => p.name === client.client_id) ? null : client.client_id;
  const groupChanged = groupChoice !== (client.pool_name ?? OWN_ACCOUNTS);

  const applyGroup = () => {
    const target = groupChoice === NEW_GROUP ? newGroupName : groupChoice;
    const leaving = client.pool_name;
    confirm({
      title: target ? `Move ${displayName(client)} into ${target}?` : `Give ${displayName(client)} its own accounts?`,
      description: target
        ? `People with an account in any app of ${target} will be able to log in here with the same email and password, and this app's users will be able to log in to those apps. Check that no one has two accounts with the same email across these apps first.`
        : `Only the accounts created through ${displayName(client)} will be able to log in. Users of the other apps in ${leaving} won't be able to anymore. Its own users keep their accounts.`,
      confirmLabel: target ? "Move" : "Use its own accounts",
      onConfirm: async () => {
        try {
          if (groupChoice === NEW_GROUP && target) await api.post("/pools", { name: target });
          if (target) await api.post(`/pools/${encodeURIComponent(target)}/assign-client`, { client_id: client.client_id });
          else if (leaving) await api.post(`/pools/${encodeURIComponent(leaving)}/remove-client`, { client_id: client.client_id });
          await onChanged();
          show(target ? `${displayName(client)} now uses ${target}'s accounts` : `${displayName(client)} now has its own accounts`);
        } catch (err) {
          show(err instanceof ApiError ? err.message : "Couldn't change the login group");
        }
      },
    });
  };

  const grantAccess = async () => {
    if (!grantUserId) return;
    setBusy(true);
    try {
      await api.post(`/clients/${client.client_id}/access`, {
        user_id: grantUserId,
        // The end of that day, in the admin's own time zone.
        expires_at: grantUntil ? new Date(`${grantUntil}T23:59:59`).toISOString() : null,
      });
      setGrantUserId("");
      setGrantUntil("");
      loadAccess();
    } catch (err) {
      show(err instanceof ApiError ? err.message : "Couldn't let them in", "error");
    } finally {
      setBusy(false);
    }
  };

  const revokeAccess = async (userId: string) => {
    await api.delete(`/clients/${client.client_id}/access/${userId}`);
    loadAccess();
  };

  return (
    <>
      <SectionHeading title="People & access" />

      <SettingRow
        title="Whose accounts can log in"
        hint="Apps in the same login group share accounts: one email and password works in all of them."
      >
        <div className="choice-list">
          <label className={`choice${groupChoice === OWN_ACCOUNTS ? " is-selected" : ""}`}>
            <input type="radio" name="login-group" checked={groupChoice === OWN_ACCOUNTS} onChange={() => setGroupChoice(OWN_ACCOUNTS)} />
            <span>
              <strong>Only this app's own accounts</strong>
              <span>Good for an internal admin tool or a client-specific deployment.</span>
            </span>
          </label>
          <label className={`choice${groupChoice !== OWN_ACCOUNTS ? " is-selected" : ""}`}>
            <input
              type="radio"
              name="login-group"
              checked={groupChoice !== OWN_ACCOUNTS}
              disabled={pools.length === 0 && !newGroupName}
              onChange={() => setGroupChoice(client.pool_name ?? pools[0]?.name ?? NEW_GROUP)}
            />
            <span>
              <strong>Share accounts with other apps</strong>
              <span>Single sign-on: people use the account they already have.</span>
            </span>
          </label>
          {groupChoice !== OWN_ACCOUNTS && (
            <select aria-label="Login group" value={groupChoice} onChange={(e) => setGroupChoice(e.target.value)}>
              {pools.map((p) => (
                <option key={p.id} value={p.name}>
                  {groupLabel(p.name)}
                </option>
              ))}
              {newGroupName && <option value={NEW_GROUP}>New login group "{newGroupName}", other apps can join it later</option>}
            </select>
          )}
        </div>
        {groupChanged && (
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button type="button" className="btn btn--primary" onClick={applyGroup}>
              Change login group
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => setGroupChoice(client.pool_name ?? OWN_ACCOUNTS)}>
              Cancel
            </button>
          </div>
        )}
      </SettingRow>

      <SettingRow
        title="Add an account"
        hint={
          client.pool_name
            ? `The account is created in this app and also works in every app of ${client.pool_name}.`
            : "The account is created in this app."
        }
        control={
          <button type="button" className="btn btn--secondary" onClick={() => setAddUserOpen(true)}>
            Add user
          </button>
        }
      />

      <SettingRow
        title="Only let people you choose log in"
        hint={
          client.restrict_access
            ? "Only the people and teams below can log in."
            : client.pool_name
              ? `Everyone in ${client.pool_name} can log in.`
              : "Every user of this app can log in."
        }
        control={
          <Switch
            label="Only let people you choose log in"
            checked={client.restrict_access}
            disabled={flipping !== null}
            onChange={(on) => flip("toggle-restrict-access", on ? "Access limited to chosen people" : "Access opened to everyone")}
          />
        }
      >
        {client.restrict_access && (
          <>
            {grants === null ? (
              <p className="field__hint">Loading…</p>
            ) : grants.length === 0 && teamsWithAccess.length === 0 ? (
              <div className="alert" style={{ marginBottom: 10 }}>
                No one can log in yet. Add a person or a team below.
              </div>
            ) : grants.length === 0 ? null : (
              <ul className="person-list">
                {grants.map((g) => (
                  <li key={g.user_id}>
                    <span>
                      {g.email}
                      {g.expires_at && <span className="app-chip__note"> · until {formatDay(g.expires_at)}</span>}
                    </span>
                    <button type="button" className="btn btn--ghost" onClick={() => revokeAccess(g.user_id)}>
                      Remove access
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {teamsWithAccess.length > 0 && (
              <div className="team-access">
                <span className="team-access__label">Teams</span>
                <ul className="app-chips" style={{ margin: 0 }}>
                  {teamsWithAccess.map((t) => (
                    <li key={t.id} className="app-chip" title="Its sub-teams' people get in too">
                      <span>
                        {t.name} <span className="app-chip__note">· {t.member_count} {t.member_count === 1 ? "person" : "people"}</span>
                      </span>
                      <button type="button" aria-label={`Stop letting ${t.name} in`} onClick={() => teamAccess(t, false)}>
                        <CloseIcon width={12} height={12} />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div style={{ display: "flex", gap: 8 }}>
              <select aria-label="Person to let in" value={grantUserId} onChange={(e) => setGrantUserId(e.target.value)} style={{ flex: 1 }}>
                <option value="">Choose a person{client.pool_name ? ` from ${client.pool_name}` : ""}…</option>
                {poolUsers
                  .filter((u) => !grants?.some((g) => g.user_id === u.id))
                  .map((u) => (
                    <option value={u.id} key={u.id}>
                      {u.email}
                    </option>
                  ))}
              </select>
              <label className="until-field">
                Until
                <input
                  type="date"
                  aria-label="Access ends on (optional)"
                  min={new Date().toISOString().slice(0, 10)}
                  value={grantUntil}
                  onChange={(e) => setGrantUntil(e.target.value)}
                />
              </label>
              <button type="button" className="btn btn--secondary" disabled={!grantUserId || busy} onClick={grantAccess}>
                Let in
              </button>
            </div>

            {otherTeams.length > 0 && (
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <select aria-label="Team to let in" value={grantTeamId} onChange={(e) => setGrantTeamId(e.target.value)} style={{ flex: 1 }}>
                  <option value="">Or a team…</option>
                  {otherTeams.map((t) => (
                    <option value={t.id} key={t.id}>
                      {t.name} ({t.member_count} {t.member_count === 1 ? "person" : "people"})
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn btn--secondary"
                  disabled={!grantTeamId || busy}
                  onClick={() => {
                    const t = otherTeams.find((x) => x.id === grantTeamId);
                    if (t) teamAccess(t, true);
                  }}
                >
                  Let in
                </button>
              </div>
            )}
          </>
        )}
      </SettingRow>

      <SettingRow
        title="Who can log in"
        hint="See everyone with access and how they got it."
        control={
          <button type="button" className="btn btn--secondary" onClick={() => setReviewOpen(true)}>
            Review access
          </button>
        }
      />

      {reviewOpen &&
        createPortal(<AccessReviewModal client={client} onClose={() => setReviewOpen(false)} />, document.body)}

      {/* Outside the panel, so its Escape and focus trap don't also act on the panel. */}
      {addUserOpen &&
        createPortal(
          <AddUserModal
            client={client}
            onClose={() => setAddUserOpen(false)}
            onAdded={() => {
              setAddUserOpen(false);
              loadAccess();
            }}
          />,
          document.body,
        )}
    </>
  );
}

function AddUserModal({ client, onClose, onAdded }: { client: Client; onClose: () => void; onAdded: () => void }) {
  const { show } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [emailVerified, setEmailVerified] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    setAdding(true);
    try {
      const created = await api.post<{ id: string }>("/users", {
        email,
        password,
        confirm_password: confirmPassword,
        client_id: client.client_id,
        email_verified: emailVerified,
      });
      if (client.restrict_access) {
        await api.post(`/clients/${client.client_id}/access`, { user_id: created.id });
      }
      show(`${email} can now log into ${displayName(client)}`);
      onAdded();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setAdding(false);
    }
  };

  return (
    <Modal title={`Add a user to ${displayName(client)}`} onClose={onClose}>
      {error && <div className="alert alert--error">{error}</div>}
      <form onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="manage-add-email">Email</label>
          <input id="manage-add-email" type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="manage-add-password">Password</label>
          <PasswordInput id="manage-add-password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="manage-add-confirm">Confirm password</label>
          <PasswordInput
            id="manage-add-confirm"
            required
            minLength={8}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
          />
        </div>
        <div className="field">
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, fontWeight: 400 }}>
            <input type="checkbox" checked={emailVerified} onChange={(e) => setEmailVerified(e.target.checked)} />
            Treat their email as already verified
          </label>
          <span className="field__hint">Off: they get the same "Unverified" badge and verification email a self-signup gets.</span>
        </div>
        <button type="submit" className="btn btn--primary btn--block" disabled={adding}>
          Add user
        </button>
      </form>
    </Modal>
  );
}

function RolesSection({
  client,
  draft,
  set,
  flip,
  flipping,
}: {
  client: Client;
  draft: Draft;
  set: SetDraft;
  flip: Flip;
  flipping: string | null;
}) {
  const { show } = useToast();
  const [roleNames, setRoleNames] = useState<string[]>([]);
  const [includes, setIncludes] = useState<Record<string, string[]>>({});
  const [userRoles, setUserRoles] = useState<UserRoleRow[] | null>(null);
  const [newRoleName, setNewRoleName] = useState("");
  const [busy, setBusy] = useState(false);

  const loadRoles = () => {
    if (!client.roles_enabled) return;
    api.get<string[]>(`/clients/${client.client_id}/roles`).then(setRoleNames);
    api.get<UserRoleRow[]>(`/clients/${client.client_id}/user-roles`).then(setUserRoles);
    api.get<Record<string, string[]>>(`/clients/${client.client_id}/role-includes`).then(setIncludes);
  };

  const setRoleIncludes = async (role: string, next: string[]) => {
    try {
      await api.put(`/clients/${client.client_id}/roles/${encodeURIComponent(role)}/includes`, { includes: next });
      setIncludes((all) => ({ ...all, [role]: next }));
    } catch (err) {
      show(err instanceof ApiError ? err.message : "Couldn't change that role", "error");
    }
  };

  useEffect(() => {
    loadRoles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client.roles_enabled, client.client_id]);

  const addRole = async (e: FormEvent) => {
    e.preventDefault();
    const name = newRoleName.trim();
    if (!name) return;
    setBusy(true);
    try {
      await api.post(`/clients/${client.client_id}/roles`, { name });
      setNewRoleName("");
      loadRoles();
    } finally {
      setBusy(false);
    }
  };

  const removeRole = async (name: string) => {
    await api.delete(`/clients/${client.client_id}/roles/${encodeURIComponent(name)}`);
    loadRoles();
  };

  const toggleUserRole = async (userId: string, roleName: string, has: boolean) => {
    if (has) await api.delete(`/users/${userId}/roles/${client.client_id}/${encodeURIComponent(roleName)}`);
    else await api.post(`/users/${userId}/roles`, { client_id: client.client_id, role: roleName });
    loadRoles();
  };

  return (
    <>
      <SectionHeading
        title="Roles"
        lead="Names like editor or billing. Your app reads them from the token and decides what each allows."
      />
      <SettingRow
        title="Use roles in this app"
        control={
          <Switch
            label="Use roles in this app"
            checked={client.roles_enabled}
            disabled={flipping !== null}
            onChange={(on) => flip("toggle-roles-enabled", on ? "Roles turned on" : "Roles turned off")}
          />
        }
      />

      {client.roles_enabled && (
        <div className="sheet__fields">
          <form onSubmit={addRole} style={{ display: "flex", gap: 8, marginBottom: 14 }}>
            <input
              aria-label="New role name"
              placeholder="Role name, e.g. editor"
              value={newRoleName}
              onChange={(e) => setNewRoleName(e.target.value)}
              style={{ flex: 1 }}
            />
            <button type="submit" className="btn btn--secondary" disabled={!newRoleName.trim() || busy}>
              Add role
            </button>
          </form>

          {roleNames.length > 1 && (
            <div className="role-includes">
              <h3 className="sheet__section-title" style={{ margin: "0 0 10px" }}>
                Roles that include others
              </h3>
              {roleNames.map((r) => {
                const mine = includes[r] ?? [];
                const options = roleNames.filter((o) => o !== r && !mine.includes(o));
                return (
                  <div key={r} className="role-includes__row">
                    <strong className="role-includes__role">{r}</strong>
                    <span className="role-includes__arrow" aria-hidden="true">
                      includes
                    </span>
                    {mine.map((inc) => (
                      <span key={inc} className="app-chip">
                        <span>{inc}</span>
                        <button type="button" aria-label={`${r} no longer includes ${inc}`} onClick={() => setRoleIncludes(r, mine.filter((x) => x !== inc))}>
                          <CloseIcon width={12} height={12} />
                        </button>
                      </span>
                    ))}
                    {options.length > 0 && (
                      <select
                        aria-label={`Add a role that ${r} includes`}
                        value=""
                        onChange={(e) => e.target.value && setRoleIncludes(r, [...mine, e.target.value])}
                      >
                        <option value="">{mine.length ? "+ add" : "nothing"}</option>
                        {options.map((o) => (
                          <option key={o} value={o}>
                            {o}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <div className="field" style={{ maxWidth: 360 }}>
            <label htmlFor="manage-roles-claim">Claim name in tokens</label>
            <input id="manage-roles-claim" value={draft.rolesClaim} onChange={(e) => set("rolesClaim", e.target.value)} />
            <span className="field__hint">Usually <code>roles</code>.</span>
          </div>

          {roleNames.length === 0 ? (
            <p className="field__hint">No roles yet. Add the first one above.</p>
          ) : userRoles === null ? (
            <p className="field__hint">Loading…</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Person</th>
                    {roleNames.map((r) => (
                      <th key={r} style={{ textAlign: "center" }}>
                        {r}{" "}
                        <button type="button" className="btn btn--ghost" aria-label={`Delete role ${r}`} title={`Delete role "${r}"`} onClick={() => removeRole(r)}>
                          ×
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {userRoles.map((row) => (
                    <tr key={row.user_id}>
                      <td style={{ fontSize: 13.5 }}>{row.email}</td>
                      {roleNames.map((r) => {
                        const has = row.roles.includes(r);
                        return (
                          <td key={r} style={{ textAlign: "center" }}>
                            <input
                              type="checkbox"
                              aria-label={`${row.email} is ${r}`}
                              checked={has}
                              onChange={() => toggleUserRole(row.user_id, r, has)}
                            />
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </>
  );
}

function AppearanceSection({ draft, set }: { draft: Draft; set: SetDraft }) {
  // <input type="color"> only takes #rrggbb; anything else stays text-only.
  const pickerValue = /^#[0-9a-fA-F]{6}$/.test(draft.brandColor) ? draft.brandColor : "#4f46e5";
  return (
    <>
      <SectionHeading title="Appearance" lead="How this app's login, signup and consent pages look." />
      <div className="sheet__fields">
        <div className="field">
          <label htmlFor="manage-logo">Logo URL</label>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            {draft.logoUrl && <img className="logo-preview" src={draft.logoUrl} alt="" />}
            <input id="manage-logo" value={draft.logoUrl} onChange={(e) => set("logoUrl", e.target.value)} placeholder="https://yourapp.com/logo.png" />
          </div>
        </div>
        <div className="field">
          <label htmlFor="manage-brand">Brand color</label>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <input
              type="color"
              aria-label="Pick brand color"
              className="color-swatch"
              value={pickerValue}
              onChange={(e) => set("brandColor", e.target.value)}
            />
            <input id="manage-brand" value={draft.brandColor} onChange={(e) => set("brandColor", e.target.value)} placeholder="#4f46e5" style={{ maxWidth: 200 }} />
            {draft.brandColor && (
              <button type="button" className="btn btn--ghost" onClick={() => set("brandColor", "")}>
                Use the default
              </button>
            )}
          </div>
          <span className="field__hint">Used for buttons and links on its login pages.</span>
        </div>
      </div>
    </>
  );
}

function AdvancedSection({
  client,
  draft,
  set,
  onDisable,
  onDelete,
}: {
  client: Client;
  draft: Draft;
  set: SetDraft;
  onDisable: () => void;
  onDelete: () => void;
}) {
  return (
    <>
      <SectionHeading title="Advanced" />
      <div className="sheet__fields">
        <div className="field">
          <label htmlFor="manage-scope">
            Allowed scopes <span className="field__hint">(space-separated)</span>
          </label>
          <input id="manage-scope" value={draft.scope} onChange={(e) => set("scope", e.target.value)} placeholder="openid profile email" />
          <span className="field__hint">Leave blank for the default access level.</span>
        </div>
        {client.grant_types.includes("authorization_code") && (
          <EmbedOriginsField value={draft.embedOrigins} onChange={(v) => set("embedOrigins", v)} />
        )}
        <div className="field">
          <label htmlFor="manage-mtls">mTLS certificate thumbprint</label>
          <input
            id="manage-mtls"
            value={draft.thumbprint}
            onChange={(e) => set("thumbprint", e.target.value)}
            placeholder="Cert thumbprint (hex)"
            style={{ fontFamily: "var(--font-mono)" }}
          />
          <span className="field__hint">
            Only checked for apps that talk directly to the server. Leave blank unless you've set up
            mutual TLS for it.
          </span>
        </div>
      </div>

      <div className="danger-zone">
        <SettingRow
          title={client.enabled ? "Disable this application" : "Re-enable this application"}
          hint={
            client.enabled
              ? "Blocks every login and token refresh straight away. Nothing is deleted."
              : "Lets it accept logins and token refreshes again."
          }
          control={
            <button type="button" className={`btn ${client.enabled ? "btn--danger" : "btn--secondary"}`} onClick={onDisable}>
              {client.enabled ? "Disable" : "Re-enable"}
            </button>
          }
        />
        <SettingRow
          title="Remove this application"
          hint="Deletes it and the accounts created through it. This cannot be undone."
          control={
            <button type="button" className="btn btn--danger" onClick={onDelete}>
              Remove
            </button>
          }
        />
      </div>
    </>
  );
}

function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function AccessReviewModal({ client, onClose }: { client: Client; onClose: () => void }) {
  const [review, setReview] = useState<AccessReview | null>(null);
  const [query, setQuery] = useState("");
  useEffect(() => {
    api.get<AccessReview>(`/clients/${client.client_id}/access-review`).then(setReview);
  }, [client.client_id]);

  const people = (review?.people ?? []).filter(
    (p) => !query || `${p.email} ${p.name}`.toLowerCase().includes(query.trim().toLowerCase()),
  );

  const download = () => {
    const cell = (v: string) => `"${v.replace(/"/g, '""')}"`;
    const lines = [
      ["email", "name", "status", "how they get in", "ends"].map(cell).join(","),
      ...(review?.people ?? []).flatMap((p) =>
        p.reasons.map((r) =>
          [p.email, p.name, p.active ? "active" : "stopped", r.label, r.expires_at ?? ""].map(cell).join(","),
        ),
      ),
    ];
    const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `access-${client.client_id}-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Modal title={`Who can log in to ${displayName(client)}`} wide onClose={onClose}>
      {review === null ? (
        <p className="field__hint">Loading…</p>
      ) : (
        <>
          <p className="modal__lead">
            {review.restricted
              ? "Only these people can log in."
              : `Open to everyone with an account${client.pool_name ? ` in ${client.pool_name}` : ""}.`}
          </p>
          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            <input
              type="search"
              aria-label="Filter people"
              placeholder="Search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{ flex: 1 }}
            />
            <button type="button" className="btn btn--secondary" onClick={download} disabled={review.people.length === 0}>
              Download CSV
            </button>
          </div>
          {people.length === 0 ? (
            <p className="chart-empty">{review.people.length ? "No one matches." : "No one can log in yet."}</p>
          ) : (
            <div className="table-wrap" style={{ maxHeight: 420, overflow: "auto" }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Person</th>
                    <th>Access</th>
                  </tr>
                </thead>
                <tbody>
                  {people.map((p) => (
                    <tr key={p.user_id}>
                      <td>
                        <strong style={{ display: "block", fontSize: 13.5 }}>{p.name || p.email}</strong>
                        {p.name && <span className="field__hint">{p.email}</span>}
                        {!p.active && <Badge variant="neutral">Stopped</Badge>}
                      </td>
                      <td>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                          {p.reasons.map((r, i) => (
                            <span key={i} className="tag">
                              {r.label}
                              {r.expires_at ? ` · until ${formatDay(r.expires_at)}` : ""}
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="field__hint" style={{ marginTop: 10 }}>
            {review.people.length} {review.people.length === 1 ? "person" : "people"} in total.
          </p>
        </>
      )}
    </Modal>
  );
}
