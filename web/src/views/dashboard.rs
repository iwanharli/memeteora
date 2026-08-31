use maud::{html, Markup, PreEscaped};

use super::{edge_class, f, meteora_link, risk_band, signed};

/// A daily sigma of 0.2576 reads as 25.8%.
fn pct(v: Option<f64>) -> String {
    match v { Some(x) => format!("{:.1}%", x * 100.0), None => "–".into() }
}

/// At most two chips, then a count. Wrapping flags broke the row rhythm and
/// made a scan down the table impossible.
const FLAG_LIMIT: usize = 2;

fn flag_class(flag: &str) -> &'static str {
    if GOOD.contains(&flag) { "good" }
    else if SEVERE.contains(&flag) { "sev" }
    else { "" }
}

/// Green when the pool actually turns over enough to pay for its own volatility.
fn brk_class(breakeven: Option<f64>, turnover: Option<f64>) -> &'static str {
    match (breakeven, turnover) {
        (Some(b), Some(t)) if t >= b => "pos",
        (Some(_), Some(_)) => "neg",
        _ => "dim",
    }
}
use crate::models::{Filters, PoolScore, Stats};

const SEVERE: [&str; 6] = ["FREEZE-AUTHORITY", "collapsing", "fee<LVR",
                           "mcap/tvl>100", "turnover>60x", "high-LVR"];
/// Not a warning - a structural advantage worth spotting at a glance.
const GOOD: [&str; 1] = ["quote-only-fees"];

pub fn page(rows: &[PoolScore], st: &Stats, fl: &Filters) -> Markup {
    let sub = html! {
        @match st.last_run {
            Some(t) => { "last ingest " (super::wib(t).format("%Y-%m-%d %H:%M")) " WIB" }
            None => { "no data yet — run the ingest worker" }
        }
    };
    let body = html! {
        (cards(st, rows))
        (filters(fl))
        @if rows.is_empty() {
            div."wrap" { div."empty" {
                "Nothing matches. Loosen the filters, or run "
                code { "python3 ingest/main.py ingest" } "."
            } }
        } @else {
            (table(rows, fl))
        }
        p."note" {
            strong { "EDGE" } " = fee/d − LVR, where LVR = σ²/8 is the adverse-selection "
            "cost of quoting a stale price (Milionis et al. 2022). This is the column that "
            "decides profit; a pool with EDGE < 0 loses money no matter how you shape the range. "
            strong { "brkevn" } " is the turnover needed to cover LVR at this fee tier — "
            "green when actual turnover clears it. "
            br;
            strong { "adj" } " = opportunity × (1 − risk/100). "
            strong { "fee/d" } " = today's fees as % of TVL. "
            strong { "floor" } " = worst of six windows (30m…24h) normalised to a daily rate — "
            "the conservative read, immune to a single hot hour. "
            strong { "cv" } " = dispersion across those windows; low means steady. "
            br;
            strong { "Q" } " marks pools that pay fees in the quote token only — in a "
            "memecoin pool that is the difference between banked income and more of the "
            "exposure you already carry."
            br;
            "Risk now prices volatility as LVR, not impermanent loss: risk correlates "
            "−0.55 with EDGE. Opportunity still does not (r ≈ −0.04) — rank by EDGE."
        }
    };
    super::layout::shell("Dashboard", sub, body)
}

fn cards(st: &Stats, rows: &[PoolScore]) -> Markup {
    let profitable = rows.iter().filter(|r| r.edge_lvr_pct.unwrap_or(-1.0) > 0.0).count();
    let median_risk = {
        let mut v: Vec<f64> = rows.iter().map(|r| r.risk).collect();
        v.sort_by(|a, b| a.partial_cmp(b).unwrap());
        (!v.is_empty()).then(|| v[v.len() / 2])
    };
    html! {
        div."cards" {
            div."card" { div."k" { "pools tracked" } div."v" { (st.pools) } }
            div."card" { div."k" { "snapshots" } div."v" { (st.snapshots) } }
            div."card" { div."k" { "shown" } div."v" { (rows.len()) } }
            div."card" { div."k" { "fee beats LVR" }
                div class={ "v " (if profitable > 0 { "pos" } else { "dim" }) } { (profitable) } }
            div."card" { div."k" { "median risk" } div."v" { (f(median_risk, 1)) } }
        }
    }
}

