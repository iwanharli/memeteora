use maud::{html, Markup};

use super::{f, meteora_link, signed, usd};
use crate::models::{BookState, ClosedPosition, DailyPnl, PaperPosition};

/// Simulated portfolio. Laid out like Meteora's own portfolio page, with one
/// column it does not have: PnL against simply holding the tokens.
///
/// Meteora reports PnL against deposit value, which flatters every position in
/// a rising market and punishes every one in a falling market regardless of
/// whether LPing was the right call. The only question that matters is whether
/// providing liquidity beat doing nothing with the same tokens.
pub fn page(rows: &[PaperPosition], closed: &[ClosedPosition],
            book: Option<&BookState>, daily: &[DailyPnl]) -> Markup {
    let deposit: f64 = rows.iter().map(|r| r.capital_usd).sum();
    let value: f64 = rows.iter().filter_map(|r| r.value_usd).sum();
    let fees: f64 = rows.iter().filter_map(|r| r.fees_usd).sum();
    let hold: f64 = rows.iter().filter_map(|r| r.hold_usd).sum();
    let pnl_hold: f64 = rows.iter().filter_map(|r| r.net_pnl).sum();
    let gas: f64 = rows.iter().filter_map(|r| r.gas_usd).sum();
    let rent: f64 = rows.iter().filter_map(|r| r.rent_usd).sum();
    let wins = rows.iter().filter(|r| r.pnl_vs_hold.unwrap_or(0.0) > 0.0).count();
    let in_range = rows.iter().filter(|r| r.in_range.unwrap_or(false)).count();
    let best = rows.iter().max_by(|a, b| {
        a.pnl_pct.unwrap_or(f64::MIN).partial_cmp(&b.pnl_pct.unwrap_or(f64::MIN)).unwrap()
    });

    let sub = html! {
        @match rows.first() {
            Some(r) => { "marked " (super::wib(r.marked_at).format("%Y-%m-%d %H:%M")) " WIB · simulated, no capital at risk" }
            None => { "no positions yet" }
        }
    };

    let body = html! {
        @if rows.is_empty() {
            div."wrap" { div."empty" {
                "No paper positions. Open one with "
                code { "python3 ingest/main.py paper open <pool> --capital 100" }
            } }
        } @else {
            @let picks = group(rows, Kind::Pick);
            @let ctrl = group(rows, Kind::Control);
            @let market = hold / deposit - 1.0;
            @let pick_pct = picks.pnl / picks.cap.max(1.0) * 100.0;
            @let ctrl_pct = ctrl.pnl / ctrl.cap.max(1.0) * 100.0;
            div."hero" {
                div."hero-main" {
                    div."k" { "Recommended — profit & loss" }
                    div class={ "big " (cls(picks.dep)) } {
                        (signed(Some(picks.dep), 2))
                        span."pct" { (signed(Some(picks.dep / picks.cap.max(1.0) * 100.0), 2)) "%" }
                    }
                    p."note" style="margin-top:2px" {
                        "(balance + claimable fees) − deposits, the same figure Meteora shows. "
                        "Excludes gas and refundable rent."
                    }
                    div."row3" {
                        div { span."k" { "vs holding" }
                              div class={ "v " (cls(picks.pnl)) } { (signed(Some(picks.pnl), 2))
                                  " " span."pct" { (signed(Some(pick_pct), 2)) "%" } } }
                        div { span."k" { "Positions" } div."v" { (picks.n) } }
                        div { span."k" { "Deployed" } div."v" { (usd(Some(picks.cap))) } }
                        div { span."k" { "Beat holding" } div."v" { (wins) "/" (rows.len()) } }
                        div { span."k" { "In range" } div."v" { (in_range) "/" (rows.len()) } }
                    }
                    @if let Some(b) = best {
                        p."note" style="margin-top:10px" {
                            "Best: " strong { (b.name) } " " (b.shape) " "
                            span class=(cls(b.pnl_pct.unwrap_or(0.0))) { (signed(b.pnl_pct, 3)) "%" }
                        }
                    }
                }
                @let core = sleeve(rows, "core");
                @let sat = sleeve(rows, "satellite");
                @if ctrl.n == 0 && (core.n + sat.n) > 0 {
                    div."hero-main" {
                        div."k" { "Sleeves — 70% core / 30% satellite" }
                        div."big" {
                            (format!("{:.0}", core.cap / (core.cap + sat.cap) * 100.0)) "/"
                            (format!("{:.0}", sat.cap / (core.cap + sat.cap) * 100.0))
                            span."pct" { " actual split" }
                        }
                        div."row3" {
                            div { span."k" { "core" } div."v" { (usd(Some(core.cap)))
                                  " · " span class=(cls(core.dep)) { (signed(Some(core.dep), 2)) } } }
                            div { span."k" { "satellite" } div."v" { (usd(Some(sat.cap)))
                                  " · " span class=(cls(sat.dep)) { (signed(Some(sat.dep), 2)) } } }
                            div { span."k" { "fees" } div."v pos" { (usd(Some(fees))) } }
                            div { span."k" { "gas" } div."v dim" { (f(Some(gas), 3)) } }
                        }
                    }
                } @else {
                div."hero-main" {
                    div."k" { "Controls — deliberately built to lose" }
                    div."big dim" {
                        (signed(Some(ctrl.pnl), 2))
                        span."pct" { (signed(Some(ctrl_pct), 2)) "%" }
                    }
                    div."row3" {
                        div { span."k" { "Spread vs picks" }
                              div class={ "v " (cls(pick_pct - ctrl_pct)) } {
                                (signed(Some(pick_pct - ctrl_pct), 2)) " pp" } }
                        div { span."k" { "Total value" } div."v" { (usd(Some(value + fees))) } }
                        div { span."k" { "Fees" } div."v pos" { (usd(Some(fees))) } }
                        div { span."k" { "Rent locked" } div."v dim" { (usd(Some(rent))) } }
                    }
                    p."note" style="margin-top:10px" {
                        "Gas " (f(Some(gas), 3)) " · total across every position "
                        span class=(cls(pnl_hold)) { (signed(Some(pnl_hold), 2)) }
                    }
                }
                }
            }
            (super::daily::section(daily))
            @if let Some(b) = book { (capital_bar(b)) }
            (deployed_detail(rows))
            p."note" {
                "Picks and controls are scored separately on purpose. This portfolio "
                "deliberately holds positions built to lose — a red-flagged pool and two "
                "over-narrow ranges — so the engine can be proved wrong. A combined total "
                "would average the engine against its own null hypothesis and mean nothing."
                br;
                "The tokens themselves moved "
                strong class=(cls(market)) { (signed(Some(market * 100.0), 2)) "%" }
                " over this window: " (usd(Some(deposit))) " deposited would be "
                (usd(Some(hold))) " if simply held. That is market direction, not a verdict "
                "on liquidity provision — which is why every figure here is measured "
                "against holding rather than against deposit."
            }

            (positions_card(rows, closed))
        }
    };
    super::layout::shell("Portfolio", sub, body)
}

