"""
GST Rate Finder - Streamlit app
BBA FinTech Practical Assignment (Python + Pandas + Streamlit)

Type the name of any goods or service and see whether GST applies,
the GST rate, the HSN/SAC code and the notification it comes from.
Data: gst_data.csv, cleaned and validated by gst_parser.parse_gst_csv.
"""

import difflib
import html
import os
import re

import altair as alt
import pandas as pd
import streamlit as st

from gst_parser import COLUMNS, parse_gst_csv, template_csv

try:  # optional voice search (needs Chrome / Edge and microphone permission)
    from streamlit_mic_recorder import speech_to_text
except ImportError:
    speech_to_text = None

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(APP_DIR, "gst_data.csv")
RATES_AS_ON = "3 November 2026"
SLAB_CHOICES = [0.0, 3.0, 5.0, 18.0, 40.0]
EXAMPLES = ["Rice", "Laptop", "Fresh milk", "Cement", "Gym", "Petrol"]
MAX_CARDS = 20
NOT_FOUND = "Item not found — please check spelling or try a related term"

st.set_page_config(page_title="GST Rate Finder", page_icon="🧾", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 2rem; max-width: 1150px;}
.hero {background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 55%, #0e7490 100%);
       color: #fff; padding: 1.5rem 1.8rem; border-radius: 16px; margin-bottom: 1.1rem;}
.hero-title {font-size: 2rem; font-weight: 800; line-height: 1.2;}
.hero-sub {margin-top: .35rem; opacity: .92;}
.hero-chip {display: inline-block; margin-top: .7rem; background: rgba(255,255,255,.16);
            padding: .2rem .7rem; border-radius: 999px; font-size: .8rem;}
.card {background: #fff; border: 1px solid #e2e8f0; border-radius: 14px;
       padding: 1.1rem 1.25rem; margin-bottom: .9rem; box-shadow: 0 1px 2px rgba(15,23,42,.05);}
.card-head {display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem;}
.card-title {font-size: 1.2rem; font-weight: 700; color: #0f172a;}
.card-sub {color: #64748b; font-size: .88rem; margin-top: .15rem;}
.rate-big {font-size: 1.9rem; font-weight: 800; color: #1e40af; white-space: nowrap; text-align: right;}
.rate-big small {display: block; font-size: .72rem; font-weight: 600; color: #64748b;
                 text-transform: uppercase; letter-spacing: .05em;}
.rate-big.nil {color: #047857;}
.rate-big.out {color: #7c3aed;}
.status {display: inline-block; margin: .6rem 0 .2rem; padding: .3rem .8rem; border-radius: 999px;
         font-weight: 700; font-size: .92rem;}
.status.yes {background: #dbeafe; color: #1e3a8a;}
.status.no {background: #d1fae5; color: #065f46;}
.status.out {background: #ede9fe; color: #5b21b6;}
.card-desc {color: #334155; margin: .35rem 0 .7rem; font-size: .93rem;}
.tiles {display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .5rem;}
.tile {background: #f1f5f9; border-radius: 10px; padding: .5rem .7rem;}
.tile span {display: block; font-size: .7rem; text-transform: uppercase; letter-spacing: .05em; color: #64748b;}
.tile b {font-size: 1.05rem; color: #0f172a;}
.meta {margin-top: .75rem; font-size: .83rem; color: #475569; display: flex;
       flex-wrap: wrap; gap: .35rem .9rem; align-items: center;}
.meta a {color: #1e40af;}
.badge {padding: .12rem .55rem; border-radius: 999px; font-size: .76rem; font-weight: 600;
         background: #dcfce7; color: #166534;}
.slab {background: #fff; border: 1px solid #e2e8f0; border-top: 4px solid var(--c);
       border-radius: 12px; padding: .8rem 1rem; height: 100%;}
.slab b {font-size: 1.4rem; display: block; color: var(--c);}
.slab div {font-weight: 600; color: #0f172a;}
.slab small {color: #64748b;}
.bill-row {display: flex; justify-content: space-between; padding: .5rem 0;
           border-bottom: 1px dashed #e2e8f0; color: #334155;}
.bill-row.total {font-weight: 800; font-size: 1.2rem; color: #1e40af; border-bottom: none; padding-top: .8rem;}
.footer {margin-top: 2.5rem; padding-top: .8rem; border-top: 1px solid #e2e8f0;
         font-size: .8rem; color: #64748b;}
@media (max-width: 640px) {.tiles {grid-template-columns: repeat(2, minmax(0, 1fr));}
                           .hero-title {font-size: 1.5rem;}}
</style>
""", unsafe_allow_html=True)


# ---------------- helpers ----------------

def esc(value):
    return html.escape(str(value), quote=True)


def fmt_rate(value):
    if pd.isna(value):
        return "N/A"
    return "Nil" if value == 0 else f"{value:g}%"


def gst_status(row):
    """Return (label, css class) for the status pill."""
    if "outside" in row["tax_status"].lower():
        return "GST Not Applicable (Outside GST)", "out"
    if pd.notna(row["igst_rate"]) and row["igst_rate"] == 0:
        return "GST Not Applicable (Nil / Exempt)", "no"
    return "GST Applicable", "yes"


def code_label(row):
    return "SAC" if row["item_type"] == "Service" else "HSN"


def inr(amount):
    """Indian digit grouping: 1234567.5 -> ₹12,34,567.50"""
    sign = "-" if amount < 0 else ""
    whole, frac = f"{abs(amount):.2f}".split(".")
    if len(whole) > 3:
        head, groups = whole[:-3], [whole[-3:]]
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups)
    return f"{sign}₹{whole}.{frac}"


def hero(title, subtitle, chip=None):
    chip_html = f'<div class="hero-chip">{esc(chip)}</div>' if chip else ""
    st.markdown(
        f'<div class="hero"><div class="hero-title">{esc(title)}</div>'
        f'<div class="hero-sub">{esc(subtitle)}</div>{chip_html}</div>',
        unsafe_allow_html=True,
    )


def footer():
    st.markdown(
        '<div class="footer">⚠️ <b>Disclaimer:</b> results are for educational purposes only and must be '
        "verified with the latest GST notifications before any commercial or tax use. "
        f"Rates as on {RATES_AS_ON}. Source: CBIC Central Tax (Rate) notifications "
        "(9/2025, 10/2025, 15/2025, 16/2025 and later amendments) — see the Sources page.</div>",
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def load_csv(path, modified):  # "modified" refreshes the cache when the file changes
    return parse_gst_csv(path)


def current_data():
    if "upload" in st.session_state:
        return st.session_state["upload"]
    if os.path.exists(DATA_FILE):
        df, issues, summary = load_csv(DATA_FILE, os.path.getmtime(DATA_FILE))
        name = "gst_data.csv"
    else:
        df, issues, summary = parse_gst_csv(b"")
        name = "gst_data.csv (missing)"
    return {"df": df, "issues": issues, "summary": summary, "name": name}


# ---------------- search ----------------

def normalize(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(text).lower())).strip()


def singular(word):
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("es") and word[-3] in "sxzh":
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def terms_of(row):
    """Searchable phrases of a row: its name and each keyword."""
    phrases = [normalize(row["product_name"])]
    phrases += [normalize(k) for k in row["keywords"].split(",") if k.strip()]
    return [p for p in phrases if p]


def score_row(row, q, q_words):
    name = normalize(row["product_name"])
    phrases = terms_of(row)
    words = set(" ".join(phrases + [normalize(row["category"])]).split())
    words |= {singular(w) for w in words}
    if q == name or q in phrases[1:]:
        return 100
    if name.startswith(q):
        return 85
    if re.search(rf"\b{re.escape(q)}\b", name):
        return 75
    if any(re.search(rf"\b{re.escape(q)}\b", p) for p in phrases[1:]):
        return 65
    if q_words and all(w in words for w in q_words):
        return 50
    return 0


def search(df, query):
    """Return (ranked results, corrected term or None)."""
    q = normalize(query)
    if not q:
        return df, None

    digits = q.replace(" ", "")
    if digits.isdigit():
        hsn = df["hsn_code"]
        exact = df[hsn == digits]
        if not exact.empty:
            return exact, None
        prefix = df[hsn.apply(lambda h: bool(h) and (h.startswith(digits) or digits.startswith(h)))]
        return prefix, None

    def ranked(term):
        words = [singular(w) for w in term.split()]
        scores = df.apply(lambda r: score_row(r, term, words), axis=1)
        hits = df.assign(_score=scores)
        hits = hits[hits["_score"] > 0].sort_values(["_score", "product_name"], ascending=[False, True])
        return hits.drop(columns="_score")

    hits = ranked(q)
    if hits.empty and singular(q) != q:
        hits = ranked(singular(q))
    if not hits.empty:
        return hits, None

    # Spelling help: closest known word or phrase.
    vocab = set()
    for _, r in df.iterrows():
        for phrase in terms_of(r):
            vocab.add(phrase)
            vocab.update(w for w in phrase.split() if len(w) > 2)
    close = difflib.get_close_matches(q, vocab, n=1, cutoff=0.72)
    if not close and " " in q:  # try word by word
        fixed = [(difflib.get_close_matches(w, vocab, n=1, cutoff=0.72) or [w])[0] for w in q.split()]
        close = [" ".join(fixed)] if fixed != q.split() else []
    if close:
        hits = ranked(close[0])
        if not hits.empty:
            return hits, close[0]
    return df.iloc[0:0], None


def status_badge(status):
    return '<span class="badge">✔ Verified</span>' if status == "Verified" else ""


def product_card(r):
    label, css = gst_status(r)
    igst = r["igst_rate"]
    rate_css = "out" if css == "out" else ("nil" if css == "no" else "")
    rate_text = "N/A" if css == "out" else ("0%" if igst == 0 else fmt_rate(igst))
    tiles = "".join(
        f'<div class="tile"><span>{name}</span><b>{fmt_rate(r[col])}</b></div>'
        for name, col in [("CGST", "cgst_rate"), ("SGST / UTGST", "sgst_rate"),
                          ("IGST", "igst_rate"), ("Cess", "cess_rate")]
    ) if css != "out" else ""
    meta = [status_badge(r["verification_status"])]
    if r["notification_number"]:
        meta.append(f"<span>📜 {esc(r['notification_number'])}</span>")
    if r["effective_from"]:
        meta.append(f"<span>📅 Effective {esc(r['effective_from'])}</span>")
    url = r["source_url"]
    if url.startswith(("https://", "http://")):
        meta.append(f'<a href="{esc(url)}" target="_blank">🔗 {esc(r["official_source"] or "Source")}</a>')
    code = r["hsn_code"] or "—"
    sub = f"{code_label(r)} {esc(code)} · {esc(r['category'])} · {esc(r['item_type'])}"
    desc = f'<div class="card-desc">ℹ️ {esc(r["description"])}</div>' if r["description"] else ""
    return (
        f'<div class="card"><div class="card-head"><div>'
        f'<div class="card-title">{esc(r["product_name"])}</div><div class="card-sub">{sub}</div></div>'
        f'<div class="rate-big {rate_css}"><small>GST rate</small>{rate_text}</div></div>'
        f'<div class="status {css}">{"✅" if css == "yes" else "🚫"} {label}</div>'
        f'{desc}<div class="tiles">{tiles}</div>'
        f'<div class="meta">{"".join(meta)}</div></div>'
    )


def show_table(frame):
    view = pd.DataFrame({
        "Item": frame["product_name"],
        "Type": frame["item_type"],
        "HSN / SAC": frame["hsn_code"],
        "Category": frame["category"],
        "GST rate": frame["igst_rate"].map(fmt_rate),
        "Status": frame.apply(lambda r: gst_status(r)[0], axis=1),
        "CGST": frame["cgst_rate"].map(fmt_rate),
        "SGST": frame["sgst_rate"].map(fmt_rate),
        "Notification": frame["notification_number"],
    })
    st.dataframe(view, hide_index=True)


def export(frame):
    out = frame[COLUMNS].copy()
    out.insert(3, "gst_status", frame.apply(lambda r: gst_status(r)[0], axis=1))
    return out.to_csv(index=False).encode("utf-8")


def set_query(text):
    st.session_state["query"] = text


def reset_upload():
    st.session_state.pop("upload", None)
    st.session_state.pop("upload_id", None)
    st.session_state["uploader_key"] = st.session_state.get("uploader_key", 0) + 1


# ---------------- pages ----------------

def page_finder(data):
    df = data["df"]
    hero("🧾 GST Rate Finder", "Type any goods or service to see if GST applies, its rate and HSN / SAC code.",
         f"Post GST rate rationalisation · rates as on {RATES_AS_ON}")

    if df.empty:
        st.info("The GST database is empty. Add records to gst_data.csv or upload a CSV on **Data & Parser**.")
        return

    if speech_to_text is not None:
        c_input, c_mic = st.columns([6, 1], vertical_alignment="bottom")
        with c_mic:
            spoken = speech_to_text(language="en-IN", start_prompt="🎤 Speak", stop_prompt="⏹ Stop",
                                    just_once=True, use_container_width=True, key="voice")
        if spoken:
            st.session_state["query"] = spoken.strip(" .?")
    else:
        c_input = st.container()
    with c_input:
        query = st.text_input("Name of goods / service or HSN code", key="query",
                              placeholder="e.g. Rice, Laptop, Fresh milk, Cement, 0401")

    st.caption("Try:")
    for col, example in zip(st.columns(len(EXAMPLES)), EXAMPLES):
        col.button(example, on_click=set_query, args=(example,), key=f"ex_{example}",
                   use_container_width=True)

    with st.expander("Filters"):
        f1, f2, f3 = st.columns(3)
        kinds = f1.multiselect("Type", ["Goods", "Service"])
        cats = f2.multiselect("Category", sorted(c for c in df["category"].unique() if c))
        rates = f3.multiselect("GST rate", sorted(df["igst_rate"].dropna().unique()), format_func=fmt_rate)

    if not query.strip() and not (kinds or cats or rates):
        m = st.columns(4)
        m[0].metric("Items in database", len(df))
        m[1].metric("Goods", int((df["item_type"] == "Goods").sum()))
        m[2].metric("Services", int((df["item_type"] == "Service").sum()))
        m[3].metric("GST not applicable", int(df.apply(lambda r: gst_status(r)[1] != "yes", axis=1).sum()))
        footer()
        return

    results, corrected = search(df, query)
    if kinds:
        results = results[results["item_type"].isin(kinds)]
    if cats:
        results = results[results["category"].isin(cats)]
    if rates:
        results = results[results["igst_rate"].isin(rates)]

    if results.empty:
        st.error(f"**{NOT_FOUND}**")
        st.caption("Tip: use a common name (e.g. *mobile* instead of a brand), a Hindi name "
                   "(*chawal*, *doodh*) or the HSN code. Browse all items on the **Browse** page.")
        footer()
        return

    if corrected:
        st.info(f"No exact match for **{query.strip()}** — showing results for **{corrected}**.")
    st.caption(f"{len(results)} result(s)")
    for _, row in results.head(MAX_CARDS).iterrows():
        st.markdown(product_card(row), unsafe_allow_html=True)
    if len(results) > MAX_CARDS:
        st.caption(f"Showing the first {MAX_CARDS}. Download the CSV for all {len(results)}.")

    st.download_button("⬇️ Download these results (CSV)", data=export(results),
                       file_name="gst_search_results.csv", mime="text/csv")
    footer()


def page_browse(data):
    df = data["df"]
    hero("🏷️ Browse", "Explore every goods and service by category or GST rate.")
    if df.empty:
        st.info("No items to browse yet.")
        return

    tab_cat, tab_rate, tab_all = st.tabs(["By category", "By GST rate", "All items"])
    with tab_cat:
        chosen = st.selectbox("Category", sorted(c for c in df["category"].unique() if c))
        show_table(df[df["category"] == chosen])
    with tab_rate:
        labels = {"Nil / Exempt": 0.0, **{fmt_rate(r): r for r in sorted(df["igst_rate"].dropna().unique()) if r}}
        labels["Outside GST"] = None
        chosen = st.selectbox("GST rate", list(labels))
        if labels[chosen] is None:
            show_table(df[df["igst_rate"].isna()])
        else:
            show_table(df[df["igst_rate"] == labels[chosen]])
    with tab_all:
        show_table(df)
        st.download_button("⬇️ Download all (CSV)", export(df), "gst_rates_all.csv", "text/csv")

    if df["igst_rate"].notna().any():
        st.subheader("Items by GST rate")
        counts = df.assign(rate=df["igst_rate"].map(fmt_rate).replace("N/A", "Outside GST"),
                           order=df["igst_rate"].fillna(999))
        counts = counts.groupby(["order", "rate"]).size().reset_index(name="items")
        chart = (
            alt.Chart(counts)
            .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6, color="#1e40af")
            .encode(x=alt.X("rate:N", sort=None, title="GST rate", axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("items:Q", title="Items"), tooltip=["rate", "items"])
            .properties(height=260)
        )
        st.altair_chart(chart)
    footer()


def page_calculator(data):
    df = data["df"]
    hero("🧮 GST Calculator", "Work out CGST, SGST, IGST and the final price on any value.")

    left, right = st.columns([1.1, 1], gap="large")
    with left:
        with st.container(border=True):
            manual = "— I'll choose the rate myself —"
            item = st.selectbox("Item (fills the rate from the database)",
                                [manual] + sorted(df["product_name"].tolist()))
            cess = 0.0
            if item == manual:
                gst = st.selectbox("GST rate", SLAB_CHOICES, index=2, format_func=fmt_rate)
            else:
                row = df[df["product_name"] == item].iloc[0]
                if pd.isna(row["igst_rate"]):
                    st.warning(f"**{item}** is outside GST — no GST is charged on it.")
                    return footer()
                gst = float(row["igst_rate"])
                cess = 0.0 if pd.isna(row["cess_rate"]) else float(row["cess_rate"])
                st.caption(f"{code_label(row)} {row['hsn_code']} · GST {fmt_rate(gst)} · {gst_status(row)[0]}")

            inclusive = st.radio("The price I'm entering is", ["Before GST", "Including GST"],
                                 horizontal=True) == "Including GST"
            price = st.number_input("Price per unit (₹)", min_value=0.0, value=1000.0, step=100.0)
            qty = st.number_input("Quantity", min_value=1, value=1, step=1)
            intra = st.radio("Type of supply", ["Within the same state (CGST + SGST)",
                                                "To another state (IGST)"]).startswith("Within")

    gross = price * qty
    taxable = gross / (1 + (gst + cess) / 100) if inclusive else gross
    gst_amt = taxable * gst / 100
    cess_amt = taxable * cess / 100
    total = taxable + gst_amt + cess_amt

    lines = [("Taxable value", taxable)]
    if intra:
        lines += [(f"CGST @ {gst / 2:g}%", gst_amt / 2), (f"SGST @ {gst / 2:g}%", gst_amt / 2)]
    else:
        lines += [(f"IGST @ {gst:g}%", gst_amt)]
    if cess:
        lines += [(f"Cess @ {cess:g}%", cess_amt)]
    lines += [("Total GST" + (" + cess" if cess else ""), gst_amt + cess_amt)]

    with right:
        rows_html = "".join(f'<div class="bill-row"><span>{esc(k)}</span><span>{inr(v)}</span></div>'
                            for k, v in lines)
        st.markdown(
            f'<div class="card"><div class="card-title">Tax breakdown</div>{rows_html}'
            f'<div class="bill-row total"><span>Final price</span><span>{inr(total)}</span></div></div>',
            unsafe_allow_html=True,
        )
        if inclusive:
            st.caption(f"Taxable value = {inr(gross)} × 100 ÷ (100 + {gst + cess:g})")
        else:
            st.caption(f"GST = {inr(taxable)} × {gst:g} ÷ 100")
    footer()


def page_data(data):
    hero("📂 Data & Parser", "Load a GST rate CSV, see what the parser fixed and download clean data.")

    with st.expander("What does the parser do?"):
        st.markdown("""
- **Reads messy headers** — `HSN Code`, `GST Rate (%)`, `Item Name`, `SGST/UTGST` are all understood.
- **Reads rate text** — `18%`, `18 %`, `9+9`, `Nil`, `Exempt` become numbers.
- **Keeps HSN / SAC codes as text** — leading zeros stay; `401` (Excel dropped the zero) becomes `0401`.
- **Fills the split** — IGST only → CGST = SGST = IGST ÷ 2, or CGST + SGST → IGST.
- **Checks** — CGST + SGST must equal IGST, retired (12% / 28%) or unusual slabs, duplicates,
  missing names, and rows marked *Verified* without a notification or source.
""")

    uploaded = st.file_uploader("Upload a GST rate CSV", type=["csv"],
                                key=f"uploader_{st.session_state.get('uploader_key', 0)}")
    if uploaded is not None:
        upload_id = (uploaded.name, uploaded.size)
        if st.session_state.get("upload_id") != upload_id:
            try:
                df_u, issues_u, summary_u = parse_gst_csv(uploaded.getvalue())
            except Exception as err:
                st.error(f"Could not read this file: {err}")
            else:
                st.session_state["upload"] = {"df": df_u, "issues": issues_u,
                                              "summary": summary_u, "name": uploaded.name}
                st.session_state["upload_id"] = upload_id
                st.rerun()

    if "upload" in st.session_state:
        st.success(f"Using uploaded file **{data['name']}** for this session.")
        st.button("↩️ Switch back to gst_data.csv", on_click=reset_upload)
    else:
        st.caption(f"Currently using **{data['name']}** from the GitHub repository.")

    s = data["summary"]
    m = st.columns(5)
    m[0].metric("Rows read", s["rows_read"])
    m[1].metric("Loaded", s["rows_loaded"])
    m[2].metric("Auto-fixes", s["fixes"])
    m[3].metric("Warnings", s["warnings"])
    m[4].metric("Errors", s["errors"])

    issues = data["issues"]
    if issues.empty:
        st.success("No problems found in the data.")
    else:
        levels = st.multiselect("Show", ["error", "warning", "info"], default=["error", "warning"])
        st.dataframe(issues[issues["level"].isin(levels)], hide_index=True)

    c1, c2 = st.columns(2)
    c1.download_button("⬇️ Download cleaned CSV", data["df"].to_csv(index=False).encode("utf-8"),
                       "gst_data_clean.csv", "text/csv")
    c2.download_button("⬇️ Download blank template", template_csv().encode("utf-8"),
                       "gst_template.csv", "text/csv")
    footer()


def page_sources(data):
    hero("📚 Sources & Disclaimer", "Where the GST rates come from and how the data was compiled.")

    st.subheader("GST slabs in force")
    slabs = [
        ("Nil", "Exempt", "Fresh milk, loose grains, Indian breads, books, health & life insurance", "#047857"),
        ("5%", "Merit rate", "Packaged food, personal care, medicines, hotels ≤ ₹7,500, salons", "#0e7490"),
        ("18%", "Standard rate", "Electronics, cement, small cars, most services", "#1e40af"),
        ("40%", "Demerit rate", "Tobacco, pan masala, aerated drinks, luxury cars, betting", "#b91c1c"),
        ("3%", "Special rate", "Gold, silver and jewellery", "#a16207"),
    ]
    for col, (rate, title, examples, colour) in zip(st.columns(5), slabs):
        col.markdown(f'<div class="slab" style="--c:{colour}"><b>{rate}</b><div>{title}</div>'
                     f'<small>{examples}</small></div>', unsafe_allow_html=True)

    st.subheader("Official sources")
    st.markdown("""
| Notification | What it covers | Effective |
|---|---|---|
| 9/2025-Central Tax (Rate), 17-09-2025 | New GST rates on goods (Schedules I–VII) after rate rationalisation | 22-09-2025 |
| 10/2025-Central Tax (Rate), 17-09-2025 | Goods exempt from GST (Nil rate) | 22-09-2025 |
| 15/2025-Central Tax (Rate), 17-09-2025 | Amends 11/2017 — GST rates on services | 22-09-2025 |
| 16/2025-Central Tax (Rate), 17-09-2025 | Amends 12/2017 — exempt services (individual life & health insurance) | 22-09-2025 |
| Tobacco amendment to 9/2025 | Cigarettes, pan masala, tobacco at 40%; compensation cess ends | 01-02-2026 |
| 2/2026, 3/2026, 6/2026-Central Tax (Rate) | 57th GST Council: tractor tyres, isabgol, hotels/restaurants, delivery | 01-11-2026 |
| CGST Act 2017, Section 9 | Alcohol for human consumption is outside GST; petroleum not yet notified | — |

- [CBIC Tax Information Portal — notifications](https://taxinformation.cbic.gov.in/)
- [CBIC — GST rates for goods and services](https://cbic-gst.gov.in/gst-goods-services-rates.html)
- [GST Council](https://gstcouncil.gov.in/)
""")
    st.subheader("How the data was compiled")
    st.markdown("""
1. Took the item lists from the rate notifications above (goods by HSN, services by SAC).
2. Picked common goods and services a user is likely to search for and recorded the HSN / SAC code,
   the IGST rate and the notification for each.
3. Added everyday synonyms and Hindi names (e.g. *chawal*, *doodh*) as keywords for search.
4. The CSV is checked by `gst_parser.py` every time the app loads (rates, CGST/SGST split, HSN format).
""")
    st.warning(
        "**Disclaimer:** This app is for educational purposes only. GST rates and HSN classification "
        "can change through notifications, and the rate can depend on conditions (packaging, price, "
        "use). Always verify with the latest official notification before using this information for "
        "any commercial or tax purpose. This is not professional tax or legal advice."
    )


def page_about(data):
    hero("ℹ️ About", "GST Rate Finder · BBA FinTech Practical Assignment")
    st.markdown("""
**Problem:** finding whether GST applies to an item, and at what rate, means reading long government
notifications. This app answers it from a simple search box.

**What it does**
- Search goods and services by name, synonym, Hindi name or HSN / SAC code — with spelling correction
- Shows GST status, rate, HSN / SAC, CGST / SGST / IGST split and the source notification
- Voice search, category and rate browsing, GST calculator, CSV download
- A CSV parser that cleans and validates the rate data

**Technology:** Python · Pandas · Streamlit · Altair · CSV · GitHub · Streamlit Community Cloud
""")
    footer()


# ---------------- layout ----------------

PAGES = {
    "🔍 Find GST Rate": page_finder,
    "🏷️ Browse": page_browse,
    "🧮 GST Calculator": page_calculator,
    "📂 Data & Parser": page_data,
    "📚 Sources & Disclaimer": page_sources,
    "ℹ️ About": page_about,
}

data = current_data()

with st.sidebar:
    st.markdown("## 🧾 GST Rate Finder")
    page = st.radio("Go to", list(PAGES), label_visibility="collapsed")
    st.divider()
    st.caption(f"Data: **{data['name']}** · {len(data['df'])} items")
    st.caption(f"Rates as on {RATES_AS_ON}")
    st.caption("Educational use only — verify with the latest notifications.")

PAGES[page](data)