fn filters(fl: &Filters) -> Markup {
    html! {
        form."filters" method="get" action="/" {
            label { "max risk" }
            input type="number" name="max_risk" step="1" min="0" max="100" value=(fl.max_risk());
            label { "min opp" }
            input type="number" name="min_opp" step="1" min="0" max="100" value=(fl.min_opp());
            label { "rows" }
            input type="number" name="limit" step="10" min="1" max="300" value=(fl.limit());
            label."chk" {
                input type="checkbox" name="positive_lvr_edge" value="true"
                    checked[fl.positive_lvr_edge()];
                "fee > LVR only"
            }
            label."chk" {
                input type="checkbox" name="quote_only" value="true" checked[fl.quote_only()];
                "quote-only fees"
            }
            input type="hidden" name="sort" value=(fl.sort_key());
            button type="submit" { "Apply" }
        }
    }
}

fn sortable(label: &str, key: &str, fl: &Filters) -> Markup {
    let on = fl.sort_key() == key;
    let href = format!(
        "/?sort={}&max_risk={}&min_opp={}&limit={}{}",
        key, fl.max_risk(), fl.min_opp(), fl.limit(),
        if fl.positive_lvr_edge() { "&positive_lvr_edge=true" } else { "" }
    );
    html! { th class=(if on { "on" } else { "" }) { a href=(href) { (label) @if on { (PreEscaped(" ↓")) } } } }
}

fn table(rows: &[PoolScore], fl: &Filters) -> Markup {
    html! {
        div."wrap" {
            table {
                thead { tr {
                    th."l" { "#" }
                    th."l" { "pool" }
                    th."l" { "address" }
                    (sortable("adj", "adjusted", fl))
                    (sortable("opp", "opportunity", fl))
                    (sortable("risk", "risk", fl))
                    (sortable("fee/d", "fee", fl))
                    (sortable("floor", "floor", fl))
                    th { "cv" }
                    th { "turn" }
                    (sortable("σ/day", "sigma", fl))
                    (sortable("LVR", "lvr", fl))
                    (sortable("edge", "edge_lvr", fl))
                    th { "brkevn" }
                    th { "bin" }
                    th."grow" { "flags" }
                } }
                tbody {
                    @for (i, r) in rows.iter().enumerate() {
                        tr {
                            td."l idx" { (i + 1) }
                            td."l name" { a href={ "/pool/" (r.pool) } { (r.name) } }
                            td."l" { (meteora_link(&r.pool)) }
                            td."key" { (f(Some(r.adjusted), 1)) }
                            td."mute" { (f(Some(r.opportunity), 1)) }
                            td { span class={ "rk " (risk_band(r.risk)) } { (f(Some(r.risk), 1)) } }
                            td {
                                (f(r.fee_day_pct, 2)) "%"
                                @if r.quote_only_fees.unwrap_or(false) {
                                    span."q" title="fees paid in the quote token only" { "Q" }
                                }
                            }
                            td { (f(r.floor_pct, 2)) }
                            td."mute" { (f(r.cv, 2)) }
                            td."mute" { (f(r.turnover, 1)) "x" }
                            td { (pct(r.sigma_daily)) }
                            td."mute" { (f(r.lvr_daily_pct, 2)) }
                            td class={ "lead " (edge_class(r.edge_lvr_pct)) } {
                                (signed(r.edge_lvr_pct, 2)) }
                            td class=(brk_class(r.breakeven_turnover, r.turnover)) { (f(r.breakeven_turnover, 1)) "x" }
                            td."mute" { (r.bin_step.unwrap_or(0)) }
                            td."grow" { div."flags" {
                                @let all = r.risk_flags.as_deref().unwrap_or(&[]);
                                @for fg in all.iter().take(FLAG_LIMIT) {
                                    span class={ "flag " (flag_class(fg)) } { (fg) }
                                }
                                @if all.len() > FLAG_LIMIT {
                                    span."more" title=(all.join(", ")) {
                                        "+" (all.len() - FLAG_LIMIT) }
                                }
                            } }
                        }
                    }
                }
            }
        }
    }
}
