"use client";

import { useEffect, useState } from "react";
import { connectGmail, deleteAccount, getAccounts, syncAccount, type Account } from "../../lib/api-client";
import { Shell } from "../shell";

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]); const [busy, setBusy] = useState<string | null>(null); const [error, setError] = useState<string | null>(null);
  const load = () => getAccounts().then(setAccounts).catch(() => setError("Unable to load connected accounts."));
  useEffect(() => { void load(); setError(new URLSearchParams(window.location.search).get("error")); }, []);
  async function sync(id: string) { setBusy(id); setError(null); try { await syncAccount(id); await load(); } catch { setError("Sync failed. Try again in a moment."); } finally { setBusy(null); } }
  async function disconnect(id: string) { if (!window.confirm("Disconnect this Gmail account?")) return; setBusy(id); try { await deleteAccount(id); await load(); } catch { setError("Could not disconnect this account."); } finally { setBusy(null); } }
  return <Shell><div className="page accounts"><h1>Connected Gmail Accounts</h1><p>Manage your connected inboxes and synchronization settings. Intelligence processing requires active connections.</p>{error && <p className="form-error" role="alert">{error}</p>}<section className="account-grid">{accounts.map((account) => <article className="account-tile" key={account.id}><div><i>✉</i><h2>{account.name || account.email.split("@", 1)[0]}<small>{account.email}</small></h2><span className="connected">● Connected</span></div><p><span>Last connected</span><b>{account.last_synced_at ? new Date(account.last_synced_at).toLocaleString() : "Not synced yet"}</b></p><p><span>Intelligence Sync</span><b className="active">◉ Active</b></p><footer><button disabled={busy === account.id} onClick={() => void sync(account.id)}>{busy === account.id ? "Syncing…" : "Sync Now"}</button><button disabled={busy === account.id} onClick={() => void disconnect(account.id)}>Disconnect</button></footer></article>)}<button className="add-account" onClick={() => void connectGmail()}><i>＋</i><b>Connect another Gmail</b><span>Authorize a new account to bring more context into your intelligence dashboard.</span></button></section></div></Shell>;
}
