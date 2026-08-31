pub mod layout;
pub mod dashboard;
pub mod detail;
pub mod daily;
pub mod portfolio;

/// A pool address, shortened for the table but linking out in full. The name
/// alone is ambiguous - one token often has several pools at different bin
/// steps, and they behave very differently.
pub fn meteora_link(pool: &str) -> maud::Markup {
    use maud::html;
    let short = if pool.len() > 12 {
        format!("{}…{}", &pool[..4], &pool[pool.len() - 4..])
    } else {
        pool.to_string()
    };
    html! {
        a."addr" href={ "https://www.meteora.ag/dlmm/" (pool) }
          target="_blank" rel="noreferrer noopener"
          title={ "Open " (pool) " on Meteora" } { (short) }
    }
}

/// Display timezone. Storage stays UTC in `timestamptz`; only rendering shifts.
/// WIB has never observed DST, so a fixed +07:00 is exact, not an approximation.
pub const WIB_OFFSET_SECS: i32 = 7 * 3600;

pub fn wib(dt: chrono::DateTime<chrono::Utc>) -> chrono::DateTime<chrono::FixedOffset> {
    dt.with_timezone(&chrono::FixedOffset::east_opt(WIB_OFFSET_SECS).expect("valid offset"))
}

/// Shared number formatting. `None` renders as a dim dash, never "null".
pub fn f(v: Option<f64>, dp: usize) -> String {
    match v {
        Some(x) => format!("{:.*}", dp, x),
        None => "–".into(),
    }
}

pub fn signed(v: Option<f64>, dp: usize) -> String {
    match v {
        Some(x) => format!("{:+.*}", dp, x),
        None => "–".into(),
    }
}

/// Exact dollars. `money()` abbreviates, which is right for pool TVL and wrong
/// for a $100 position where the cents are the entire result being measured.
pub fn usd(v: Option<f64>) -> String {
    match v {
        Some(x) => {
            let neg = x < 0.0;
            // round once, in cents - rounding the fraction separately let 59.996
            // print as "$59.100"
            let total = (x.abs() * 100.0).round() as i64;
            let (whole, cents) = (total / 100, total % 100);
            let mut s = whole.to_string();
            let mut out = String::new();
            while s.len() > 3 {
                let cut = s.len() - 3;
                out = format!(",{}{}", &s[cut..], out);
                s.truncate(cut);
            }
            format!("{}${}{}.{:02}", if neg { "-" } else { "" }, s, out, cents)
        }
        None => "–".into(),
    }
}

pub fn money(v: Option<f64>) -> String {
    match v {
        Some(x) if x >= 1e6 => format!("${:.2}M", x / 1e6),
        Some(x) if x >= 1e3 => format!("${:.0}k", x / 1e3),
        Some(x) => format!("${:.0}", x),
        None => "–".into(),
    }
}

/// Risk 0-100 -> a coarse band. Keeps colour logic in one place.
pub fn risk_band(r: f64) -> &'static str {
    if r < 12.0 { "low" } else if r < 25.0 { "mid" } else { "high" }
}

pub fn edge_class(e: Option<f64>) -> &'static str {
    match e {
        Some(x) if x > 0.0 => "pos",
        Some(_) => "neg",
        None => "dim",
    }
}