/// The portfolio deliberately holds positions built to lose - a red-flagged
/// pool and two over-narrow ranges - so that the engine can be falsified.
/// Summing them with the picks produces a headline that means nothing.
fn kind(strategy: &str) -> Kind {
    match strategy {
        // sleeves are the live book; "rekomendasi" is the pre-sleeve name
        "core" | "satellite" | "rekomendasi" => Kind::Pick,
        "kontrol-negatif" | "uji-lebar" => Kind::Control,
        _ => Kind::Experiment,
    }
}

fn sleeve(rows: &[PaperPosition], name: &str) -> Group {
    let mut g = Group { cap: 0.0, pnl: 0.0, dep: 0.0, n: 0 };
    for r in rows.iter().filter(|r| r.strategy == name) {
        g.cap += r.capital_usd;
        g.pnl += r.net_pnl.unwrap_or(0.0);
        g.dep += r.pnl_vs_deposit().unwrap_or(0.0);
        g.n += 1;
    }
    g
}

#[derive(PartialEq, Clone, Copy)]
enum Kind { Pick, Control, Experiment }

struct Group { cap: f64, pnl: f64, dep: f64, n: usize }

fn group(rows: &[PaperPosition], k: Kind) -> Group {
    let sel = rows.iter().filter(|r| kind(&r.strategy) == k);
    let mut g = Group { cap: 0.0, pnl: 0.0, dep: 0.0, n: 0 };
    for r in sel {
        g.cap += r.capital_usd;
        g.pnl += r.net_pnl.unwrap_or(0.0);
        g.dep += r.pnl_vs_deposit().unwrap_or(0.0);
        g.n += 1;
    }
    g
}

