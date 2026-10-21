"""CQR 華南介面：網頁登入彈窗、MT5 風格買賣按鈕＋委託設定、帳務資訊頁。
橋接程式 huanan_bridge.py 會在登入時由這裡自動啟動（--serve-only），網頁結束時一併結束。
"""
import os
import socket
import subprocess
import sys
import time
from html import escape
from pathlib import Path
from urllib.parse import urlparse

import requests
import streamlit as st

HERE = Path(__file__).resolve().parent
BRIDGE = os.environ.get("CQR_HN_BRIDGE", "http://127.0.0.1:8766")
DEFAULT_SERVER = "fvipb.entrust.com.tw"
PRICE_TYPE = {"限價": "L", "市價": "M", "範圍市價": "P"}
EFF = {"ROD": "R", "IOC": "I", "FOK": "F"}
OPEN_CLOSE = {"自動": "", "新倉": "0", "平倉": "1", "當沖": "2"}
ORDER_COLUMNS = {"ORDERNO": "委託書號", "ORDERTIME": "時間", "BS": "買賣", "PRODUCTID": "商品", "ORDERPRICE": "價格",
                 "ORDERQTY": "委託量", "MATCHQTY": "成交量", "NOMATCHQTY": "未成交", "DELQTY": "刪除量", "ORDERSTATUS": "狀態"}

CSS = """<style>
.st-key-hn_sell div button,.st-key-hn_buy div button{height:46px!important;border-radius:8px!important;color:#fff!important;width:100%}
.st-key-hn_sell div button p,.st-key-hn_buy div button p{font-size:20px!important;font-weight:700!important;font-variant-numeric:tabular-nums;letter-spacing:.4px;line-height:1.1!important}
.st-key-hn_sell div button{background:linear-gradient(#2f9a7b,#1f6e57)!important;border:1px solid #55c8a4!important}
.st-key-hn_buy div button{background:linear-gradient(#cc5559,#a13d42)!important;border:1px solid #f17c7e!important}
.st-key-hn_pair [data-testid="stHorizontalBlock"]{gap:4px!important}
.st-key-hn_sell div button:hover{filter:brightness(1.12)}
@media(max-width:1500px){.st-key-hn_sell div button p,.st-key-hn_buy div button p{font-size:17px!important}.hn-name{font-size:24px!important}}.st-key-hn_buy div button:hover{filter:brightness(1.12)}
.hn-head{display:flex;align-items:center;gap:10px;height:auto}.hn-name{font-size:27px;font-weight:700;line-height:1.2;color:#f3eee2;white-space:nowrap}
.hn-pill{display:inline-block;border-radius:20px;padding:4px 10px;font-size:13px;font-weight:650;white-space:nowrap}
.hn-pill.paper{background:#1f3a31;color:#9fe2c6;border:1px solid #2f7a5f}.hn-pill.live{background:#4a1f22;color:#ffb3b5;border:1px solid #a8474b}.hn-pill.off{background:#1d1b16;color:#9a9383;border:1px solid #3d3527}
.hn-note{color:#9a9383;font-size:13px}
[data-testid="stDialog"] [data-testid="stBaseButton-primaryFormSubmit"] p{color:#15110a!important;font-weight:700;font-size:17px}
.st-key-hn_ticket_panel{position:fixed!important;top:238px;right:26px;width:min(500px,46vw);z-index:1000;background:#100f0e!important;border:1px solid #67583b!important;border-radius:12px!important;padding:14px 16px 12px!important;box-shadow:0 18px 44px rgba(0,0,0,.6)}
.hn-ticket-title{font-size:19px;font-weight:700;margin-bottom:4px}.hn-ticket-title.buy{color:#f17c7e}.hn-ticket-title.sell{color:#55c8a4}
.hn-ticket-sum{background:#1d1b16;border-radius:8px;padding:9px 12px;color:#dbe3ee;font-size:15px;line-height:1.7;margin:6px 0 8px}
.hn-ticket-sum b{color:#f1d9a0}
.st-key-hn_confirm_B div button{background:linear-gradient(#cc5559,#a13d42)!important;border:1px solid #f17c7e!important;color:#fff!important;font-weight:700}
.st-key-hn_confirm_S div button{background:linear-gradient(#2f9a7b,#1f6e57)!important;border:1px solid #55c8a4!important;color:#fff!important;font-weight:700}
.acct-cards{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin:2px 0 12px}
.acct-card{background:linear-gradient(115deg,#19170f,#0c0b0a);border:1px solid #2f2a1f;border-radius:10px;padding:10px 14px;min-width:0}
.acct-card span{display:block;color:#9b9484;font-size:13px;white-space:nowrap}.acct-card b{display:block;font-size:22px;font-weight:600;color:#f0eadb;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.acct-title{font-size:17px;font-weight:650;color:#efe9da;margin:12px 0 6px;display:flex;justify-content:space-between;align-items:baseline}.acct-title small{font-size:12px;color:#8e8778;font-weight:400}
table.acct{width:100%;border-collapse:collapse;background:#0e0d0c;border:1px solid #332d21;border-radius:10px;overflow:hidden;font-size:15px}
table.acct th{background:#1b1914;color:#aebacb;font-weight:500;text-align:right;padding:9px 10px;border-bottom:1px solid #352f22;white-space:nowrap}
table.acct td{text-align:right;padding:8px 10px;border-bottom:1px solid #1f1d18;color:#cbd4e1;font-variant-numeric:tabular-nums;white-space:nowrap}
table.acct th:first-child,table.acct td:first-child{text-align:left}table.acct tr:nth-child(odd) td{background:#0f0e0d}table.acct tr:hover td{background:#25221b}
table.acct .empty{text-align:center;color:#8e8778;padding:18px}.acct-up{color:#f17c7e!important}.acct-down{color:#55c8a4!important}
.acct-gate{border:1px dashed #3d3527;border-radius:12px;padding:30px;text-align:center;color:#a8a191;font-size:16px;margin-top:10px}
@media(max-width:1100px){.acct-cards{grid-template-columns:repeat(3,minmax(0,1fr))}}
</style>"""


