use maud::{html, Markup, PreEscaped, DOCTYPE};

pub fn shell(title: &str, subtitle: Markup, body: Markup) -> Markup {
    html! {
        (DOCTYPE)
        html lang="en" {
            head {
                meta charset="utf-8";
                meta name="viewport" content="width=device-width, initial-scale=1";
                title { (title) " · memet" }
                style { (PreEscaped(CSS)) }
            }
            body {
                header {
                    div."brand" {
                        a href="/" { "memet" }
                        span."tag" { "DLMM screener" }
                        span."nav" { a href="/" { "Screener" } a href="/portfolio" { "Portfolio" } }
                    }
                    div."sub" { (subtitle) }
                }
                main { (body) }
                div."live" {
                    span."dot" {}
                    span."age" title="how old the newest data is" { "…" }
                    button."pause" type="button" { "pause" }
                }
                script { (PreEscaped(REFRESH_JS)) }
                footer {
                    "Estimates from public data. Not investment advice — verify every pool before deploying capital."
                }
            }
        }
    }
}

/// Swaps <main> in place rather than reloading: a full reload throws away the
/// scroll position, and on a long table that is the whole page. Refreshing is
/// paused while the tab is hidden, and can be paused by hand - a table that
/// reorders itself under the cursor is worse than a stale one.
const REFRESH_JS: &str = r#"
(function () {
  var EVERY = 60000, paused = false, timer = null;
  var dot = document.querySelector('.live .dot');
  var age = document.querySelector('.live .age');
  var btn = document.querySelector('.live .pause');
  var stampedAt = Date.now();

  function marked() {
    var el = document.querySelector('.sub');
    return el ? el.textContent : '';
  }
  function tick() {
    var s = Math.round((Date.now() - stampedAt) / 1000);
    age.textContent = paused ? 'paused'
      : (s < 60 ? s + 's ago' : Math.floor(s / 60) + 'm ago');
  }
  async function refresh() {
    if (paused || document.hidden) return;
    try {
      dot.classList.add('busy');
      var r = await fetch(location.href, { headers: { 'x-partial': '1' } });
      if (!r.ok) return;
      var doc = new DOMParser().parseFromString(await r.text(), 'text/html');
      var next = doc.querySelector('main'), cur = document.querySelector('main');
      if (next && cur && next.innerHTML !== cur.innerHTML) {
        var y = window.scrollY;
        cur.innerHTML = next.innerHTML;
        window.scrollTo(0, y);
      }
      var sub = doc.querySelector('.sub');
      if (sub) document.querySelector('.sub').textContent = sub.textContent;
      stampedAt = Date.now();
    } catch (e) {
      /* offline or server restarting - try again next tick */
    } finally {
      dot.classList.remove('busy');
      tick();
    }
  }
  btn.addEventListener('click', function () {
    paused = !paused;
    btn.textContent = paused ? 'resume' : 'pause';
    dot.classList.toggle('off', paused);
    tick();
  });
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) refresh();
  });
  timer = setInterval(function () { refresh(); }, EVERY);
  setInterval(tick, 1000);
  tick();
})();
"#;

const CSS: &str = r#"
/* Fonts: one proportional sans everywhere. `tabular-nums` gives figures equal
   widths so columns still align perfectly - a monospace face aligns too but
   reads as a code editor, not an instrument. Avoid -apple-system/ui-monospace:
   in some Chrome builds they resolve to a serif. */
:root{
  --ui:system-ui,"Helvetica Neue",Helvetica,Arial,sans-serif;

  --bg:#0a0b0e; --panel:#111318; --panel2:#161920; --raise:#1b1f27;
  --line:#1e222b; --line2:#2a303b;
  --ink:#f2f4f8; --ink2:#9aa3b2; --dim:#646d7d;
  --pos:#31d18a; --neg:#ff6257; --warn:#ffb020;
  --accent:#5b8cff;
}
:root[data-theme="light"]{
  --bg:#f7f7f5; --panel:#fff; --panel2:#fafaf8; --raise:#f2f2ef;
  --line:#e8e6e1; --line2:#d6d3cc;
  --ink:#16181d; --ink2:#5a6070; --dim:#8b909c;
  --pos:#0f8a54; --neg:#cf3b2c; --warn:#a06a00;
  --accent:#2f5fd0;
}
:root{color-scheme:dark}
:root[data-theme="light"]{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 var(--ui);
  -webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;
  font-variant-numeric:tabular-nums}