fn cls(v: f64) -> &'static str {
    if v > 0.0 { "pos" } else if v < 0.0 { "neg" } else { "dim" }
}





/// Bin ids plus the prices they sit at, with a marker for where the price is
/// inside the range. The ids alone say nothing you can check against a chart.
fn range_cell(r: &PaperPosition) -> Markup {
    let (lo, hi) = (r.min_bin, r.max_bin);
    if lo.is_none() || hi.is_none() {
        return html! { span."dim" { "–" } };
    }
    let pos = r.range_position();
    html! {
        div."rng" {
            // Price leads: bin ids are the machine's index, prices are the
            // number the reader can compare against the market.
            span."rng-px" { (price(r.min_price)) " – " (price(r.max_price)) }
            @if let Some(p) = pos {
                div."rng-bar" {
                    div."rng-dot" style=(format!("left:{:.1}%", p * 100.0)) {}
                }
            }
            span."rng-ids" {
                @if let Some(q) = r.quote_symbol.as_ref() {
                    (q) " per " (r.base_symbol.clone().unwrap_or_default()) " · "
                }
                "bin " (lo.unwrap()) " … " (hi.unwrap())
            }
        }
    }
}

/// Prices span many orders of magnitude here - SOL near 100, a memecoin near
/// 0.00008 - so significant figures matter more than a fixed decimal count.
fn price(v: Option<f64>) -> String {
    match v {
        Some(x) if x >= 100.0 => format!("{x:.2}"),
        Some(x) if x >= 1.0 => format!("{x:.4}"),
        Some(x) if x >= 0.0001 => format!("{x:.6}"),
        Some(x) => format!("{x:.9}"),
        None => "–".into(),
    }
}

/// The reasons carry the mechanism, so they belong on the row rather than in a
/// separate report the reader has to go and find.
fn exit_cell(r: &PaperPosition) -> Markup {
    let reasons = r.exit_reasons.clone().unwrap_or_default();
    match r.exit_urgency.as_deref() {
        Some("hard") => html! {
            span."flag sev" title=(reasons.join(" · ")) { "close" }
        },
        Some("soft") => html! {
            span."flag" title=(reasons.join(" · ")) { "watch" }
        },
        _ => html! {},
    }
}





/// Where the budget actually sits. Rent is shown apart from cash because it is
/// a refundable deposit locked in the position accounts, not money that can be
/// spent - folding it into cash would make the SOL share look like 43% when
/// only $66.67 is actually liquid.
fn capital_bar(b: &BookState) -> Markup {
    let pct = |v: f64| if b.budget > 0.0 { v / b.budget * 100.0 } else { 0.0 };
    let seg = |label: &str, v: f64, class: &str| -> Markup {
        html! {
            div class={ "seg " (class) } style=(format!("flex:{:.4}", (v / b.budget).max(0.001))) {
                span."seg-l" { (label) }
                span."seg-v" { (usd(Some(v))) }
                span."seg-p" { (format!("{:.1}%", pct(v))) }
            }
        }
    };
    html! {
        h2 { "Capital" span."dim" { " — budget " (usd(Some(b.budget)))
             ", allocated " (super::wib(b.ts).format("%H:%M")) " WIB" } }
        div."capbar" {
            (seg("deployed", b.deployed, "s-dep"))
            (seg("rent (SOL)", b.rent_locked, "s-rent"))
            (seg("cash USDC", b.cash_usdc, "s-usdc"))
            (seg("cash SOL", b.cash_sol, "s-sol"))
        }
        p."note" {
            "Cash is held " strong { "70% USDC / 30% SOL" } ". The SOL leg is an "
            "obligation rather than a preference — Solana fees can only be paid in SOL — "
            "so the cash pile is sized so that its 30% share still covers the gas buffer: "
            code { "cash = gas ÷ 0.30" } ". "
            strong { "Rent" } " sits outside that split: it is a refundable deposit locked "
            "in the position accounts, so it is SOL you own but cannot spend."
            @if b.idle.abs() > 1.0 {
                br;
                "Unallocated: " strong { (usd(Some(b.idle))) }
                " — a sleeve could not place its full share at the position floor."
            }
        }
    }
}


