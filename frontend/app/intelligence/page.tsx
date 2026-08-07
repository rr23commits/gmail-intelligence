"use client";

import { useEffect, useMemo, useState } from "react";
import { getAccounts, getIntelligence, type Account, type IntelligenceItem } from "../../lib/api-client";
import { Shell } from "../shell";

export default function IntelligencePage() {
  const [items, setItems] = useState<IntelligenceItem[]>([]); const [accounts, setAccounts] = useState<Account[]>([]); const [search, setSearch] = useState(""); const [tab, setTab] = useState("All"); const [account, setAccount] = useState("");
  useEffect(() => { setSearch(new URLSearchParams(window.location.search).get("q") || ""); void getIntelligence().then(setItems).catch(() => setItems([])); void getAccounts().then(setAccounts).catch(() => setAccounts([])); }, []);
  const visible = useMemo(() => items.filter((item) => (!account || item.account_id === account) && (tab === "All" || (tab === "Action Required" ? item.priority >= 70 : item.category === tab)) && `${item.subject} ${item.snippet}`.toLowerCase().includes(search.toLowerCase())), [items, account, tab, search]);
  return <Shell><div className="page intelligence"><h1>Intelligence</h1><div className="filter-row"><select value={account} onChange={(event) => setAccount(event.target.value)}><option value="">All accounts</option>{accounts.map((item) => <option value={item.id} key={item.id}>{item.name || item.email}</option>)}</select><div className="tabs">{["All", "Action Required", "Important", "Review", "Bulk"].map((item) => <button onClick={() => setTab(item)} className={tab === item ? "active" : ""} key={item}>{item}</button>)}</div></div><input className="mobile-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search insights…" /> <section className="intelligence-list">{visible.map((item) => <a href={`/intelligence/${item.id}`} className={`insight-row ${item.priority >= 70 ? "urgent" : ""}`} key={item.id}><i>{item.priority >= 70 ? "!" : "i"}</i><div><small>{item.account}</small><h2>{item.subject}</h2><span>{item.priority >= 70 ? "△ Action Required" : `◉ ${item.category}`}</span>{item.priority >= 70 && <span>High priority</span>}</div><time>{new Date(item.at).toLocaleDateString()}</time></a>)}{!visible.length && <div className="empty-state">No intelligence matches this view.</div>}</section></div></Shell>;
}
