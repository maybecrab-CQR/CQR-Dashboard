"""盤中量價訊號面板（蕭氏：攻擊 → 量縮 → 再攻）。只顯示訊號，不會下單。

與回測共用 xiao_daytrade 的 daily_context / prepare_bars / DayMachine，判斷邏輯完全相同。
資料來源：Yahoo 日 K 與 15 分 K（延遲，非逐筆即時）。
"""
import time as clock
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

from pathlib import Path

import xiao_swing as xs
from xiao_daytrade import DayMachine, Params, daily_context, index_intraday_change, prepare_bars

import os

LOG_DIR = Path(os.environ.get("CQR_SIGNAL_LOG", Path(__file__).resolve().parent / "signal_log"))

TZ = ZoneInfo("Asia/Taipei")
STATES = {  # 狀態 → (顯示文字, 排序, CSS 類別)
    "signal": ("再攻訊號", 0, "sig-hot"),
    "holding": ("訊號後持有中", 1, "sig-hot"),
    "armed": ("量縮整理・待再攻", 2, "sig-warm"),
    "wait_pull": ("攻擊出現・等量縮", 3, "sig-info"),
    "wait_push": ("等待攻擊量", 4, "sig-idle"),
    "done": ("已出場", 5, "sig-muted"),
    "filtered": ("盤前條件不符", 6, "sig-muted"),
    "nodata": ("資料不足", 7, "sig-muted"),
}

CSS = """<style>
.sig-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin:0 0 8px}
.sig-head b{font-size:19px;color:#eef1f6}.sig-head span{font-size:12px;color:#8fa0b6}
.sig-cards{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin-bottom:10px}
.sig-card{background:linear-gradient(115deg,#141c27,#0f151f);border:1px solid #263140;border-radius:10px;padding:8px 12px}
.sig-card span{display:block;font-size:12px;color:#929fb1}.sig-card b{font-size:22px;color:#e8edf6}
.sig-wrap{overflow:auto;border:1px solid #293442;border-radius:10px}
.sig-wrap table.acct{border:0;border-radius:0}.sig-wrap th{position:sticky;top:0;z-index:2}
.sig-badge{display:inline-block;border-radius:12px;padding:2px 9px;font-size:13px;white-space:nowrap}
.sig-hot{background:#4a1f22;color:#ffb3b5;border:1px solid #a8474b}.sig-warm{background:#3b3423;color:#efc979;border:1px solid #67583b}
.sig-info{background:#1c2d42;color:#9cc7f5;border:1px solid #35557a}.sig-idle{background:#1a2431;color:#a9b6c9;border:1px solid #344353}
.sig-muted{background:#141b25;color:#6f7d90;border:1px solid #263140}
.sig-cards.six{grid-template-columns:repeat(6,minmax(0,1fr))}.sig-cards.six .sig-card b{font-size:19px!important;white-space:nowrap}
.sig-warn{background:#3d2a12;color:#ffc46b;border:1px solid #8a5a1c;flex:none}
.sig-ev{color:#9fb0c4;font-size:12px;white-space:normal;margin-top:3px;line-height:1.35;max-width:300px}
.sig-sel td{background:#2a2b24!important}.sig-ok{color:#f17c7e}.sig-no{color:#55667a}
.sig-note{font-size:12px;color:#7f8ea3;margin-top:6px}
.sig-wrap table.acct{font-size:14px}.sig-wrap td:nth-child(-n+4),.sig-wrap th:nth-child(-n+4){text-align:left!important}
.sig-flag{font-size:12px;margin-right:3px}
@media(max-width:1100px){.sig-cards{grid-template-columns:repeat(3,minmax(0,1fr))}}
[data-testid="stMarkdownContainer"]:has(.sx-bar){margin-bottom:0!important}
.sx-bar{height:84px;box-sizing:border-box;padding:8px 12px;border:1px solid #293442;border-radius:10px;background:linear-gradient(115deg,#141c27,#0f151f);display:flex;flex-direction:column;justify-content:space-between}
.sx-top{display:flex;align-items:center;gap:12px;min-width:0}
.sx-top .sig-badge{font-size:16px;font-weight:700;flex:none}
.sx-note{flex:1;min-width:0;font-size:15px;color:#c0ccdc;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sx-num{flex:none;font-size:18px;color:#eef2f8;font-variant-numeric:tabular-nums}.sx-num i{font-style:normal;font-size:14px;color:#94a3b6;margin-right:5px}
.sx-chips{display:flex;align-items:center;gap:6px;white-space:nowrap;overflow:hidden}
.sx-chip{font-size:14px;padding:1px 8px;border-radius:10px;border:1px solid #2b3747}
.sx-chip.ok{color:#f6b0b2;border-color:#6b3437;background:#2a1719}.sx-chip.no{color:#7a8a9e;background:#121923}
.sx-stamp{margin-left:auto;font-size:13px;color:#7f8fa3}
.sig-head b{font-size:21px!important}.sig-head span{font-size:14px!important}
.sig-card span{font-size:14px!important}.sig-card b{font-size:24px!important}
.sig-wrap table.acct{font-size:16px!important}.sig-ev{font-size:14px!important}.sig-note{font-size:14px!important}.sig-badge{font-size:14px!important}
</style>"""