/// What the deployed segment is actually made of. The capital bar says how much
/// is at work; this says where, at what bin step, and in which token — the last
/// mattering because a DLMM position converts as the price walks its range, so
/// a book that looks balanced on deposit can be entirely in one asset by now.
fn deployed_detail(rows: &[PaperPosition]) -> Markup {
    if rows.is_empty() {
        return html! {};
    }
    let total: f64 = rows.iter().map(|r| r.capital_usd).sum();
    // book-wide token mix, weighted by current position value
    let (mut base_usd, mut quote_usd) = (0.0, 0.0);
    for r in rows {
        if let (Some(v), Some(share)) = (r.value_usd, r.base_share()) {
            base_usd += v * share;
            quote_usd += v * (1.0 - share);
        }
    }
    let mix = base_usd + quote_usd;

    html! {
        div."wrap" style="margin-top:10px" {
            table."cap" {
                colgroup {
                    col style="width:12%"; col style="width:10%"; col style="width:8%";
                    col style="width:8%";  col style="width:8%";  col style="width:6%";
                    col style="width:10%"; col style="width:7%";  col style="width:10%";
                    col style="width:21%";
                }
                thead { tr {
                    th."l" { "pool" } th."l" { "address" } th."l" { "sleeve" } th { "bin step" } th { "fee tier" }
                    th { "bins" } th { "deployed" } th { "share" } th { "value now" }
                    th."l" { "composition now" }
                } }
                tbody {
                    @for r in rows {
                        @let share = r.base_share();
                        tr {
                            td."l name" { (r.name) }
                            td."l" { (meteora_link(&r.pool)) }
                            td."l mute" { (r.strategy) }
                            td { (r.bin_step.unwrap_or(0)) " bps" }
                            td."mute" { (f(r.base_fee_pct, 2)) "%" }
                            td."mute" { (r.n_bins) }
                            td { (usd(Some(r.capital_usd))) }
                            td."mute" { (format!("{:.1}%", r.capital_usd / total * 100.0)) }
                            td { (usd(r.value_usd)) }
                            td."l" {
                                @match share {
                                    Some(sh) => {
                                        div."mixbar" {
                                            div."mix-b" style=(format!("flex:{:.4}", sh.max(0.0005))) {}
                                            div."mix-q" style=(format!("flex:{:.4}", (1.0 - sh).max(0.0005))) {}
                                        }
                                        span."mixlab" {
                                            (format!("{:.0}%", sh * 100.0)) " "
                                            (r.base_symbol.clone().unwrap_or_default())
                                            " · " (format!("{:.0}%", (1.0 - sh) * 100.0)) " "
                                            (r.quote_symbol.clone().unwrap_or_default())
                                        }
                                    }
                                    None => { span."dim" { "–" } }
                                }
                            }
                        }
                    }
                }
            }
        }
        @if mix > 0.0 {
            p."note" {
                "Across the deployed book: " strong { (format!("{:.0}%", base_usd / mix * 100.0)) }
                " in base tokens, " strong { (format!("{:.0}%", quote_usd / mix * 100.0)) }
                " in quote (SOL/USDC). Positions are opened half in each, so any drift from "
                "50/50 is the market having walked the price through the range — up moves sell "
                "the base leg into quote, down moves buy it back."
            }
        }
    }
}