# ---------- 橋接程式連線 ----------
def _get(path, timeout=3, **params):
    try:
        r = requests.get(BRIDGE + path, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _post(path, payload, timeout=30):
    _STATUS["t"] = 0.0  # 登入／登出／下單後重新查狀態
    try:
        r = requests.post(BRIDGE + path, json=payload, timeout=timeout, headers={"X-CQR-Confirm": "1"})
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"ok": False, "message": f"橋接程式無回應：{exc}"}


_STATUS = {"t": 0.0, "v": None}


def _bridge_up(timeout=0.15):
    """先用 socket 快速探測連接埠：橋接程式沒開時，Windows 對 localhost 的拒絕連線要重試約 1～2 秒，會拖慢每次換頁。"""
    u = urlparse(BRIDGE)
    try:
        with socket.create_connection((u.hostname, u.port or 80), timeout=timeout):
            return True
    except OSError:
        return False


def status(fresh=False):
    """橋接程式狀態；2 秒內重複查詢直接用上次結果（同一次畫面會查好幾次）。"""
    now = time.monotonic()
    if not fresh and now - _STATUS["t"] < 2.0:
        return _STATUS["v"]
    value = _get("/status", timeout=1.5) if _bridge_up() else None
    _STATUS.update(t=now, v=value)
    return value


def is_logged_in(info=None):
    info = info if info is not None else status()
    return bool(info and info.get("logged_in"))


def _start_bridge(live):
    log = open(HERE / "huanan_bridge.log", "ab")  # 不含密碼；只有橋接程式的狀態訊息
    command = [sys.executable, str(HERE / "huanan_bridge.py"), "--serve-only", "--parent-pid", str(os.getpid()),
               "--port", str(urlparse(BRIDGE).port or 8766)]
    if live:
        command.append("--live")
    subprocess.Popen(command, cwd=str(HERE), stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=0x08000000)  # CREATE_NO_WINDOW
    for _ in range(60):  # 載入 .NET 元件，最多等 15 秒
        time.sleep(0.25)
        if status(fresh=True) is not None:
            return True
    return False