@st.cache_data(ttl=300, show_spinner=False)
def _download(tickers, period, interval):
    """批次下載，回傳 {ticker: DataFrame}。快取 5 分鐘，避免 Yahoo 限流。"""
    df = yf.download(list(tickers), period=period, interval=interval, group_by="ticker", auto_adjust=False,
                     actions=False, threads=True, progress=False, timeout=30)
    out = {}
    for t in tickers:
        try:
            sub = df[t] if isinstance(df.columns, pd.MultiIndex) else df
        except KeyError:
            continue
        sub = sub.dropna(how="all")
        if sub.empty:
            continue
        idx = pd.DatetimeIndex(sub.index)
        sub.index = idx.tz_convert(TZ) if idx.tz is not None else idx.tz_localize(TZ)
        out[t] = sub
    return out, datetime.now(TZ).strftime("%H:%M:%S")


def _completed(m15, now):
    """只保留已收完的 15 分 K（盤中最後一根還在跑，不能拿來判斷）。"""
    return m15[m15.index + pd.Timedelta(minutes=15) <= now]


def evaluate(cands, p=Params()):
    tickers = tuple(sorted({c["ticker"] for c in cands} | {"^TWII"}))
    daily, d_stamp = _download(tickers, "6mo", "1d")
    m15all, m_stamp = _download(tickers, "1mo", "15m")
    if "^TWII" not in daily or "^TWII" not in m15all:
        raise RuntimeError("Yahoo 未回傳大盤資料，稍後再試")
    now = pd.Timestamp(datetime.now(TZ))
    idx_d = daily["^TWII"].copy()
    idx_d.index = pd.DatetimeIndex(idx_d.index.date)
    idx_m = _completed(m15all["^TWII"], now)
    idx_chg = index_intraday_change(idx_m, idx_d)
    rows, session = [], None
    for c in cands:
        t = c["ticker"]
        row = dict(c, state="nodata", events="", trigger=np.nan, stop=np.nan, entry=np.nan, last=np.nan,
                   chg=np.nan, idx=np.nan, vwap=np.nan, ratio=np.nan, flags={})
        d, m = daily.get(t), m15all.get(t)
        if d is None or m is None or len(d) < 30:
            rows.append(row)
            continue
        d = d.copy()
        d.index = pd.DatetimeIndex(d.index.date)
        m = _completed(m, now)
        ctx = daily_context(d, idx_d, p)
        bars = prepare_bars(m, ctx["prev_close"], idx_chg)
        if bars.empty:
            rows.append(row)
            continue
        day = bars.index.date[-1]
        session = session or day
        key = pd.Timestamp(day)
        today = bars[bars.index.date == day]
        last = today.iloc[-1]
        row.update(last=last.close, chg=last.chg, idx=last.idx_chg, vwap=last.vwap, ratio=last.slot_ratio)
        if key in ctx.index:
            cr = ctx.loc[key]
            row["flags"] = {"扣": bool(cr.fast_up and cr.slow_up), "強": bool(cr.rs > 0),
                            "峰": bool(cr.vol_peak >= p.vol_peak_ratio), "21": bool(cr.above_slow)}
            long_ok = bool(cr.long_ok)
        else:
            long_ok = False
        if not long_ok:
            row["state"] = "filtered"
            rows.append(row)
            continue
        mach, pending = DayMachine(1, today.prev_close.iloc[0], p), None
        for bar in today.to_dict("records"):
            if pending is not None and mach.state == "entering":
                mach.filled(bar["open"], pending[2])           # 模擬：下一根開盤成交（不含滑價）
                row["entry"] = bar["open"]
                pending = None
            out = mach.on_bar(bar)
            if out and out[0] == "enter":
                pending = out
        if mach.trigger:
            row.update(trigger=mach.trigger["price"], stop=mach.trigger["stop"])
        row["state"] = {"entering": "signal", "in_pos": "holding"}.get(mach.state, mach.state)
        row["events"] = "、".join(f"{tm} {ev}" for tm, ev in mach.events[-4:])
        rows.append(row)
    return rows, session, m_stamp


