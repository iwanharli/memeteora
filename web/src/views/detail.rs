use maud::{html, Markup};

use super::{edge_class, f, money, risk_band, signed};
use crate::models::{HistoryPoint, PoolDetail, PoolScore};

pub fn page(d: &PoolDetail, sc: Option<&PoolScore>, hist: &[HistoryPoint]) -> Markup {
    let title = d.name.clone().unwrap_or_else(|| d.address.clone());
    let sub = html! {
        a href="/" { "← all pools" }
        " · "
        a href={ "https://www.meteora.ag/dlmm/" (d.address) } target="_blank" rel="noreferrer" { "Meteora" }
        " · "
        a href={ "https://dexscreener.com/solana/" (d.address) } target="_blank" rel="noreferrer" { "DexScreener" }
    };
    let body = html! {
        h2 { (title) }
        (meta_block(d))
        @if let Some(s) = sc { (score_block(s)) }
        h2 { "Snapshots" }
        @if hist.len() < 2 {
            div."wrap" { div."empty" {
                "Only " (hist.len()) " snapshot so far. Trends need a few ingest cycles — "
                "a single point tells you nothing about persistence."
            } }
        }
        (history_table(hist))
    };
    super::layout::shell(&title, sub, body)
}

fn meta_block(d: &PoolDetail) -> Markup {
    html! {
        div."meta" {
            div { span { "base" } (d.base_symbol.clone().unwrap_or_else(|| "–".into())) }
            div { span { "quote" } (d.quote_symbol.clone().unwrap_or_else(|| "–".into())) }
            div { span { "bin step" } (d.bin_step.unwrap_or(0)) " bps" }
            div { span { "base fee" } (f(d.base_fee_pct, 2)) "%" }
            div { span { "max fee" } (f(d.max_fee_pct, 2)) "%" }
            div { span { "holders" }
                  (d.holders.map(|h| h.to_string()).unwrap_or_else(|| "–".into())) }
            div { span { "verified" } (if d.is_verified.unwrap_or(false) { "yes" } else { "no" }) }
            div { span { "created" }
                @match d.created_at {
                    Some(t) => { (super::wib(t).format("%Y-%m-%d")) }
                    None => { "–" }
                }
            }
            div { span { "address" } code { (d.address) } }
        }
    }
}

fn score_block(s: &PoolScore) -> Markup {
    html! {
        div."cards" style="margin-top:14px" {
            div."card" { div."k" { "adjusted" } div."v" { (f(Some(s.adjusted), 1)) } }
            div."card" { div."k" { "opportunity" } div."v" { (f(Some(s.opportunity), 1)) } }
            div."card" { div."k" { "risk" }
                div."v" { span class={ "pill " (risk_band(s.risk)) } { (f(Some(s.risk), 1)) } } }
            div."card" { div."k" { "fee / day" } div."v" { (f(s.fee_day_pct, 2)) "%" } }
            div."card" { div."k" { "floor" } div."v" { (f(s.floor_pct, 2)) "%" } }
            div."card" { div."k" { "σ / day" }
                div."v" { (s.sigma_daily.map(|v| format!("{:.1}%", v * 100.0))
                            .unwrap_or_else(|| "–".into())) } }
            div."card" { div."k" { "LVR / day" } div."v" { (f(s.lvr_daily_pct, 2)) "%" } }
            div."card" { div."k" { "edge (fee − LVR)" }
                div class={ "v " (edge_class(s.edge_lvr_pct)) } { (signed(s.edge_lvr_pct, 2)) "%" } }
        }
        @if let Some(flags) = s.risk_flags.as_deref() {
            @if !flags.is_empty() {
                div."flags" style="justify-content:flex-start;margin-top:10px" {
                    @for fg in flags { span."flag sev" { (fg) } }
                }
            }
        }
    }
}

fn history_table(hist: &[HistoryPoint]) -> Markup {
    html! {
        div."wrap" {
            table style="min-width:720px" {
                thead { tr {
                    th."l" { "when (WIB)" } th { "tvl" } th { "fee/day" }
                    th { "volume 24h" } th { "price" } th { "adj" } th { "risk" }
                } }
                tbody {
                    @for h in hist {
                        tr {
                            td."l" { (super::wib(h.ts).format("%Y-%m-%d %H:%M")) }
                            td { (money(h.tvl)) }
                            td { (f(h.fee_day, 2)) "%" }
                            td { (money(h.vol_24h)) }
                            td { @match h.price { Some(p) => { "$" (format!("{:.6}", p)) } None => { "–" } } }
                            td { (f(h.adjusted, 1)) }
                            td { @match h.risk {
                                Some(r) => { span class={ "pill " (risk_band(r)) } { (f(Some(r), 1)) } }
                                None => { "–" }
                            } }
                        }
                    }
                }
            }
        }
    }
}