// ---------------------------------------------------------------- positions card
/// Live and closed positions in one card with a tab between them, following
/// the shape of Meteora's own portfolio: a header that carries the totals, then
/// rows whose primary value sits above its own context rather than beside it.
/// Two lines per cell is what lets sixteen facts fit without a horizontal
/// scroll bar.
fn positions_card(rows: &[PaperPosition], closed: &[ClosedPosition]) -> Markup {
    let deployed: f64 = rows.iter().map(|r| r.capital_usd).sum();
    let net: f64 = rows.iter().filter_map(|r| r.net_pnl).sum();
    let fees: f64 = rows.iter().filter_map(|r| r.fees_usd).sum();
    let net_pct = if deployed > 0.0 { net / deployed * 100.0 } else { 0.0 };
    let dep: f64 = rows.iter().filter_map(|r| r.pnl_vs_deposit()).sum();
    let dep_pct = if deployed > 0.0 { dep / deployed * 100.0 } else { 0.0 };

    let c_cap: f64 = closed.iter().map(|r| r.capital_usd).sum();
    let c_pnl: f64 = closed.iter().filter_map(|r| r.realized_pnl).sum();
    let c_fees: f64 = closed.iter().filter_map(|r| r.realized_fees).sum();

    html! {
        div."pcard" {
            div."ptabs" {
                input #"pos-live" type="radio" name="posview" checked;
                label for="pos-live" { "Live positions" }
                input #"pos-closed" type="radio" name="posview";
                label for="pos-closed" { "Closed" }
            }

            div."pane pane-live" {
                div."pcard-head" {
                    span."pcard-icon" { "◧" }
                    strong { "DLMM positions" }
                    div."pcard-stats" {
                        div { span."k" { "profit & loss" }
                              span class={ "v " (cls(dep)) } { (signed(Some(dep), 2))
                                  " " span."pct" { "(" (signed(Some(dep_pct), 2)) "%)" } } }
                        div { span."k" { "vs holding" }
                              span class={ "v " (cls(net)) } { (signed(Some(net), 2))
                                  " " span."pct" { "(" (signed(Some(net_pct), 2)) "%)" } } }
                        div { span."k" { "deployed" } span."v" { (usd(Some(deployed))) } }
                        div { span."k" { "fees" } span."v pos" { (usd(Some(fees))) } }
                        div { span."k" { "positions" } span."v" { (rows.len()) } }
                    }
                }
                @if rows.is_empty() {
                    div."empty" { "No open positions." }
                } @else {
                    (live_table(rows))
                }
            }

            div."pane pane-closed" {
                div."pcard-head" {
                    span."pcard-icon" { "◨" }
                    strong { "Closed positions" }
                    div."pcard-stats" {
                        div { span."k" { "realised" }
                              span class={ "v " (cls(c_pnl)) } { (signed(Some(c_pnl), 2)) } }
                        div { span."k" { "on" } span."v" { (usd(Some(c_cap))) } }
                        div { span."k" { "fees" } span."v pos" { (usd(Some(c_fees))) } }
                        div { span."k" { "closed" } span."v" { (closed.len()) } }
                    }
                }
                @if closed.is_empty() {
                    div."empty" { "Nothing closed yet." }
                } @else {
                    (closed_table(closed))
                }
            }
        }
    }
}

/// "6h ago", "2 days ago" - an absolute timestamp makes the reader do
/// arithmetic to answer the question they actually have.
fn ago(hours: Option<f64>) -> String {
    match hours {
        None => "–".into(),
        Some(h) if h < 1.0 => format!("{:.0}m ago", h * 60.0),
        Some(h) if h < 48.0 => format!("{h:.0}h ago"),
        Some(h) => format!("{:.0} days ago", h / 24.0),
    }
}