def _fmt(v, nd=2, signed=False):
    if v is None or not np.isfinite(v):
        return "—"
    return f"{v:+,.{nd}f}" if signed else f"{v:,.{nd}f}"


def render_signal_panel(cands, selected_code, workspace):
    mode = st.segmented_control("訊號模式", ["日線凹洞量 v2（建議）", "盤中15分K v1"], default="日線凹洞量 v2（建議）",
                                key="sig_mode", label_visibility="collapsed") or "日線凹洞量 v2（建議）"
    if mode.startswith("日線"):
        render_v2(cands, selected_code, workspace)
    else:
        render_v1(cands, selected_code, workspace)


# ======================= v2：日線凹洞量 =======================
def _read_csv(name):
    fp = LOG_DIR / name
    if not fp.exists():
        return None
    try:
        return pd.read_csv(fp, dtype={"code": str})
    except Exception:
        return None


def _live_v2(cands):
    """沒有排程檔（例如雲端）時：對儀表板候選股即時計算今日狀態。族群強弱與排名取自儀表板掃描結果。"""
    tickers = tuple(sorted({c["ticker"] for c in cands} | {"^TWII"}))
    daily, stamp = _download(tickers, "1y", "1d")
    if "^TWII" not in daily:
        raise RuntimeError("Yahoo 未回傳大盤資料")
    idx = daily["^TWII"]["Close"].copy()
    idx.index = pd.DatetimeIndex(idx.index.date)
    data = {}
    for c in cands:
        d = daily.get(c["ticker"])
        if d is None:
            continue
        d = d.copy()
        d.index = pd.DatetimeIndex(d.index.date)
        x = xs.prep_daily(d, idx)
        if x is not None:
            data[c["ticker"]] = (c, x)
    by_sec = {}
    for t, (c, x) in data.items():
        if bool(x.liquid.iat[-1]):
            by_sec.setdefault(c["sector"], []).append((c["stock_rs"], t))
    rank = {t: i + 1 for lst in by_sec.values() for i, (_, t) in enumerate(sorted(lst, reverse=True))}
    rows = []
    mkt_bull = bool((idx > idx.rolling(60).mean()).iat[-1])
    for t, (c, x) in data.items():
        last = x.index[-1]
        # 族群強弱只有今天的值（取自儀表板掃描）；歷史訊號標記沿用今天的族群條件，只供參考
        sec_rs = pd.Series(c["sector_rs"], index=x.index)
        sec_rank = pd.Series(rank.get(t, 99), index=x.index)
        xs.add_features(x, sec_rs, sec_rank, idx)
        xs.add_v3(x, idx)
        pref = c["sector"] in xs.PREFERRED
        st_ = xs.today_state3(x, preferred=pref)
        checks = xs.checks_v3(x)
        checks["偏好族群"] = pref
        rows.append({"date": last.date(), "code": c["code"], "name": c["name"], "sector": c["sector"], "state": st_["state"],
                     "close": x.c.iat[-1], "stop": st_["stop"], "high": st_["high"], "sec_rank": rank.get(t, np.nan),
                     "futures": "", "note": st_["note"], "warn": st_["warn"], "mkt_bull": mkt_bull, "checks": checks,
                     "marks": _marks(x, pref)})
    return pd.DataFrame(rows), stamp