a{color:inherit;text-decoration:none}

/* ---------- header ---------- */
header{height:52px;padding:0 20px;border-bottom:1px solid var(--line);
  background:var(--bg);display:flex;align-items:center;gap:26px;
  position:sticky;top:0;z-index:30}
.brand{display:flex;align-items:baseline;gap:9px}
.brand>a{font-size:15px;font-weight:600;letter-spacing:-.01em;color:var(--ink)}
.tag{font-size:10px;color:var(--dim);letter-spacing:.04em}
.nav{display:flex;gap:4px}
.nav a{font-size:13.5px;color:var(--ink2);padding:5px 10px;border-radius:6px;font-weight:500}
.nav a:hover{background:var(--panel);color:var(--ink)}
.sub{margin-left:auto;font-size:12px;color:var(--dim)}
main{padding:18px 20px 56px;max-width:1680px;margin:0 auto}
footer{padding:16px 20px 30px;font-size:11.5px;color:var(--dim);border-top:1px solid var(--line)}

/* ---------- stat strip ---------- */
.cards{display:flex;flex-wrap:wrap;gap:0;margin-bottom:16px;
  background:var(--panel);border:1px solid var(--line);border-radius:8px;overflow:hidden}
.card{padding:11px 20px;min-width:120px;border-right:1px solid var(--line);flex:0 0 auto}
.card:last-child{border-right:0}
.card .k{font-size:11px;color:var(--dim);font-weight:500}
.card .v{font-size:20px;font-weight:600;margin-top:1px;letter-spacing:-.02em;line-height:1.2}

/* ---------- filters ---------- */
.filters{display:flex;flex-wrap:wrap;gap:7px;align-items:center;margin-bottom:12px}
.filters label{font-size:12.5px;color:var(--dim)}
.filters input[type=number]{width:62px}
.filters input,.filters select{background:var(--panel);color:var(--ink);
  border:1px solid var(--line2);border-radius:6px;padding:5px 8px;font:13px var(--ui);
  font-variant-numeric:tabular-nums}
.filters input:focus{outline:none;border-color:var(--accent)}
.filters button{background:var(--accent);color:#fff;border:0;border-radius:6px;
  padding:6px 14px;font:13px var(--ui);font-weight:600;cursor:pointer}
.filters button:hover{filter:brightness(1.1)}
.chk{display:flex;align-items:center;gap:6px;font-size:12.5px;color:var(--ink2);
  cursor:pointer;padding:0 4px}
.chk input{accent-color:var(--accent);margin:0}

/* ---------- table ---------- */
.wrap{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:8px}
table{border-collapse:separate;border-spacing:0;width:100%;min-width:1120px}
th{font-size:10.5px;color:var(--dim);font-weight:600;text-align:right;
  padding:9px 10px;white-space:nowrap;background:var(--panel2);
  border-bottom:1px solid var(--line2);position:sticky;top:0;z-index:5}
td{padding:7px 10px;text-align:right;white-space:nowrap;font-size:13px;color:var(--ink2);
  border-bottom:1px solid var(--line)}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover td{background:var(--panel2)}
th:first-child,td:first-child,th.l,td.l{text-align:left}
/* the flag column absorbs spare width so the figures stay grouped */
th.grow,td.grow{width:99%;text-align:left;padding-left:22px}
th a{color:var(--dim)} th a:hover,th.on a{color:var(--ink)}

/* hierarchy: identity and the deciding number carry weight, the rest recede */
td.name{font-size:13.5px;font-weight:500;color:var(--ink)}
td.name a:hover{color:var(--accent)}
td.key{font-weight:600;color:var(--ink)}
td.lead{font-size:13.5px;font-weight:600}
td.idx{color:var(--dim);font-size:12px;width:34px}
td.mute{color:var(--dim)}

.pos{color:var(--pos)} .neg{color:var(--neg)} .dim{color:var(--dim)}
.rk{font-weight:600}
.rk.low{color:var(--pos)} .rk.mid{color:var(--warn)} .rk.high{color:var(--neg)}

/* ---------- chips ---------- */
.flags{display:flex;gap:5px;align-items:center;flex-wrap:nowrap;overflow:hidden}
.flag{font-size:11px;line-height:1.7;padding:0 7px;border-radius:4px;
  background:var(--raise);color:var(--ink2);white-space:nowrap}
