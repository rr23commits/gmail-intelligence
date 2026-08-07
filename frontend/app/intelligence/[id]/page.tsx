"use client";

import { useEffect, useState } from "react";
import { getIntelligenceDetail, type IntelligenceDetail } from "../../../lib/api-client";
import { Shell } from "../../shell";

export default function DetailPage({ params }: { params: Promise<{ id: string }> }) {
  const [item, setItem] = useState<IntelligenceDetail | null>(null);
  useEffect(() => { void params.then(({ id }) => getIntelligenceDetail(id).then(setItem).catch(() => setItem(null))); }, [params]);
  if (!item) return <Shell><div className="page"><div className="empty-state">This intelligence item is unavailable.</div></div></Shell>;
  return <Shell><div className="page detail-page"><div className="crumbs"><a href="/intelligence">← Intelligence Feed</a><span>›</span> Message Detail</div><h1>{item.subject}</h1><p className="sender">♟ &nbsp;{item.messages[0]?.from || item.account} <span>•</span> {new Date(item.at).toLocaleString()}</p><hr /><div className="detail-grid"><section><div className="summary-box"><small>✦ &nbsp; Intelligence summary</small><p>{item.summary}</p></div><div className="why-box"><h2>▣ &nbsp; Why we classified it this way</h2><p>◉ &nbsp;Contains a relevant keyword or time-sensitive request.</p><p>◉ &nbsp;Message is directly addressed to your connected mailbox.</p><p>◉ &nbsp;Context implies a high likelihood that it requires attention.</p></div></section><aside className="analytics"><b>Message analytics</b><small>Category</small><span className="category">△ &nbsp;{item.category}</span><hr /><label>Priority score <strong>{item.priority}<em>/100</em></strong><i><span style={{ width: `${item.priority}%` }} /></i></label><label>AI confidence <strong>96<em>%</em></strong><i><span style={{ width: "96%" }} /></i></label><button onClick={() => window.open("https://mail.google.com", "_blank", "noopener,noreferrer")}>✉ &nbsp; View original in Gmail</button></aside></div></div></Shell>;
}