fn live_table(rows: &[PaperPosition]) -> Markup {
    html! {
        div."wrap plain" {
            table."pos" {
                colgroup {
                    col style="width:20%"; col style="width:11%"; col style="width:11%";
                    col style="width:12%"; col style="width:19%"; col style="width:9%";
                    col style="width:10%"; col style="width:8%";
                }
                thead { tr {
                    th."l" { "pool / position" }
                    th."l" { "profit & loss" }
                    th."l" { "vs holding" }
                    th."l" { "liquidity" }
                    th."l" { "range" }
                    th."l" { "fees" }
                    th."l" { "cost" }
                    th."l" { "status" }
                } }
                tbody {
                    @for r in rows {
                        tr {
                            td."l" {
                                div."two" {
                                    span."t1" { a href={ "/pool/" (r.pool) } { (r.name) }
                                        @if r.blocked.unwrap_or(false) {
                                            span."flagdot" title="red-flagged pool" { "!" } } }
                                    span."t2" {
                                        "Bin step " (r.bin_step.unwrap_or(0))
                                        " · Fee " (f(r.base_fee_pct, 2)) "%"
                                        " · " (r.strategy)
                                    }
                                    span."t3" { (meteora_link(&r.pool)) " · opened " (ago(r.hours_open)) }
                                }
                            }
                            @let dep = r.pnl_vs_deposit();
                            td."l" {
                                div."two" {
                                    span class={ "t1 " (cls(dep.unwrap_or(0.0))) } {
                                        (signed(dep, 2)) }
                                    span class={ "t2 " (cls(dep.unwrap_or(0.0))) } {
                                        (signed(dep.map(|d| d / r.capital_usd * 100.0), 3)) "%" }
                                }
                            }
                            td."l" {
                                div."two" {
                                    span class={ "t1 " (cls(r.net_pnl.unwrap_or(0.0))) } {
                                        (signed(r.net_pnl, 2)) }
                                    span class={ "t2 " (cls(r.pnl_pct.unwrap_or(0.0))) } {
                                        (signed(r.pnl_pct, 3)) "%" }
                                }
                            }
                            td."l" {
                                div."two" {
                                    span."t1" { (usd(r.value_usd)) }
                                    span."t2" { "deposit " (usd(Some(r.capital_usd))) }
                                    @if let Some(sh) = r.base_share() {
                                        span."t3" {
                                            (format!("{:.0}%", sh * 100.0)) " "
                                            (r.base_symbol.clone().unwrap_or_default())
                                            " · " (format!("{:.0}%", (1.0 - sh) * 100.0)) " "
                                            (r.quote_symbol.clone().unwrap_or_default())
                                        }
                                    }
                                }
                            }
                            td."l" { (range_cell(r)) }
                            td."l" {
                                div."two" {
                                    span."t1 pos" { (f(r.fees_usd, 3)) }
                                    span."t2" { (r.shape) " · " (r.n_bins) " bins" }
                                }
                            }
                            td."l" {
                                div."two" {
                                    span."t1 dim" { (usd(r.rent_usd)) }
                                    span."t2" { "rent, refundable" }
                                    span."t3" { "gas " (f(r.gas_usd, 3)) }
                                }
                            }
                            td."l" {
                                div."two" {
                                    span."t1" {
                                        @if r.in_range.unwrap_or(false) {
                                            span."pill low" { "in range" }
                                        } @else {
                                            span."pill high" { "out"
                                                @if let Some(h) = r.hours_out { " " (f(Some(h), 1)) "h" } }
                                        }
                                        (exit_cell(r))
                                    }
                                    @if let Some(fl) = r.exit_reasons.as_ref() {
                                        @if !fl.is_empty() {
                                            span."t2" { (fl[0].clone()) }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

fn closed_table(rows: &[ClosedPosition]) -> Markup {
    html! {
        div."wrap plain" {
            table."pos" {
                colgroup {
                    col style="width:22%"; col style="width:12%"; col style="width:13%";
                    col style="width:13%"; col style="width:40%";
                }
                thead { tr {
                    th."l" { "pool" }
                    th."l" { "realised" }
                    th."l" { "deposit" }
                    th."l" { "fees earned" }
                    th."l" { "why it was closed" }
                } }
                tbody {
                    @for r in rows {
                        tr {
                            td."l" {
                                div."two" {
                                    span."t1" { (r.name) }
                                    span."t2" { (r.shape) " · " (r.n_bins) " bins · gen " (r.generation) }
                                    span."t3" { (meteora_link(&r.pool)) " · held "
                                        (f(r.hours_held, 1)) "h" }
                                }
                            }
                            td."l" {
                                div."two" {
                                    span class={ "t1 " (cls(r.realized_pnl.unwrap_or(0.0))) } {
                                        (signed(r.realized_pnl, 2)) }
                                    span class={ "t2 " (cls(r.realized_pnl.unwrap_or(0.0))) } {
                                        (signed(r.realized_pnl.map(|p| p / r.capital_usd * 100.0), 2)) "%" }
                                }
                            }
                            td."l" { span."chip" { (usd(Some(r.capital_usd))) } }
                            td."l" { span."chip pos" { (f(r.realized_fees, 2)) } }
                            td."l mute" { (r.close_reason.clone().unwrap_or_default()) }
                        }
                    }
                }
            }
        }
    }
}
