use maud::{html, Markup};

use super::{f, meteora_link, signed, usd};
use crate::models::{BookState, ClosedPosition, PaperPosition};

/// Simulated portfolio. Laid out like Meteora's own portfolio page, with one
/// column it does not have: PnL against simply holding the tokens.
///
/// Meteora reports PnL against deposit value, which flatters every position in
/// a rising market and punishes every one in a falling market regardless of
/// whether LPing was the right call. The only question that matters is whether
/// providing liquidity beat doing nothing with the same tokens.
pub fn page(rows: &[PaperPosition], closed: &[ClosedPosition],
            book: Option<&BookState>) -> Markup {
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
                    div."k" { "Recommended — PnL vs holding" }
                    div class={ "big " (cls(picks.pnl)) } {
                        (signed(Some(picks.pnl), 2))
                        span."pct" { (signed(Some(pick_pct), 2)) "%" }
                    }
                    div."row3" {
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
                                  " · " span class=(cls(core.pnl)) { (signed(Some(core.pnl), 2)) } } }
                            div { span."k" { "satellite" } div."v" { (usd(Some(sat.cap)))
                                  " · " span class=(cls(sat.pnl)) { (signed(Some(sat.pnl), 2)) } } }
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

            @for g in ["core", "satellite", "rekomendasi", "barbell", "bersambung",
                       "kontrol-negatif", "uji-bentuk", "uji-lebar"] {
                (section(rows, g))
            }
            (section_other(rows))
            (closed_section(closed))
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
    let mut g = Group { cap: 0.0, pnl: 0.0, n: 0 };
    for r in rows.iter().filter(|r| r.strategy == name) {
        g.cap += r.capital_usd;
        g.pnl += r.net_pnl.unwrap_or(0.0);
        g.n += 1;
    }
    g
}

#[derive(PartialEq, Clone, Copy)]
enum Kind { Pick, Control, Experiment }

struct Group { cap: f64, pnl: f64, n: usize }

fn group(rows: &[PaperPosition], k: Kind) -> Group {
    let sel = rows.iter().filter(|r| kind(&r.strategy) == k);
    let mut g = Group { cap: 0.0, pnl: 0.0, n: 0 };
    for r in sel {
        g.cap += r.capital_usd;
        g.pnl += r.net_pnl.unwrap_or(0.0);
        g.n += 1;
    }
    g
}

fn cls(v: f64) -> &'static str {
    if v > 0.0 { "pos" } else if v < 0.0 { "neg" } else { "dim" }
}

fn label(group: &str) -> (&'static str, &'static str) {
    match group {
        "rekomendasi" => ("Recommended", "what the engine says to deploy into"),
        "kontrol-negatif" => ("Negative control", "red-flagged — if these win, the model is wrong"),
        "uji-bentuk" => ("Shape test", "same pool, same entry, only the distribution differs"),
        "uji-lebar" => ("Width test", "same pool, same shape, only the bin count differs"),
        "core" => ("Core", "verified, widely held, volatility under 10%/day — 70% of the book"),
        "satellite" => ("Satellite", "memecoins — 30% of the book, small stakes, fast upside"),
        "barbell" => ("Barbell", "one pool, three positions: concentrated core plus wide flanks — a shape no single position can express"),
        "bersambung" => ("Tiled", "one pool, three positions side by side to clear the 69-bin cap"),
        _ => ("Other", ""),
    }
}

fn section(rows: &[PaperPosition], group: &str) -> Markup {
    let subset: Vec<&PaperPosition> = rows.iter().filter(|r| r.strategy == group).collect();
    if subset.is_empty() {
        return html! {};
    }
    let (title, why) = label(group);
    html! {
        h2 { (title) " " span."dim" style="font-weight:400;font-size:12px" { "— " (why) } }
        (table(&subset))
        @if subset.len() > 1 { (subtotal(&subset)) }
    }
}

/// Positions that belong to one strategy have to be judged as one thing.
/// A flank sitting out of range is not a losing position, it is half a plan.
fn subtotal(rows: &[&PaperPosition]) -> Markup {
    let cap: f64 = rows.iter().map(|r| r.capital_usd).sum();
    let val: f64 = rows.iter().filter_map(|r| r.value_usd).sum();
    let fees: f64 = rows.iter().filter_map(|r| r.fees_usd).sum();
    let hold: f64 = rows.iter().filter_map(|r| r.hold_usd).sum();
    let pnl: f64 = rows.iter().filter_map(|r| r.net_pnl).sum();
    let rent: f64 = rows.iter().filter_map(|r| r.rent_usd).sum();
    let inr = rows.iter().filter(|r| r.in_range.unwrap_or(false)).count();
    html! {
        p."note" style="margin-top:8px" {
            "Combined: " strong { (usd(Some(cap))) } " deployed · "
            "liquidity " strong { (usd(Some(val))) } " · "
            "fees " strong."pos" { (f(Some(fees), 3)) } " · "
            "if held " strong { (usd(Some(hold))) } " · "
            "rent locked " strong { (usd(Some(rent))) }
            " (" (format!("{:.0}", rent / cap * 100.0)) "% of capital) · "
            "net vs hold " strong class=(cls(pnl)) { (signed(Some(pnl), 2)) }
            " (" (signed(Some(pnl / cap * 100.0), 3)) "%) · "
            (inr) "/" (rows.len()) " in range"
        }
    }
}