def _marks(x, pref, bars=250):
    """最近一年的歷史訊號日（給 K 線標記用）：v3 波段量啟動、v2 凹洞量轉折。"""
    lo = max(0, len(x) - bars)
    bull = x.mkt_bull.values
    out = []
    if pref:
        out += [(str(x.index[i].date()), "v3", float(s)) for i, s in xs.entries_wave(x, trend=True) if i >= lo and bull[i]]
    out += [(str(x.index[i].date()), "v2", float(s)) for i, s in xs.entries_v2(x) if i >= lo and bull[i]]
    return tuple(sorted(out))


@st.cache_data(ttl=300, show_spinner=False, max_entries=16)
def scan_states(cands):
    """量價訊號模組用：對候選股（前十強板塊的前五強）即時計算 v2 狀態。回傳 ({code: row}, 取得時間)。"""
    if not cands:
        return {}, "—"
    scan, stamp = _live_v2(cands)
    return {str(r["code"]): r for r in scan.to_dict("records")}, stamp


SHORT = {"signal3": "v3 波段啟動", "signal": "v2 轉折", "wave": "波段進行中", "setup": "量縮整理", "trend": "趨勢・無型態", "none": "盤前不符"}


def state_label(row):
    """表格用短標籤（完整說明在 K 線上方的狀態列）。"""
    return SHORT.get((row or {}).get("state"), "—")


def render_status(row, stamp):
    """K 線上方的訊號狀態列：狀態、說明、停損／攻擊高點、條件逐項。"""
    if not row:
        st.markdown('<div class="sx-bar"><div class="sx-top"><span class="sig-badge sig-muted">資料不足</span>'
                    '<span class="sx-note">此檔沒有足夠的日線資料可判斷（需至少 120 根）</span></div></div>', unsafe_allow_html=True)
        return
    label, cls, _ = V2_STATE.get(row["state"], (row["state"], "sig-idle", 9))
    nums = [("收盤", _fmt(row["close"])), ("停損", _fmt(row["stop"])), ("攻擊高點", _fmt(row["high"])),
            ("族群內", "—" if not np.isfinite(row["sec_rank"]) else f"第 {int(row['sec_rank'])}")]
    checks = row.get("checks") or {}
    chips = "".join(f'<span class="sx-chip {"ok" if ok else "no"}">{"✓" if ok else "✗"} {escape(k)}</span>' for k, ok in checks.items())
    note = escape(str(row["note"])) if isinstance(row.get("note"), str) and row["note"] else "—"
    warn = row.get("warn") if isinstance(row.get("warn"), str) else ""
    warn_html = f'<span class="sig-badge sig-warn" title="持股出場警示">⚠ {escape(warn)}</span>' if warn else ""
    st.markdown(f'<div class="sx-bar"><div class="sx-top"><span class="sig-badge {cls}">{label}</span>{warn_html}<span class="sx-note" title="{note}">{note}</span>'
                + "".join(f'<span class="sx-num"><i>{a}</i>{b}</span>' for a, b in nums)
                + f'</div><div class="sx-chips">{chips}<span class="sx-stamp">日線 {row["date"]} · 取得 {escape(stamp)}</span></div></div>',
                unsafe_allow_html=True)


