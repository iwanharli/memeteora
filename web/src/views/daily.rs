//! Day-by-day view of the book, as a calendar or a bar chart.
//!
//! Both are rendered server-side and toggled with CSS - no charting library and
//! no client-side data. The calendar is the better read for "which days were
//! bad"; the chart is the better read for "is this trending".
use chrono::{Datelike, NaiveDate};
use maud::{html, Markup};

use super::{signed, usd};
use crate::models::DailyPnl;

const DOW: [&str; 7] = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

fn cls(v: f64) -> &'static str {
    if v > 0.0 { "pos" } else if v < 0.0 { "neg" } else { "dim" }
}

pub fn section(days: &[DailyPnl]) -> Markup {
    if days.is_empty() {
        return html! {};
    }
    let total: f64 = days.iter().filter_map(|d| d.pnl).sum();
    let fees: f64 = days.iter().filter_map(|d| d.fees).sum();
    let wins = days.iter().filter(|d| d.pnl.unwrap_or(0.0) > 0.0).count();
    let scored = days.iter().filter(|d| d.pnl.unwrap_or(0.0) != 0.0).count();
    let best = days.iter().max_by(|a, b| {
        a.pnl.unwrap_or(f64::MIN).partial_cmp(&b.pnl.unwrap_or(f64::MIN)).unwrap()
    });

    // the most recent month present, which is what the calendar shows
    let last = days.last().unwrap().day;

    html! {
        h2 { "Daily" span."dim" { " — PnL against holding, day by day" } }
        div."daily" {
            div."daily-head" {
                div."daily-stats" {
                    div { span."k" { "period PnL" }
                          div class={ "v " (cls(total)) } { (signed(Some(total), 2)) } }
                    div { span."k" { "fees" } div."v pos" { (usd(Some(fees))) } }
                    div { span."k" { "up days" } div."v" { (wins) "/" (scored) } }
                    div { span."k" { "best day" }
                          div class={ "v " (cls(best.and_then(|b| b.pnl).unwrap_or(0.0))) } {
                            (signed(best.and_then(|b| b.pnl), 2)) } }
                }
                div."daily-tabs" {
                    input #"tab-cal" type="radio" name="dailyview" checked;
                    label for="tab-cal" { "Calendar" }
                    input #"tab-bar" type="radio" name="dailyview";
                    label for="tab-bar" { "Chart" }
                }
            }
            div."daily-body" {
                div."cal" { (calendar(days, last)) }
                div."bars" { (bars(days)) }
            }
        }
    }
}

fn calendar(days: &[DailyPnl], anchor: NaiveDate) -> Markup {
    let (y, m) = (anchor.year(), anchor.month());
    let first = NaiveDate::from_ymd_opt(y, m, 1).unwrap();
    let lead = first.weekday().num_days_from_sunday() as u32;
    let in_month = |d: &&DailyPnl| d.day.year() == y && d.day.month() == m;
    let month_total: f64 = days.iter().filter(in_month).filter_map(|d| d.pnl).sum();
    let days_in_month = match m {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        _ => if (y % 4 == 0 && y % 100 != 0) || y % 400 == 0 { 29 } else { 28 },
    };

    html! {
        div."cal-head" {
            strong { (first.format("%B %Y").to_string()) }
            span."dim" { "month "
                span class=(cls(month_total)) { (signed(Some(month_total), 2)) } }
        }
        div."cal-grid" {
            @for d in DOW { div."cal-dow" { (d) } }
            @for _ in 0..lead { div."cal-pad" {} }
            @for dom in 1..=days_in_month {
                @let date = NaiveDate::from_ymd_opt(y, m, dom).unwrap();
                @let row = days.iter().find(|d| d.day == date);
                @let pnl = row.and_then(|r| r.pnl);
                div class={ "cal-cell " (match pnl {
                        Some(v) if v > 0.0 => "c-pos",
                        Some(v) if v < 0.0 => "c-neg",
                        Some(_) => "c-flat",
                        None => "c-none" }) } {
                    span."cal-d" { (dom) }
                    @match pnl {
                        Some(v) => {
                            span class={ "cal-v " (cls(v)) } { (signed(Some(v), 2)) }
                            span."cal-n" { (row.map(|r| r.positions).unwrap_or(0))
                                @if row.map(|r| r.positions).unwrap_or(0) == 1 { " position" }
                                @else { " positions" } }
                        }
                        None => { span."cal-v dim" { "–" } }
                    }
                }
            }
        }
    }
}

/// Inline SVG: a bar per day, zero line in the middle, scaled to the largest
/// absolute move so a single big day cannot flatten the rest into nothing.
fn bars(days: &[DailyPnl]) -> Markup {
    let peak = days.iter()
        .filter_map(|d| d.pnl)
        .fold(0.0_f64, |a, b| a.max(b.abs()))
        .max(0.01);
    let n = days.len().max(1);
    let (w, h) = (760.0_f64, 190.0_f64);
    let bw = (w / n as f64).min(46.0);
    let mid = h / 2.0;

    html! {
        svg."barchart" viewBox={ "0 0 " (w) " " (h + 26.0) } preserveAspectRatio="none" {
            line x1="0" y1=(mid) x2=(w) y2=(mid) stroke="currentColor"
                 stroke-opacity="0.25" stroke-width="1" {}
            @for (i, d) in days.iter().enumerate() {
                @let v = d.pnl.unwrap_or(0.0);
                @let bh = (v.abs() / peak * (mid - 8.0)).max(if v == 0.0 { 0.0 } else { 1.5 });
                @let x = i as f64 * bw + bw * 0.18;
                @let y = if v >= 0.0 { mid - bh } else { mid };
                rect x=(x) y=(y) width=(bw * 0.64) height=(bh) rx="2"
                     class=(if v >= 0.0 { "b-pos" } else { "b-neg" }) {
                    title { (d.day.format("%d %b").to_string()) " · "
                            (signed(Some(v), 2)) " · " (d.positions) " positions" }
                }
                @if n <= 21 || i % ((n / 14).max(1)) == 0 {
                    text x=(x + bw * 0.32) y=(h + 16.0) text-anchor="middle"
                         class="b-label" { (d.day.format("%-d/%-m").to_string()) }
                }
            }
        }
        p."note" { "Scaled to the largest absolute day (" (usd(Some(peak)))
                   "), so a single outlier cannot flatten the rest." }
    }
}
