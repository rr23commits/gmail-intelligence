"use client";

import { useEffect, useState } from "react";
import { getAccounts, getDashboard, type Account, type IntelligenceItem } from "../lib/api-client";
import { Shell } from "./shell";

const groups = ["People & conversations", "Important activity", "Needs your attention"];
function groupFor(item: IntelligenceItem) { return item.priority >= 70 ? groups[2] : item.category === "FYI" ? groups[1] : groups[0]; }

export default function DashboardPage() {
  const [items, setItems] = useState<IntelligenceItem[]>([]); const [accounts, setAccounts] = useState<Account[]>([]);
  useEffect(() => { void getDashboard().then((data) => setItems(data.items)).catch(() => setItems([])); void getAccounts().then(setAccounts).catch(() => setAccounts([])); }, []);
  return <Shell><div className="page dashboard"><div className="dash-heading"><div><h1>Good morning user,</h1><p>here&apos;s what needs your attention.</p></div><small>↻ &nbsp; Last sync: 9:00 AM, Next sync: 9:00 PM</small></div>{accounts.length ? accounts.map((account) => <AccountDigest account={account} items={items.filter((item) => item.account_id === account.id)} key={account.id} />) : <div className="empty-state"><b>Connect Gmail to start your intelligence briefing.</b><a href="/accounts">Connect an account →</a></div>}</div></Shell>;
}

function AccountDigest({ account, items }: { account: Account; items: IntelligenceItem[] }) {
  return <section className="digest"><h2><i>{account.email.includes("work") ? "▣" : "◎"}</i>{account.name || account.email.split("@", 1)[0]}<small>{account.email}</small></h2><div className="digest-summary"><b>Summary:</b> You have {items.length || "no"} things worth knowing about.</div><div className="digest-columns">{groups.map((group) => <div className={group === groups[2] ? "attention" : ""} key={group}><h3>{group === groups[2] ? "⚠" : group === groups[1] ? "♧" : "▣"} &nbsp;{group}</h3>{items.filter((item) => groupFor(item) === group).slice(0, 3).map((item) => <a href={`/intelligence/${item.id}`} key={item.id}>{item.subject}</a>)}{!items.filter((item) => groupFor(item) === group).length && <p>Nothing new here.</p>}</div>)}</div></section>;
}
