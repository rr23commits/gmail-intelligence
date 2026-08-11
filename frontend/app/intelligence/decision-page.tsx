"use client";

import { useEffect, useState } from "react";

import { getAccounts, getIntelligence, type Account, type IntelligenceItem } from "../../lib/api-client";
import { Shell } from "../shell";

const label = (value: string) => value.replaceAll("_", " ");

export function DecisionPage({ decision, title, description }: { decision: "do" | "consider"; title: string; description: string }) {
  const [items, setItems] = useState<IntelligenceItem[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [account, setAccount] = useState("");

  useEffect(() => { void getAccounts().then(setAccounts).catch(() => setAccounts([])); }, []);
  useEffect(() => { void getIntelligence({ accountId: account || undefined, decision }).then(setItems).catch(() => setItems([])); }, [account, decision]);

  return <Shell><div className="page intelligence decision-page"><div className="crumbs"><a href="/intelligence">← Intelligence</a><span>›</span> {title}</div><h1>{title}</h1><p>{description}</p><select className="decision-account" value={account} onChange={(event) => setAccount(event.target.value)}><option value="">All accounts</option>{accounts.map((item) => <option value={item.id} key={item.id}>{item.name || item.email}</option>)}</select><small className="list-label">{items.length} emails</small><section className="intelligence-list">{items.map((item) => <a href={`/intelligence/${item.id}`} className={`insight-row ${item.priority >= 80 ? "urgent" : ""}`} key={item.id}><i>{item.priority >= 80 ? "!" : "◇"}</i><div><small>{item.account}</small><h2>{item.subject}</h2><span>{label(item.category)}</span><span>{label(item.decision)}</span>{item.priority >= 80 && <span>High priority</span>}</div><time>Priority {item.priority}　›</time></a>)}{!items.length && <div className="empty-state">No emails match this decision.</div>}</section></div></Shell>;
}