V2_STATE = {"signal3": ("v3 波段量啟動", "sig-hot", 0), "signal": ("v2 凹洞量轉折", "sig-hot", 1),
            "setup": ("量縮整理中", "sig-warm", 2), "wave": ("波段進行中", "sig-info", 3),
            "trend": ("盤前符合・無型態", "sig-idle", 4), "none": ("盤前不符", "sig-muted", 5)}


def _fwd_stats(fwd):
    closed = fwd[fwd.status == "已出場"] if fwd is not None and not fwd.empty else pd.DataFrame()
    if closed.empty:
        return 0 if fwd is None else len(fwd), 0, "—"
    return len(fwd), len(closed), f"{(closed.ret_net_stock > 0).mean() * 100:.0f}% / {closed.ret_net_stock.mean() * 100:+.2f}%"


def _fwd_table(fwd, height):
    if fwd is None or fwd.empty:
        st.markdown('<div class="sig-note">尚無紀錄。排程每個交易日 14:45 執行，出現訊號（且大盤為多頭）時才會記錄；累積 2～3 個月才有參考價值。</div>', unsafe_allow_html=True)
        return
    fwd = fwd.sort_values("date", ascending=False)
    head = "".join(f"<th>{h}</th>" for h in ["訊號日", "代號", "名稱", "進場（收盤）", "停損", "狀態", "毛報酬%", "扣現股成本%", "持有天", "出場原因"])
    body = ""
    for r in fwd.itertuples():
        g = float(getattr(r, "ret_gross", 0) or 0) * 100
        raw = getattr(r, "ret_net_stock", np.nan)
        net = float(raw) * 100 if raw is not None and np.isfinite(float(raw)) else np.nan
        cls = ' class="acct-up"' if g > 0 else ' class="acct-down"' if g < 0 else ""
        why = getattr(r, "exit_reason", "")
        body += (f"<tr><td>{str(r.date)[:10]}</td><td>{escape(str(r.code))}</td><td>{escape(str(r.name))}</td><td>{_fmt(r.close)}</td>"
                 f"<td>{_fmt(r.stop)}</td><td>{escape(str(r.status))}</td><td{cls}>{_fmt(g, 2, True)}</td><td>{_fmt(net, 2, True)}</td>"
                 f"<td>{_fmt(r.days, 0)}</td><td>{escape(why) if isinstance(why, str) else ''}</td></tr>")
    st.markdown(f'<div class="sig-wrap" style="max-height:{height}px"><table class="acct"><tr>{head}</tr>{body}</table></div>', unsafe_allow_html=True)