def _fmt(value, digits=2):
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return escape(str(value)) if value not in (None, "") else "—"
    text = f"{number:,.{digits}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text  # 只去小數尾端的零，整數的零要保留


def _num(value, default=None):
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


# ---------- 登入彈窗與頁首按鈕 ----------
@st.dialog("券商登入")
def login_dialog():
    info = status(fresh=True)
    if is_logged_in(info):
        st.success(f"已登入華南永昌 · {info['user']}")
        st.caption(f"{'LIVE 正式下單' if info['live'] else 'PAPER 紙上模式'} · 主機 {info['server']}")
        if st.button("登出", use_container_width=True):
            _post("/logout", {"exit": True})
            st.rerun()
        return
    st.caption("帳號與密碼只傳給你這台電腦上的橋接程式，用完即丟，不會存檔或記錄。")
    with st.form("hn_login_form", border=False):
        st.selectbox("券商", ["華南永昌（期貨）"], help="目前網頁登入只支援華南永昌。")
        user = st.text_input("身分證字號／交易帳號", key="hn_login_id", autocomplete="off")
        password = st.text_input("密碼", type="password", key="hn_login_pw", autocomplete="off")
        with st.expander("進階設定"):
            server = st.text_input("登入主機", value=DEFAULT_SERVER)
            live = st.checkbox("正式下單模式（會真的送出委託）", value=False,
                               help="預設為紙上模式：登入、查詢都正常，但委託只記錄、不會送到交易所。")
            if live:
                st.warning("正式模式：之後按下確認的委託都會真的送到交易所。")
        submit = st.form_submit_button("登入", type="primary", use_container_width=True)
    if not submit:
        return
    try:
        st.session_state.pop("hn_login_pw", None)  # 密碼不留在 session；欄位已被使用者送出
    except Exception:
        pass
    with st.spinner("登入中…（華南限制每 5 秒登入 1 次）"):
        running = status(fresh=True)
        if running is not None and bool(running.get("live")) != live:
            _post("/logout", {"exit": True})  # 模式不同：重啟橋接程式
            time.sleep(1.2)
            running = None
        if running is None and not _start_bridge(live):
            st.error("橋接程式啟動失敗，請查看 huanan_bridge.log。")
            return
        result = _post("/login", {"id": user, "password": password, "server": server}, timeout=75)
        password = None
    if result.get("ok"):
        st.rerun()
    st.error(result.get("message") or result.get("error") or "登入失敗")


def login_control():
    info = status()
    if is_logged_in(info):
        with st.popover(f"● 華南 {info['user']}", use_container_width=True):
            st.markdown(f"**華南永昌** · {'🔴 LIVE 正式下單' if info['live'] else '🟢 PAPER 紙上模式'}")
            st.caption(f"帳號 {', '.join(info['accounts']) or '—'} · {info['server']}")
            if st.button("登出", key="hn_logout", use_container_width=True):
                _post("/logout", {"exit": True})
                st.rerun()
    elif st.button("登入", key="hn_login_btn", use_container_width=True):
        login_dialog()


# ---------- MT5 風格買賣 ----------
def _price(*values):
    for value in values:
        number = _num(value)
        if number:
            return number
    return None


def _short(number):
    return "—" if number is None else _fmt(number)


def render_ticket(code, name):
    """已登入：每 3 秒更新報價；未登入：不自動重跑（否則網頁一直在執行，換頁要排隊）。"""
    if is_logged_in(status()):
        _ticket_live(code, name)
    else:
        _ticket_idle(code, name)


