"""量價策略面板（蕭氏日線 v3／v2）：選股看盤的狀態列、訊號績效（今日訊號／歷史回測／實盤追蹤）。只顯示訊號，不會下單。
規則與回測、每日排程共用 xiao_swing.py；資料來源：排程掃描檔（signal_log/），沒有時即時以 Yahoo 日 K 計算。
"""
import os
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

import xiao_swing as xs

LOG_DIR = Path(os.environ.get("CQR_SIGNAL_LOG", Path(__file__).resolve().parent / "signal_log"))

TZ = ZoneInfo("Asia/Taipei")

CSS = """<style>
.sig-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin:0 0 8px}
.sig-head b{font-size:19px;color:#f3eee2}.sig-head span{font-size:12px;color:#9a9383}
.sig-cards{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin-bottom:10px}
.sig-card{background:linear-gradient(115deg,#19170f,#0c0b0a);border:1px solid #2f2a1f;border-radius:10px;padding:8px 12px}
.sig-card span{display:block;font-size:12px;color:#9b9484}.sig-card b{font-size:22px;color:#f0eadb}
.sig-wrap{overflow:auto;border:1px solid #332d21;border-radius:10px}
.sig-wrap table.acct{border:0;border-radius:0}.sig-wrap th{position:sticky;top:0;z-index:2}
.sig-badge{display:inline-block;border-radius:12px;padding:2px 9px;font-size:13px;white-space:nowrap}
.sig-hot{background:#4a1f22;color:#ffb3b5;border:1px solid #a8474b}.sig-warm{background:#3b3423;color:#e3c06a;border:1px solid #67583b}
.sig-info{background:#1c2d42;color:#9cc7f5;border:1px solid #35557a}.sig-idle{background:#1d1b16;color:#b2ab9b;border:1px solid #3d3527}
.sig-muted{background:#141b25;color:#7b7466;border:1px solid #2f2a1f}
.sig-cards.six{grid-template-columns:repeat(6,minmax(0,1fr))}.sig-cards.six .sig-card b{font-size:19px!important;white-space:nowrap}
.sig-warn{background:#3d2a12;color:#ffc46b;border:1px solid #8a5a1c;flex:none}
.sig-hint{display:inline-block;border-radius:12px;padding:1px 8px;font-size:13px;white-space:nowrap;flex:none;cursor:help;
background:#241f38;color:#d2c3ff;border:1px solid #5b4a8f;margin:2px 4px 0 0}
.sig-hint.up{background:#3a1d22;color:#ffb3b5;border-color:#8a3f45}
.sig-card em{display:block;font-style:normal;font-size:13px;color:#b9a9f0;margin-top:1px;white-space:nowrap}
.hist-stats{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:8px;margin:2px 0 6px}
.hist-stats>div{background:linear-gradient(115deg,#19170f,#0c0b0a);border:1px solid #2f2a1f;border-radius:9px;padding:5px 10px;min-width:0}
.hist-stats span{display:block;font-size:13px;color:#9b9484}.hist-stats b{font-size:18px;color:#f0eadb;white-space:nowrap;font-variant-numeric:tabular-nums}
.sig-card span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sig-card b{white-space:nowrap}
.hist-rule{font-size:12.5px;color:#a8a191;line-height:1.45;margin:0;height:80px;box-sizing:border-box;overflow:auto;padding:5px 9px;border:1px solid #2f2a1f;border-radius:8px;background:#100f0d}.hist-rule b{color:#c9a552;margin-right:6px;font-weight:600}
.hist-head{background:linear-gradient(115deg,#19170f,#0c0b0a);border:1px solid #2f2a1f;border-radius:10px;padding:6px 12px;margin:0;height:80px;box-sizing:border-box;overflow:hidden}
/* 說明卡與規則框固定 80px，所在的元件容器也固定高度、不留額外間距：左右兩欄的表格與 K 線才能上下對齊 */
.stElementContainer:has(.hist-head),.stElementContainer:has(.hist-rule){height:80px!important;min-height:80px!important;margin:0!important}
[data-testid="stMarkdownContainer"]:has(.hist-head),[data-testid="stMarkdownContainer"]:has(.hist-rule){margin-bottom:0!important}
.hist-title{display:flex;align-items:baseline;gap:8px;font-size:15px;color:#a8a191;white-space:nowrap}.hist-title b{font-size:19px;color:#f4eee0}
.hist-title i{font-style:normal;font-size:13px;color:#8a8374}.hist-title em{margin-left:auto;font-style:normal;font-size:20px;font-weight:700}
.hist-legs{display:block;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#d2cbbb;line-height:1.45;font-variant-numeric:tabular-nums}
.hist-legs span{color:#c9a552;margin-right:5px}
.hist-head .up{color:#f17c7e}.hist-head .down{color:#55c8a4}
.sig-guide{font-size:14px;color:#b6af9f;margin:2px 0 6px;line-height:1.5}.sig-guide b{color:#ffb3b5}.sig-guide i{font-style:normal;color:#e3c06a}
@media(max-width:1100px){.hist-stats{grid-template-columns:repeat(4,minmax(0,1fr))}}
.sig-ev{color:#a8a191;font-size:12px;white-space:normal;margin-top:3px;line-height:1.35;max-width:300px}
.sig-sel td{background:#2a2416!important}.sig-ok{color:#f17c7e}.sig-no{color:#665f52}
.sig-note{font-size:12px;color:#8a8374;margin-top:6px}
.sig-wrap table.acct{font-size:14px}.sig-wrap td:nth-child(-n+4),.sig-wrap th:nth-child(-n+4){text-align:left!important}
.sig-flag{font-size:12px;margin-right:3px}
@media(max-width:1100px){.sig-cards{grid-template-columns:repeat(3,minmax(0,1fr))}}
[data-testid="stMarkdownContainer"]:has(.sx-bar){margin-bottom:0!important}
.sx-bar{height:84px;box-sizing:border-box;padding:8px 12px;border:1px solid #332d21;border-radius:10px;background:linear-gradient(115deg,#19170f,#0c0b0a);display:flex;flex-direction:column;justify-content:space-between}
.sx-top{display:flex;align-items:center;gap:12px;min-width:0}
.sx-top .sig-badge{font-size:16px;font-weight:700;flex:none}
.sx-note{flex:1;min-width:0;font-size:15px;color:#cbc4b4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sx-num{flex:none;font-size:18px;color:#f4eee0;font-variant-numeric:tabular-nums}.sx-num i{font-style:normal;font-size:14px;color:#9e9787;margin-right:5px}
.sx-chips{display:flex;align-items:center;gap:6px;white-space:nowrap;overflow:hidden}
.sx-chip{font-size:14px;padding:1px 8px;border-radius:10px;border:1px solid #352f22}
.sx-chip.ok{color:#f6b0b2;border-color:#6b3437;background:#2a1719}.sx-chip.no{color:#868070;background:#121110}
.sx-stamp{margin-left:auto;font-size:13px;color:#8a8374}
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


def _fmt(v, nd=2, signed=False):
    if v is None or not np.isfinite(v):
        return "—"
    return f"{v:+,.{nd}f}" if signed else f"{v:,.{nd}f}"


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
    idx = idx[idx > 0]          # 批次下載時大盤最後一列常是空值（當天尚未補齊）；空值比較會被當成「空頭」，必須先去掉
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
        # 偏好範圍以個股的官方產業別判斷（與回測一致）；沒有官方產業別時看族群名稱
        pref = c.get("official") in xs.PREFERRED if c.get("official") else c["sector"] in xs.PREFERRED
        st_ = xs.today_state3(x, preferred=pref)
        checks = xs.checks_v3(x)
        checks["偏好族群"] = pref
        rows.append({"date": last.date(), "code": c["code"], "ticker": t, "name": c["name"], "sector": c["sector"], "state": st_["state"],
                     "close": x.c.iat[-1], "stop": st_["stop"], "high": st_["high"], "sec_rank": rank.get(t, np.nan), "rs10": round(float(x.rs10.iat[-1]), 2),
                     "futures": "", "note": st_["note"], "warn": st_["warn"], "hints": st_["hints"],
                     "idx_below3": bool(x.idx_below3.iat[-1]), "mkt_bull": mkt_bull, "checks": checks,
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


def hint_badges(hints, skip=()):
    """老師參考提醒徽章（紫＝偏空提醒、紅＝偏多）；滑鼠移上去看說明與回測結論。"""
    if not isinstance(hints, str) or not hints:
        return ""
    out = ""
    for k in hints.split("、"):
        if k in skip:
            continue
        who, side, help_ = xs.HINTS.get(k, ("", "down", ""))
        tip = f"{ {'林': '林教授', '蕭': '蕭明道'}.get(who, '廖崧沂 2.0')}參考提醒：{help_}"
        out += f'<span class="sig-hint{" up" if side == "up" else ""}" title="{escape(tip)}">{escape(who)}｜{escape(k)}</span>'
    return out


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
    warn_html += hint_badges(row.get("hints"))
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


def _fwd_summary(fwd):
    """前瞻紀錄卡片：持有中檔數、持有中平均損益、浮盈／浮虧檔數、已出場勝率與平均。"""
    if fwd is None or fwd.empty:
        return [("持有中", "0 檔"), ("持有中平均損益", "—"), ("浮盈／浮虧", "—"), ("已出場", "0 筆"), ("已出場勝率／平均", "—")]
    hold = fwd[fwd.status != "已出場"]
    done = fwd[fwd.status == "已出場"]
    g = hold.ret_gross * 100
    return [("持有中", f"{len(hold)} 檔"), ("持有中平均損益", f"{g.mean():+.2f}%" if len(hold) else "—"),
            ("浮盈／浮虧", f"{int((g > 0).sum())}／{int((g < 0).sum())}"), ("已出場", f"{len(done)} 筆"),
            ("已出場勝率／平均", f"{(done.ret_net_stock > 0).mean() * 100:.0f}%／{done.ret_net_stock.mean() * 100:+.2f}%" if len(done) else "—")]


def render_v2(cands, selected_code, workspace, history=None, picker=None):
    """前瞻紀錄頁：今日觀察／回測紀錄／前瞻紀錄。
    history(height)：app 繪製回測紀錄；picker(kind, df, height)：app 繪製可點選清單＋K 線（kind＝"today"｜"fwd"）。"""
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
    # 同一狀態內依個股 RS（10 日強於大盤 %）由強到弱：資金有限時先買最強的（docs 10.10：兩期回測都較好）
    if "rs10" not in scan:
        scan["rs10"] = np.nan
    today = scan[scan.state.isin(["signal3", "signal", "setup", "wave"])].sort_values(["order", "rs10"], ascending=[True, False])
    f3, f2 = _read_csv("forward_status_v3.csv"), _read_csv("forward_status.csv")
    t3, c3, s3 = _fwd_stats(f3)
    bull_txt = "—" if bull is None else ("多頭（可做多）" if bull else "空頭（不做多）")
    below3 = scan["idx_below3"].iloc[0] if "idx_below3" in scan and not scan.empty else None
    liao_txt = "" if below3 is None or below3 != below3 else (
        '<em title="廖崧沂 2.0：加權指數在 8、21、55 日均線全部之下才不做多（參考，現行仍用 60MA）">'
        + ("2.0：在 8/21/55 之下" if bool(below3) else "2.0：未全破 8/21/55") + "</em>")
    views = ["今日訊號", "歷史回測", "實盤追蹤"]
    tcol, vcol = st.columns([1.25, 1], gap="small", vertical_alignment="center")
    with vcol:
        view = tabs("訊號績效頁面", views, "fwd_view")
    with tcol:
        st.markdown(f'<div class="sig-head"><b>蕭氏日線訊號</b><span title="{escape(source)}">資料日 {asof} · '
                    f'{"排程掃描" if "排程" in source else "即時計算（候選股）"}</span></div>', unsafe_allow_html=True)
    with st.container():
        if view == "歷史回測":
            if history is not None:
                history(max(420, workspace - 50))
        elif view == "實盤追蹤":
            _view_tracking(f3, f2, picker, max(360, workspace - 140))
        else:
            _view_today(today, scan, bull_txt, liao_txt, t3, s3, picker, selected_code, max(360, workspace - 140))


def _keep_selection(key):
    """segmented_control 再點一次已選的項目會變成「未選」；這裡把它還原成原本的選項。"""
    if st.session_state.get(key) is None:
        st.session_state[key] = st.session_state.get(f"_prev_{key}")


def tabs(label, options, key, default=None):
    """頁籤（segmented_control）：一定有一個被選取，點已選的頁籤不會取消。舊名稱留在 session 時自動重設成預設值。"""
    default = default or options[0]
    if st.session_state.get(key) not in [None] + list(options):
        st.session_state[key] = default
    value = st.segmented_control(label, options, default=default, key=key, label_visibility="collapsed",
                                 on_change=_keep_selection, args=(key,)) or default
    st.session_state[f"_prev_{key}"] = value
    return value


def _card_row(cards, first_extra=""):
    st.markdown(f'<div class="sig-cards" style="grid-template-columns:repeat({len(cards)},minmax(0,1fr))">'
                + "".join(f'<div class="sig-card"><span>{a}</span><b style="font-size:{18 if len(str(b)) > 8 else 21}px">{b}</b>'
                          + (first_extra if i == 0 else "") + "</div>" for i, (a, b) in enumerate(cards)) + "</div>", unsafe_allow_html=True)


def _view_tracking(f3, f2, picker, avail):
    """實盤追蹤：排程每天實際記下的訊號，追蹤持倉損益與出場。"""
    wcol, gcol = st.columns([1, 2.2], gap="small", vertical_alignment="center")
    with wcol:
        which = tabs("實盤追蹤策略", ["v3 波段量啟動", "v2 凹洞量轉折"], "fwd_which")
    with gcol:
        st.markdown('<div class="sig-guide" style="margin:0">本機排程每天 14:45 實際記下的訊號（不是回測），用同一套出場規則追蹤到今天，'
                    '是真正的樣本外成績。點選任一筆看 K 線與進出場位置。</div>', unsafe_allow_html=True)
    fwd = f3 if which.startswith("v3") else f2
    _card_row(_fwd_summary(fwd))
    if fwd is None or fwd.empty:
        st.markdown('<div class="sig-note">尚無紀錄。排程每個交易日 14:45 執行，出現訊號（且大盤為多頭）時才會記錄；累積 2～3 個月才有參考價值。</div>', unsafe_allow_html=True)
    else:
        picker("fwd", fwd, avail - 40)


def _view_today(today, scan, bull_txt, liao_txt, t3, s3, picker, selected_code, avail):
    """今日訊號：今天收盤的掃描結果（可買訊號、量縮整理、波段進行中）。"""
    n = lambda k: int((scan.state == k).sum())
    cards = [("大盤濾網（60MA）", bull_txt), ("今日 v3 波段量啟動", n("signal3")), ("今日 v2 凹洞量轉折", n("signal")),
             ("量縮整理／波段進行中", f"{n('setup')}／{n('wave')}"), ("v3 實盤追蹤", f"{t3} 筆"), ("v3 實盤勝率／平均", s3)]
    _card_row(cards, liao_txt)
    st.markdown('<div class="sig-guide"><b>v3／v2 訊號</b>＝今天收盤可買（停損欄是失敗出場價）；'
                '<i>量縮整理中</i>＝放入觀察，等它轉成訊號才買，不要提前進場。'
                '<span style="color:#9cc7f5">波段進行中</span>＝已經在漲：持股續抱，未持有不追，等它量縮回檔變成整理再看。點選任一檔看 K 線。</div>', unsafe_allow_html=True)
    if today.empty:
        st.info("今天沒有訊號、量縮整理或波段進行中的股票。")
    else:
        picker("today", today.assign(label=today.state.map(lambda k: V2_STATE.get(k, (k, "", 9))[0])), avail - 84)   # 下方還有「規則與徽章說明」
    _rules_note()


def _rules_note():
    with st.expander("規則與徽章說明"):
        st.markdown('<div class="sig-note">v3（主）：5MV 帶出 13MV 的第一天、34MV 上揚，當天強於大盤且收在上半部；站上並扣低 21MA、強於大盤、族群強且族群前三，'
                    '只做電子／重電／綠能 → 收盤買，停損前 3 日低點，收盤虧損超過 10% 全出，其餘出場同 v2（跌破 21MA、均線扣高、極限大量後量縮不見高先出 1/3）。'
                    '完整的歷史交易與績效見「歷史回測」。v2：攻擊後回檔量縮、凹洞量轉折買，樣本少。回測不保證未來，請以「實盤追蹤」為準。<br>'
                    '<span class="sig-hint">紫色</span>／<span class="sig-hint up">紅色</span>徽章＝林教授、廖崧沂 2.0 的參考提醒（偏空／偏多），'
                    '不影響訊號與紀錄；滑鼠移到徽章上可看規則與回測結論。回測顯示當成固定出場規則會降低報酬，持股可當減碼或提高警覺的參考。</div>', unsafe_allow_html=True)


# ======================= v1：盤中 15 分 K =======================