fn section_other(rows: &[PaperPosition]) -> Markup {
    let known = ["core", "satellite", "rekomendasi", "barbell", "bersambung",
                 "kontrol-negatif", "uji-bentuk", "uji-lebar"];
    let subset: Vec<&PaperPosition> =
        rows.iter().filter(|r| !known.contains(&r.strategy.as_str())).collect();
    if subset.is_empty() {
        return html! {};
    }
    html! { h2 { "Other" } (table(&subset)) }
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
        _ => html! { span."dim" { "–" } },
    }
}

fn table(rows: &[&PaperPosition]) -> Markup {
    html! {
        div."wrap" {
            table style="min-width:1000px" {
                thead { tr {
                    th."l" { "pool" }
                    th."l" { "shape" }
                    th { "bins" }
                    th { "hrs" }
                    th { "deposit" }
                    th { "liquidity" }
                    th { "fees" }
                    th { "if held" }
                    th { "price PnL" }
                    th { "gas" }
                    th { "rent" }
                    th { "net vs hold" }
                    th { "%" }
                    th { "edge" }
                    th { "range" }
                    th."l" { "exit" }
                } }
                tbody {
                    @for r in rows {
                        tr {
                            td."l" { a href={ "/pool/" (r.pool) } { (r.name) }
                                @if r.blocked.unwrap_or(false) {
                                    span."flagdot" title="red-flagged pool" { "!" }
                                } }
                            td."l dim" { (r.shape) }
                            td { (r.n_bins) }
                            td."dim" { (f(r.hours_open, 1)) }
                            td { (usd(Some(r.capital_usd))) }
                            td { (usd(r.value_usd)) }
                            td class="pos" { (f(r.fees_usd, 3)) }
                            td."dim" { (usd(r.hold_usd)) }
                            td class=(cls(r.price_pnl().unwrap_or(0.0))) { (signed(r.price_pnl(), 2)) }
                            td."dim" { (f(r.gas_usd, 3)) }
                            td."dim" { (usd(r.rent_usd)) }
                            td class=(cls(r.net_pnl.unwrap_or(0.0))) {
                                strong { (signed(r.net_pnl, 2)) } }
                            td class=(cls(r.pnl_pct.unwrap_or(0.0))) { (signed(r.pnl_pct, 3)) "%" }
                            td."dim" { (signed(r.edge_lvr_pct, 2)) }
                            td { @if r.in_range.unwrap_or(false) {
                                    span."pill low" { "in" }
                                 } @else {
                                    span."pill high" {
                                        "out" @if let Some(h) = r.hours_out {
                                            " " (format!("{h:.0}h")) } }
                                 } }
                            td."l" { (exit_cell(r)) }
                        }
                    }
                }
            }
        }
    }
}


/// Closed positions are the only realised evidence the engine produces. Marked
/// positions can still recover; these cannot, so they are what the rules are
/// finally judged on.
fn closed_section(rows: &[ClosedPosition]) -> Markup {
    if rows.is_empty() {
        return html! {};
    }
    let pnl: f64 = rows.iter().filter_map(|r| r.realized_pnl).sum();
    let cap: f64 = rows.iter().map(|r| r.capital_usd).sum();
    html! {
        h2 { "Closed" span."dim" { " — realised, acted on automatically" } }
        div."wrap" {
            table style="min-width:960px" {
                thead { tr {
                    th."l" { "pool" } th."l" { "address" } th."l" { "shape" } th { "bins" } th { "gen" }
                    th { "held" } th { "deposit" } th { "fees" } th { "realised" }
                    th { "%" } th."l grow" { "why it was closed" }
                } }
                tbody {
                    @for r in rows {
                        tr {
                            td."l name" { (r.name) }
                            td."l" { (meteora_link(&r.pool)) }
                            td."l mute" { (r.shape) }
                            td."mute" { (r.n_bins) }
                            td."mute" { (r.generation) }
                            td."mute" { (f(r.hours_held, 1)) "h" }
                            td { (usd(Some(r.capital_usd))) }
                            td."pos" { (f(r.realized_fees, 2)) }
                            td class=(cls(r.realized_pnl.unwrap_or(0.0))) {
                                (signed(r.realized_pnl, 2)) }
                            td class=(cls(r.realized_pnl.unwrap_or(0.0))) {
                                (signed(r.realized_pnl.map(|p| p / r.capital_usd * 100.0), 2)) "%" }
                            td."l grow mute" { (r.close_reason.clone().unwrap_or_default()) }
                        }
                    }
                }
            }
        }
        p."note" {
            "Realised across " (rows.len()) " closed positions: "
            strong class=(cls(pnl)) { (signed(Some(pnl), 2)) }
            " on " (usd(Some(cap))) " deployed ("
            (signed(Some(pnl / cap.max(1.0) * 100.0), 2)) "%). These were closed by the "
            "rules, not by hand — every one names the mechanism that triggered it."
        }
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
            table style="min-width:940px" {
                thead { tr {
                    th."l" { "pool" } th."l" { "address" } th."l" { "sleeve" } th { "bin step" } th { "fee tier" }
                    th { "bins" } th { "deployed" } th { "share" } th { "value now" }
                    th."l grow" { "composition now" }
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
                            td."l grow" {
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