def _ticket(code, name):
    info = status()
    logged = is_logged_in(info)
    products = []
    if logged:
        found = _get("/products", q=name) or []
        # 只收完整名稱相符的合約：「台塑」不能抓到「台塑化期貨」。小型合約（如 小型台積電期貨）一併列出。
        products = [p for p in found if p["desc"] in (f"{name}期貨", f"小型{name}期貨")]
    cols = st.columns([1.45, 2.0, 2.6, .85, 1.0], vertical_alignment="center", gap="small")
    cols[0].markdown(f'<div class="hn-head"><span class="hn-name">{escape(name)}</span><span class="stock-code">{escape(code)}</span></div>', unsafe_allow_html=True)
    if not logged:
        cols[1].markdown('<span class="hn-note">登入後可直接下單</span>', unsafe_allow_html=True)
    elif not products:
        cols[1].markdown(f'<span class="hn-note">{escape(name)} 沒有對應期貨</span>', unsafe_allow_html=True)
    product, bid, ask = None, None, None
    if products:
        labels = {f'{p["desc"]} {p["id"]} · {p["period"][:4]}/{p["period"][4:6]}': p for p in products}
        product = labels[cols[1].selectbox("期貨月份", list(labels), key=f"hn_prod_{code}", label_visibility="collapsed")]
        quote = _get("/quote", code=product["id"]) or {}
        last = _price(quote.get("price"), quote.get("close"), product.get("close"))
        bid, ask = _price(quote.get("bid"), last), _price(quote.get("ask"), last)
    with cols[2]:
        with st.container(key="hn_pair"):  # 賣出／買進並排靠攏（MT5 風格）；口數改到按下後的委託設定裡決定
            sell_col, buy_col = st.columns(2, gap="small")
            sell_clicked = sell_col.button(f"賣出  {_short(bid)}", key="hn_sell", use_container_width=True, disabled=logged and not product)
            buy_clicked = buy_col.button(f"買進  {_short(ask)}", key="hn_buy", use_container_width=True, disabled=logged and not product)
    mode = "off" if not logged else ("live" if info["live"] else "paper")
    cols[3].markdown(f'<span class="hn-pill {mode}">{ {"off": "未登入", "live": "LIVE", "paper": "紙上"}[mode] }</span>', unsafe_allow_html=True)

    if sell_clicked or buy_clicked:
        if not logged:
            login_dialog()
            return
        side = "S" if sell_clicked else "B"
        st.session_state["hn_ticket"] = side
        st.session_state["hn_px"] = float((bid if side == "S" else ask) or 0.0)
    side = st.session_state.get("hn_ticket")
    if side and product and logged:
        _ticket_panel(side, product, info, bid, ask)


_ticket_live = st.fragment(run_every="3s")(_ticket)
_ticket_idle = st.fragment(_ticket)