.flag.sev{background:color-mix(in srgb,var(--neg) 15%,transparent);color:var(--neg)}
.flag.good{background:color-mix(in srgb,var(--pos) 15%,transparent);color:var(--pos)}
.more{font-size:11px;color:var(--dim)}
/* the address links out to Meteora; muted so it never competes with the name */
/* ---------- daily ---------- */
.daily{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  overflow:hidden}
.daily-head{display:flex;flex-wrap:wrap;gap:16px;align-items:center;
  justify-content:space-between;padding:13px 16px;border-bottom:1px solid var(--line);
  background:var(--panel2)}
.daily-stats{display:flex;gap:28px;flex-wrap:wrap}
.daily-stats .k{font-size:10.5px;color:var(--dim);font-weight:500}
.daily-stats .v{font-size:16px;font-weight:600;margin-top:1px}
/* radios drive the toggle: no script, and the state survives a page swap */
.daily-tabs{display:inline-flex;background:var(--bg);border:1px solid var(--line2);
  border-radius:8px;padding:2px}
.daily-tabs input{position:absolute;opacity:0;pointer-events:none}
.daily-tabs label{font-size:12.5px;color:var(--dim);padding:5px 14px;border-radius:6px;
  cursor:pointer;user-select:none}
.daily-tabs label:hover{color:var(--ink)}
#tab-cal:checked ~ label[for="tab-cal"],
#tab-bar:checked ~ label[for="tab-bar"]{background:var(--panel);color:var(--ink)}
.daily-body{padding:14px 16px 16px}
.daily-body .bars{display:none}
.daily:has(#tab-bar:checked) .cal{display:none}
.daily:has(#tab-bar:checked) .bars{display:block}

.cal-head{display:flex;justify-content:space-between;align-items:baseline;
  margin-bottom:10px;font-size:13.5px}
.cal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:5px}
.cal-dow{font-size:10.5px;color:var(--dim);text-align:center;padding-bottom:2px}
.cal-pad{min-height:62px}
.cal-cell{min-height:62px;border:1px solid var(--line);border-radius:7px;padding:6px 8px;
  display:flex;flex-direction:column;gap:1px;background:var(--bg)}
.cal-d{font-size:11px;color:var(--dim)}
.cal-v{font-size:14px;font-weight:640;margin-top:auto}
.cal-n{font-size:10px;color:var(--dim)}
.c-pos{border-color:color-mix(in srgb,var(--pos) 45%,transparent);
  background:color-mix(in srgb,var(--pos) 8%,var(--bg))}
.c-neg{border-color:color-mix(in srgb,var(--neg) 45%,transparent);
  background:color-mix(in srgb,var(--neg) 8%,var(--bg))}
.c-none{opacity:.4}

.barchart{width:100%;height:230px;color:var(--ink2);display:block}
.b-pos{fill:var(--pos)} .b-neg{fill:var(--neg)}
.b-label{fill:var(--dim);font-size:9px;font-family:var(--ui)}

.rng{display:flex;flex-direction:column;gap:2px;min-width:150px}
.rng-ids{font-size:11.5px;color:var(--ink2)}
.rng-px{font-size:10.5px;color:var(--dim)}
.rng-bar{position:relative;height:3px;border-radius:2px;background:var(--line2)}
.rng-dot{position:absolute;top:-2px;width:7px;height:7px;border-radius:50%;
  background:var(--accent);transform:translateX(-50%)}
.addr{font-size:11.5px;color:var(--dim);font-family:Menlo,Consolas,monospace;
  border-bottom:1px dotted var(--line2)}
.addr:hover{color:var(--accent);border-bottom-color:var(--accent)}
.pill{display:inline-block;padding:1px 8px;border-radius:4px;font-size:12px;font-weight:600;
  background:var(--raise);color:var(--ink2)}
.pill.low{background:color-mix(in srgb,var(--pos) 15%,transparent);color:var(--pos)}
.pill.mid{background:color-mix(in srgb,var(--warn) 15%,transparent);color:var(--warn)}
.pill.high{background:color-mix(in srgb,var(--neg) 15%,transparent);color:var(--neg)}
.q{display:inline-block;margin-left:5px;padding:0 4px;border-radius:3px;font-size:10px;
  font-weight:700;background:color-mix(in srgb,var(--pos) 18%,transparent);color:var(--pos);
  vertical-align:1px}
/* a marker, not a bullet: inline-flex keeps it on the text baseline instead of
   floating below it like a rendering artefact */
.flagdot{display:inline-flex;align-items:center;justify-content:center;margin-left:7px;
  width:15px;height:15px;border-radius:4px;font-size:10px;font-weight:700;
  background:color-mix(in srgb,var(--neg) 18%,transparent);color:var(--neg);
  vertical-align:-2px}

/* ---------- portfolio ---------- */
.hero{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:12px;
  margin-bottom:16px}
.hero-main{background:var(--panel);border:1px solid var(--line);border-radius:8px;
  padding:16px 18px}
.hero-main .k{font-size:11px;color:var(--dim);font-weight:500}
.hero-main .big{font-size:30px;font-weight:600;letter-spacing:-.03em;margin:2px 0 15px;
  line-height:1.15}
.hero-main .big .pct{font-size:14px;font-weight:600;opacity:.8;margin-left:6px}
.row3{display:flex;gap:28px;flex-wrap:wrap;border-top:1px solid var(--line);padding-top:11px}
.row3 .k{font-size:11px;color:var(--dim);font-weight:500}
.row3 .v{font-size:15px;font-weight:600;margin-top:1px}

/* ---------- misc ---------- */
.mixbar{display:flex;height:5px;border-radius:3px;overflow:hidden;width:150px;
  background:var(--raise)}
.mix-b{background:var(--warn)} .mix-q{background:var(--accent)}
.mixlab{display:block;font-size:11px;color:var(--dim);margin-top:3px}
.capbar{display:flex;flex-wrap:wrap;gap:2px;border-radius:8px;overflow:hidden;border:1px solid var(--line)}
/* flex alone squeezed the small segments until their labels were ellipsised;
   a min-width keeps every figure readable and lets the large one absorb the rest */
.seg{padding:11px 14px;min-width:132px;background:var(--panel);display:flex;
  flex-direction:column;gap:1px;border-right:1px solid var(--line)}
.seg:last-child{border-right:0}
.seg-l{font-size:10.5px;color:var(--dim);white-space:nowrap}
.seg-v{font-size:15px;font-weight:600;color:var(--ink)}
.seg-p{font-size:11px;color:var(--dim)}
.s-dep{background:color-mix(in srgb,var(--accent) 12%,var(--panel))}
.s-rent{background:color-mix(in srgb,var(--warn) 10%,var(--panel))}
.s-usdc{background:color-mix(in srgb,var(--pos) 10%,var(--panel))}
.s-sol{background:color-mix(in srgb,var(--pos) 18%,var(--panel))}
h2{font-size:14px;margin:26px 0 8px;font-weight:600;color:var(--ink);letter-spacing:-.01em}
h2 .dim{font-weight:400;font-size:12.5px}
.meta{display:flex;flex-wrap:wrap;gap:26px;background:var(--panel);
  border:1px solid var(--line);border-radius:8px;padding:14px 18px;font-size:13.5px}
.meta div span{display:block;font-size:11px;color:var(--dim);margin-bottom:1px;font-weight:500}
.empty{padding:40px;text-align:center;color:var(--dim);font-size:13px}
.note{font-size:12.5px;color:var(--ink2);margin-top:10px;line-height:1.75;max-width:1100px}
.note strong{color:var(--ink);font-weight:600}
code{background:var(--raise);border-radius:4px;padding:1px 5px;
  font:12px Menlo,Consolas,monospace;color:var(--ink)}
.live{position:fixed;right:14px;bottom:14px;z-index:40;display:flex;align-items:center;
  gap:8px;background:var(--panel);border:1px solid var(--line2);border-radius:20px;
  padding:5px 11px 5px 10px;font-size:11.5px;color:var(--dim);box-shadow:var(--shadow)}
.live .dot{width:7px;height:7px;border-radius:50%;background:var(--pos);flex:0 0 auto}
.live .dot.busy{background:var(--accent)}
.live .dot.off{background:var(--dim)}
.live .pause{background:none;border:0;color:var(--dim);font:inherit;cursor:pointer;
  padding:0 0 0 2px;text-decoration:underline}
.live .pause:hover{color:var(--ink)}
::-webkit-scrollbar{height:10px;width:10px}
::-webkit-scrollbar-thumb{background:var(--line2);border-radius:5px}
::-webkit-scrollbar-thumb:hover{background:var(--dim)}
::-webkit-scrollbar-track{background:transparent}
@media (max-width:640px){main{padding:12px 10px 40px}header{padding:0 12px;gap:14px}
  .sub{display:none}.hero-main .big{font-size:25px}}
"#;
