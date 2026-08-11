"use client";

import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { usePathname } from "next/navigation";

import { connectGmail, getSession, login, logout } from "../lib/api-client";

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
  const [password, setPassword] = useState("");
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [signInError, setSignInError] = useState("");

  useEffect(() => { void getSession().then(() => setSignedIn(true)).catch(() => setSignedIn(false)); }, []);

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    router.push(`/intelligence?q=${encodeURIComponent(search)}`);
  }

  if (signedIn === null) return <div className="canvas"><main className="product"><section className="workspace"><div className="page"><div className="empty-state">Checking session…</div></div></section></main></div>;
  if (!signedIn) return <div className="canvas"><main className="product"><section className="workspace"><form className="page" onSubmit={(event) => { event.preventDefault(); void login(password).then(() => setSignedIn(true)).catch(() => setSignInError("Sign-in failed.")); }}><h1>Sign in</h1><p>Enter the local app password configured in <code>.env</code>.</p><input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} aria-label="Local app password" /><button disabled={!password}>Sign in</button>{signInError && <p className="form-error" role="alert">{signInError}</p>}</form></section></main></div>;
  return <div className="canvas"><main className="product"><aside className="sidebar"><Link className="logo" href="/"><b>✉</b><span>Gmail Intel<small>Executive Dashboard</small></span></Link><button className="connect-button" onClick={() => void connectGmail()}>＋&nbsp; Connect Gmail</button><nav>{links.map(([href, icon, label]) => <Link href={href} className={path === href || (href !== "/" && path.startsWith(href)) ? "selected" : ""} key={href}><i>{icon}</i>{label}</Link>)}</nav><div className="sidebar-footer"><button onClick={() => void logout().then(() => setSignedIn(false))}>⇥&nbsp; Sign Out</button></div></aside><section className="workspace"><header className="topbar"><form onSubmit={submitSearch}><label><span>⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search insights…" aria-label="Search insights" /></label></form><div><button aria-label="Notifications" className="icon-button" onClick={() => alert("No new notifications.")}>♧</button><Link className="profile" href="/settings">U</Link></div></header>{children}</section></main></div>;
}