def _ticket_panel(side, product, info, bid, ask):
    word, cls = ("買進", "buy") if side == "B" else ("賣出", "sell")
    with st.container(key="hn_ticket_panel", border=True):
        st.markdown(f'<div class="hn-ticket-title {cls}">{word} {escape(product["desc"])} <span style="color:#cfae5c;font-size:15px">{escape(product["id"])}</span></div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        ptype = c1.segmented_control("價格類型", list(PRICE_TYPE), default="限價", key="hn_ptype") or "限價"
        eff_options = list(EFF) if ptype == "限價" else ["IOC", "FOK"]
        eff = c2.segmented_control("委託條件", eff_options, default=eff_options[0], key=f"hn_eff_{ptype}") or eff_options[0]
        oof = st.segmented_control("新平倉", list(OPEN_CLOSE), default="自動", key="hn_oof") or "自動"
        c3, c4, c5 = st.columns([1, 1.2, 1])
        max_lots = int(info.get("max_lots") or 5)
        qty = int(c3.number_input("口數", min_value=1, max_value=max_lots, value=1, step=1, key="hn_qty"))  # 每次開啟都從 1 口開始
        price = c4.number_input("限價", min_value=0.0, step=1.0, format="%.2f", key="hn_px", disabled=ptype != "限價")
        accounts = info["accounts"]
        account = c5.selectbox("帳號", accounts, key="hn_acc") if len(accounts) > 1 else accounts[0]
        if len(accounts) <= 1:
            c5.markdown(f'<div class="hn-note" style="padding-top:30px">帳號 {escape(account)}</div>', unsafe_allow_html=True)
        shown = f'限價 <b>{price:g}</b>' if ptype == "限價" else ptype
        st.markdown(f'<div class="hn-ticket-sum">{word} <b>{qty}</b> 口 · {shown} · {eff} · {oof}<br>'
                    f'帳號 {escape(account)} · {"<b style=color:#ffb3b5>LIVE：會真的送出委託</b>" if info["live"] else "紙上模式：只記錄，不會送到交易所"}</div>', unsafe_allow_html=True)
        ok_col, cancel_col = st.columns([2, 1])
        label = f"確認{word}" + ("（正式）" if info["live"] else "")
        ready = ptype != "限價" or price > 0
        if ok_col.button(label, key=f"hn_confirm_{side}", use_container_width=True, disabled=not ready):
            result = _post("/order", {"account": account, "symbol": product["id"], "bs": side, "qty": qty,
                                      "price": f"{price:g}" if ptype == "限價" else "0", "price_type": PRICE_TYPE[ptype],
                                      "eff": EFF[eff], "oof": OPEN_CLOSE[oof], "confirm": True})
            st.session_state.pop("hn_ticket", None)
            text = (result.get("result") or result.get("message") or result.get("error") or "").strip()
            st.toast(f'{"✅" if result.get("ok") else "❌"} {result.get("mode", "")} {word} {product["id"]} {qty}口 — {text}')
            st.rerun(scope="fragment")
        if cancel_col.button("取消", key="hn_ticket_cancel", use_container_width=True):
            st.session_state.pop("hn_ticket", None)
            st.rerun(scope="fragment")


# ---------- 帳務資訊 ----------
def _table(headers, rows, empty="目前沒有資料"):
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    if not rows:
        return f'<table class="acct"><tr>{head}</tr><tr><td class="empty" colspan="{len(headers)}">{empty}</td></tr></table>'
    return f'<table class="acct"><tr>{head}</tr>' + "".join("<tr>" + "".join(f"<td{c}>{v}</td>" for v, c in row) + "</tr>" for row in rows) + "</table>"


def _side_cell(bs):
    return ("買" if bs == "B" else "賣" if bs == "S" else escape(str(bs)), ' class="acct-up"' if bs == "B" else ' class="acct-down"' if bs == "S" else "")


def _pnl_cell(value):
    number = _num(value)
    return (_fmt(value, 0), ' class="acct-up"' if number and number > 0 else ' class="acct-down"' if number and number < 0 else "")


@st.fragment(run_every="5s")
def render_account(workspace):
    info = status()
    if not is_logged_in(info):
        st.markdown('<div class="acct-gate">尚未登入券商。登入後可查看保證金、部位、委託與成交。</div>', unsafe_allow_html=True)
        if st.button("登入華南永昌", key="hn_gate_login"):
            login_dialog()
        return
    data = _get("/positions") or {"positions": {}, "margin": {}}
    replies = _get("/replies") or {"orders": [], "matches": []}
    accounts = info["accounts"]
    account = st.segmented_control("帳號", accounts, default=accounts[0], key="hn_acct_view", label_visibility="collapsed") if len(accounts) > 1 else accounts[0]
    margin = (data["margin"].get(account) or {})
    rows = data["positions"].get(account) or []
    floating = sum(_num(r.get("FLOAT_PROFIT"), 0) or 0 for r in rows)
    mode = "LIVE" if info["live"] else "PAPER"
    cards = [("帳號 · " + mode, escape(account)), ("權益數", _fmt(margin.get("EQUITY"), 0)), ("可用保證金", _fmt(margin.get("USABLE_MARGIN"), 0)),
             ("原始保證金", _fmt(margin.get("INITIAL_MARGIN"), 0)), ("風險指標", _fmt(margin.get("RISK_RATE"))), ("浮動損益", f"{floating:+,.0f}")]
    st.markdown('<div class="acct-cards">' + "".join(f'<div class="acct-card"><span>{label}</span><b>{value}</b></div>' for label, value in cards) + "</div>", unsafe_allow_html=True)

    st.markdown(f'<div class="acct-title">即時部位<small>約每 10 秒更新 · 保證金約每 35 秒更新（華南限制查詢頻率）</small></div>', unsafe_allow_html=True)
    st.markdown(_table(["商品", "名稱", "買賣", "口數", "均價", "市價", "浮動損益"],
                       [[(escape(r.get("PRODUCTID", "")), ""), (escape(r.get("PRODUCTDESC", "")), ""), _side_cell(r.get("BS")), (_fmt(r.get("POSITION_QTY"), 0), ""),
                         (_fmt(r.get("POSITION_PRICE")), ""), (_fmt(r.get("MARKET_PRICE")), ""), _pnl_cell(r.get("FLOAT_PROFIT"))] for r in rows],
                       "目前沒有部位"), unsafe_allow_html=True)

    mine = [o for o in replies["orders"] if o.get("INVESTORACNO") in (account, "")]
    st.markdown('<div class="acct-title">委託回報<small>含在其他軟體下的單</small></div>', unsafe_allow_html=True)
    st.markdown(_table(["委託書號", "時間", "買賣", "商品", "價格", "委託量", "成交量", "未成交", "狀態"],
                       [[(escape(o.get("ORDERNO", "")), ""), (escape(o.get("ORDERTIME", "")), ""), _side_cell(o.get("BS")), (escape(o.get("PRODUCTID", "")), ""),
                         (_fmt(o.get("ORDERPRICE")), ""), (_fmt(o.get("ORDERQTY"), 0), ""), (_fmt(o.get("MATCHQTY"), 0), ""),
                         (_fmt(o.get("NOMATCHQTY"), 0), ""), (escape(o.get("ORDERSTATUS", "")), "")] for o in mine[:30]], "今日尚無委託"), unsafe_allow_html=True)
    pending = [o for o in mine if (_num(o.get("NOMATCHQTY"), 0) or 0) > 0]
    if pending:
        with st.expander("刪單（列出未成交量 > 0 的委託；狀態欄請自行確認是否已刪除）"):
            options = {f'{o["ORDERNO"]} · {o["PRODUCTID"]} · {"買" if o["BS"] == "B" else "賣"} · 價 {_fmt(o["ORDERPRICE"])} · 未成交 {_fmt(o["NOMATCHQTY"], 0)}': o for o in pending}
            picked = options[st.selectbox("委託", list(options), key="hn_cancel_pick")]
            if st.button(f'送出刪單 {picked["ORDERNO"]}', key="hn_cancel_send"):
                result = _post("/cancel", {"account": picked["INVESTORACNO"], "orderno": picked["ORDERNO"], "confirm": True})
                st.toast(f'{"✅" if result.get("ok") else "❌"} 刪單 {picked["ORDERNO"]}：{result.get("result") or result.get("message") or result.get("error") or ""}')

    st.markdown('<div class="acct-title">成交回報</div>', unsafe_allow_html=True)
    st.markdown(_table(["委託書號", "時間", "買賣", "商品", "成交價", "口數"],
                       [[(escape(m.get("ORDERNO", "")), ""), (escape(m.get("MATCHTIME", "")), ""), _side_cell(m.get("BS")), (escape(m.get("PRODUCTID", "")), ""),
                         (_fmt(m.get("MATCHPRICE")), ""), (_fmt(m.get("MATCHQTY"), 0), "")] for m in replies["matches"][:30]], "今日尚無成交"), unsafe_allow_html=True)

    logs = _get("/orders") or []
    st.markdown('<div class="acct-title">本機送單紀錄<small>此網頁送出的委託（含紙上模式）</small></div>', unsafe_allow_html=True)
    st.markdown(_table(["時間", "模式", "動作", "商品", "買賣", "口數", "價格", "結果"],
                       [[(escape(str(x.get("time", ""))[11:19]), ""), (escape(x.get("mode", "")), ""), ("刪單" if x.get("action") == "cancel" else "下單", ""),
                         (escape(str(x.get("pid", x.get("orderno", "")))), ""), _side_cell(x.get("bs")), (_fmt(x.get("qty"), 0), ""),
                         (_fmt(x.get("price")) if x.get("ptype", "L") == "L" else {"M": "市價", "P": "範圍市價"}.get(x.get("ptype"), "—"), ""),
                         (escape(str(x.get("result", ""))[:40]), "")] for x in logs[::-1][:20]], "尚無紀錄"), unsafe_allow_html=True)
    with st.expander("橋接程式訊息／API 錯誤"):
        st.code("\n".join(info.get("errors", [])[::-1] + [""] + info.get("messages", [])[::-1]) or "—", language=None)
