"use client";

import { type FormEvent, type ReactNode, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { usePathname } from "next/navigation";

import { connectGmail } from "../lib/api-client";

const links = [
  ["/", "▦", "Dashboard"],
  ["/intelligence", "♙", "Intelligence"],
  ["/accounts", "◎", "Accounts"],
  ["/settings", "⚙", "Settings"],
];

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [search, setSearch] = useState("");

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    router.push(`/intelligence?q=${encodeURIComponent(search)}`);
  }

  return <div className="canvas"><main className="product"><aside className="sidebar"><Link className="logo" href="/"><b>✉</b><span>Gmail Intel<small>Executive Dashboard</small></span></Link><button className="connect-button" onClick={() => void connectGmail()}>＋&nbsp; Connect Gmail</button><nav>{links.map(([href, icon, label]) => <Link href={href} className={path === href || (href !== "/" && path.startsWith(href)) ? "selected" : ""} key={href}><i>{icon}</i>{label}</Link>)}</nav><div className="sidebar-footer"><button onClick={() => alert("This local app has no separate signed-in session to end.")}>⇥&nbsp; Sign Out</button></div></aside><section className="workspace"><header className="topbar"><form onSubmit={submitSearch}><label><span>⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search insights…" aria-label="Search insights" /></label></form><div><button aria-label="Notifications" className="icon-button" onClick={() => alert("No new notifications.")}>♧</button><Link className="profile" href="/settings">U</Link></div></header>{children}</section></main></div>;
}