def render_v2(cands, selected_code, workspace):
    """前瞻紀錄頁：今日全市場訊號（排程掃描）＋ v3／v2 前瞻紀錄。"""
    scan, source = _read_csv("latest_scan.csv"), "排程掃描（全市場，每個交易日 14:45 更新）"
    if scan is None:
        if not cands:
            st.info("目前沒有候選股。")
            return
        with st.spinner("即時計算候選股的日線型態…"):
            try:
                scan, stamp = _live_v2(cands)
                source = f"即時計算（儀表板候選股 {len(cands)} 檔，取得 {stamp}；前瞻紀錄只在本機排程產生）"
            except Exception as exc:
                st.warning(f"資料暫時無法取得：{exc}")
                return
    scan = scan.copy()
    asof = str(scan["date"].iloc[0]) if not scan.empty else "—"
    bull = bool(scan["mkt_bull"].iloc[0]) if "mkt_bull" in scan and not scan.empty else None
    scan["order"] = scan["state"].map(lambda k: V2_STATE.get(k, ("", "", 9))[2])
    today = scan[scan.state.isin(["signal3", "signal", "setup"])].sort_values(["order", "sec_rank"])
    n = lambda k: int((scan.state == k).sum())
    f3, f2 = _read_csv("forward_status_v3.csv"), _read_csv("forward_status.csv")
    t3, c3, s3 = _fwd_stats(f3)
    bull_txt = "—" if bull is None else ("多頭（可做多）" if bull else "空頭（不做多）")
    st.markdown(f'<div class="sig-head"><b>蕭氏日線訊號 · 前瞻紀錄</b><span>資料日 {asof} · {escape(source)}</span></div>', unsafe_allow_html=True)
    cards = [("大盤濾網", bull_txt), ("今日 v3 波段量啟動", n("signal3")), ("今日 v2 凹洞量轉折", n("signal")),
             ("量縮整理／波段進行中", f"{n('setup')}／{n('wave')}"), ("v3 紀錄（已出場）", f"{t3}（{c3}）"), ("v3 前瞻勝率／平均", s3)]
    st.markdown('<div class="sig-cards six">' + "".join(f'<div class="sig-card"><span>{a}</span><b style="font-size:{18 if len(str(b)) > 8 else 22}px">{b}</b></div>'
                                                        for a, b in cards) + "</div>", unsafe_allow_html=True)
    head = "".join(f"<th>{h}</th>" for h in ["代號", "名稱", "族群", "狀態／說明", "收盤", "停損", "高點", "族群內", "股期"])
    body = ""
    for r in today.itertuples():
        label, cls, _ = V2_STATE.get(r.state, (r.state, "sig-idle", 9))
        sel = ' class="sig-sel"' if str(r.code) == str(selected_code) else ""
        note = f'<div class="sig-ev">{escape(str(r.note))}</div>' if isinstance(r.note, str) and r.note else ""
        fut = r.futures if isinstance(getattr(r, "futures", ""), str) and r.futures else "—"
        body += (f"<tr{sel}><td>{escape(str(r.code))}</td><td>{escape(str(r.name))}</td><td>{escape(str(r.sector))}</td>"
                 f'<td><span class="sig-badge {cls}">{label}</span>{note}</td><td>{_fmt(r.close)}</td><td>{_fmt(r.stop)}</td>'
                 f"<td>{_fmt(r.high)}</td><td>{_fmt(r.sec_rank, 0)}</td><td>{escape(fut)}</td></tr>")
    if not body:
        body = '<tr><td class="empty" colspan="9">今天沒有訊號或量縮整理中的股票</td></tr>'
    half = max(160, (workspace - 250) // 2)
    st.markdown(f'<div class="sig-wrap" style="max-height:{half}px"><table class="acct"><tr>{head}</tr>{body}</table></div>', unsafe_allow_html=True)
    which = st.segmented_control("前瞻紀錄", ["v3 波段量啟動", "v2 凹洞量轉折"], default="v3 波段量啟動", key="fwd_which",
                                 label_visibility="collapsed") or "v3 波段量啟動"
    _fwd_table(f3 if which.startswith("v3") else f2, half)
    st.markdown('<div class="sig-note">v3（主）：5MV 帶出 13MV 的第一天、34MV 上揚，當天強於大盤且收在上半部；站上並扣低 21MA、強於大盤、族群強且族群前三，'
                '只做電子／重電／綠能 → 收盤買，停損前 3 日低點，出場同 v2（跌破 21MA、均線扣高、極限大量後量縮不見高先出一半）。'
                '回測 2015-20／2021-26 每筆平均 +1.8%／+2.1%（現股）、勝率約 36～40%；同時持有 5 檔年化約 5%／27%（大盤 8%／22%）。'
                'v2：攻擊後回檔量縮、凹洞量轉折買，樣本少。回測不保證未來，請以前瞻紀錄為準。</div>', unsafe_allow_html=True)


# ======================= v1：盤中 15 分 K =======================
def render_v1(cands, selected_code, workspace):
    if not cands:
        st.info("目前沒有符合條件的候選股：需要在強勢族群內、股價 ≥ 100 元、今日成交值 ≥ 2 億、且強於所屬族群。")
        return
    with st.spinner("讀取候選股的 15 分 K 與日 K…"):
        try:
            rows, session, stamp = evaluate(cands)
        except Exception as exc:
            st.warning(f"訊號資料暫時無法取得：{exc}")
            return
    rows.sort(key=lambda r: (STATES[r["state"]][1], -r.get("sector_rs", 0), -r.get("stock_rs", 0)))
    idx_now = next((r["idx"] for r in rows if np.isfinite(r["idx"])), np.nan)
    counts = {k: sum(r["state"] == k for r in rows) for k in STATES}
    live = datetime.now(TZ).weekday() < 5 and "09:00" <= datetime.now(TZ).strftime("%H:%M") <= "13:30"
    st.markdown(f'<div class="sig-head"><b>量價訊號・攻擊 → 量縮 → 再攻</b><span>{"盤中（Yahoo 15 分 K，延遲約 15～20 分鐘）" if live else "盤後回顧"}'
                f' · 交易日 {session} · 大盤 {_fmt(idx_now, 2, True)}% · 取得 {stamp} · 只顯示訊號，不會下單</span></div>', unsafe_allow_html=True)
    cards = [("再攻訊號／持有", counts["signal"] + counts["holding"]), ("待再攻", counts["armed"]),
             ("等量縮", counts["wait_pull"]), ("等待攻擊", counts["wait_push"]), ("不符／出場", counts["filtered"] + counts["done"] + counts["nodata"])]
    st.markdown('<div class="sig-cards">' + "".join(f'<div class="sig-card"><span>{a}</span><b>{b}</b></div>' for a, b in cards) + "</div>",
                unsafe_allow_html=True)
    head = "".join(f"<th>{h}</th>" for h in ["代號", "名稱", "族群", "狀態／事件", "觸發／停損", "現價", "漲跌%", "均價線", "量比", "盤前"])
    body = ""
    for r in rows:
        label, _, cls = STATES[r["state"]]
        flags = "".join(f'<span class="sig-flag {"sig-ok" if ok else "sig-no"}">{escape(k)}{"✓" if ok else "✗"}</span>' for k, ok in r["flags"].items()) or "—"
        up = r["chg"] > 0 if np.isfinite(r["chg"]) else None
        chg_cls = ' class="acct-up"' if up else ' class="acct-down"' if up is False else ""
        sel = ' class="sig-sel"' if r["code"] == selected_code else ""
        ev = f'<div class="sig-ev">{escape(r["events"])}</div>' if r["events"] else ""
        trig = f"{_fmt(r['trigger'])} / {_fmt(r['stop'])}" if np.isfinite(r["trigger"]) else "—"
        body += (f"<tr{sel}><td>{escape(r['code'])}</td><td>{escape(r['name'])}</td><td>{escape(r['sector'])}</td>"
                 f'<td><span class="sig-badge {cls}">{label}</span>{ev}</td>'
                 f"<td>{trig}</td><td>{_fmt(r['last'])}</td>"
                 f"<td{chg_cls}>{_fmt(r['chg'], 2, True)}</td><td>{_fmt(r['vwap'])}</td>"
                 f"<td>{_fmt(r['ratio'], 2)}</td><td>{flags}</td></tr>")
    st.markdown(f'<div class="sig-wrap" style="max-height:{max(260, workspace - 150)}px"><table class="acct"><tr>{head}</tr>{body}</table></div>',
                unsafe_allow_html=True)
    st.markdown('<div class="sig-note">盤前：扣＝8MA與21MA扣低、強＝10日強於大盤、峰＝量在峰、21＝站上21MA。規則：盤前條件皆符合 → 開高強於大盤出攻擊量 → 壓回量縮守住均價線 → 量增突破整理區＝再攻訊號；'
                '出場看「出大量、量縮、不見高」、跌破均價線、停損、13:00 前平倉。回測顯示扣成本後沒有穩定優勢，請當參考、勿直接照單全收。</div>',
                unsafe_allow_html=True)
