"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { getAccounts, getIntelligence, type Account, type IntelligenceItem } from "../../lib/api-client";

const label = (value: string) => value.replaceAll("_", " ");

export function DecisionPage({ decision, title, description }: { decision: "do" | "consider"; title: string; description: string }) {
  const [items, setItems] = useState<IntelligenceItem[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [account, setAccount] = useState(""); const [hasMore, setHasMore] = useState(false);

  useEffect(() => { void getAccounts().then(setAccounts).catch(() => setAccounts([])); }, []);
  useEffect(() => { void getIntelligence({ accountId: account || undefined, decision, limit: 100 }).then((next) => { setItems(next); setHasMore(next.length === 100); }).catch(() => setItems([])); }, [account, decision]);

  return <div className="page intelligence decision-page"><div className="crumbs"><Link href="/intelligence">← Intelligence</Link><span>›</span> {title}</div><h1>{title}</h1><p>{description}</p><select className="decision-account" value={account} onChange={(event) => setAccount(event.target.value)}><option value="">All accounts</option>{accounts.map((item) => <option value={item.id} key={item.id}>{item.name || item.email}</option>)}</select><small className="list-label">{items.length} emails</small><section className="intelligence-list">{items.map((item) => <Link href={`/intelligence/${item.id}`} className={`insight-row ${item.priority >= 80 ? "urgent" : ""}`} key={item.id}><i>{item.priority >= 80 ? "!" : "◇"}</i><div><small>{item.account}</small><h2>{item.subject}</h2><span>{label(item.category)}</span><span>{label(item.decision)}</span>{item.priority >= 80 && <span>High priority</span>}</div><time>Priority {item.priority}　›</time></Link>)}{!items.length && <div className="empty-state">No emails match this decision.</div>}</section>{hasMore && <button className="load-more" onClick={() => void getIntelligence({ accountId: account || undefined, decision, limit: 100, offset: items.length }).then((next) => { setItems((current) => [...current, ...next]); setHasMore(next.length === 100); })}>Load more emails</button>}</div>;
}
