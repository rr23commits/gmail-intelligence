"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getAccounts, getDashboard, type Account, type DailyBriefing } from "../lib/api-client";

const label = (value: string) => value.replaceAll("_", " ");

export default function DashboardPage() {
  const [briefing, setBriefing] = useState<DailyBriefing | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [account, setAccount] = useState("");
  useEffect(() => { void getAccounts().then(setAccounts).catch(() => setAccounts([])); }, []);
  useEffect(() => { setBriefing(null); void getDashboard(account || undefined).then(setBriefing).catch(() => setBriefing({ tasks: [], consider: [], consider_count: 0, cleanup_count: 0 })); }, [account]);
  if (!briefing) return <div className="page dashboard"><div className="empty-state">Loading today&apos;s briefing…</div></div>;
  return <div className="page dashboard"><div className="dash-heading"><div><h1>Today&apos;s briefing</h1><p>What should you focus on today?</p></div><select className="dashboard-account" value={account} onChange={(event) => setAccount(event.target.value)}><option value="">All accounts</option>{accounts.map((item) => <option value={item.id} key={item.id}>{item.name || item.email}</option>)}</select></div><section className="daily-briefing"><BriefingSection title="Needs your attention" detail="Open actions from your email conversations.">{briefing.tasks.map((task) => <Link className="briefing-task" href={`/intelligence/${task.source_thread_id}?message=${task.source_message_id}`} key={task.id}><div><b>{task.open_action}</b><small>{[task.deadline && `Deadline: ${task.deadline}`, `Priority ${task.priority}`].filter(Boolean).join(" · ") || task.latest_event || task.account}</small></div><span>Open action →</span></Link>)}{!briefing.tasks.length && <p>Nothing needs action right now.</p>}</BriefingSection><BriefingSection title="Worth considering" detail={`${briefing.consider_count} emails worth your attention.`}>{briefing.consider.map((item) => <Link href={`/intelligence/${item.id}`} key={item.id}><b>{item.subject}</b><small>{label(item.category)} · Priority {item.priority}</small></Link>)}{!briefing.consider.length && <p>Nothing to consider right now.</p>}</BriefingSection><BriefingSection title="Can probably go" detail={`${briefing.cleanup_count} lower-priority emails are ready to review.`}><Link className="briefing-cleanup" href="/intelligence/cleanup"><b>Review Cleanup</b><span>{briefing.cleanup_count} emails →</span></Link></BriefingSection></section></div>;
}

function BriefingSection({ title, detail, children }: { title: string; detail: string; children: React.ReactNode }) {
  return <section className="briefing-section"><header><h2>{title}</h2><small>{detail}</small></header><div>{children}</div></section>;
}
