"""蕭明道量價規則 v2（日線波段）：共用模組。
回測（research/backtest_swing_v2.py）、每日訊號排程（daily_signals.py）、儀表板面板（xiao_panel.py）
三邊都用這裡的函式，確保規則一模一樣。規則出處見 docs/蕭明道量價規則整理.md。

v2 精神：不追突破，在「攻擊（量增價漲）→ 回檔量縮價穩 → 凹洞量回升」的轉折點買；
良性回檔抱住，極限大量後量縮不見高先出一半，跌破 21MA／均線扣高反轉／跌破回檔低點全出。
"""
import numpy as np
import pandas as pd

import xiao_rules as xr

# 流動性與盤前條件（股價門檻 50：2015-2020 設計期比較後決定，驗證期只跑一次）
P = dict(min_price=50, min_value=3e8)
# 型態與出場參數（依影片與 2015-2020 設計期決定）
Q = dict(push_min=2, push_max=12, attack=1.5, pull_vol=0.7, spike=3.0, climax=2.5, top_in_sector=3, big=2.0)
MAX_HOLD = 60


# ---------------------------------------------------------------- 指標
def prep_daily(d, idx_close):
    """d：Yahoo 日 K（含 Open/High/Low/Close/Adj Close/Volume，index 為日期）。回傳指標 DataFrame；資料不足回 None。"""
    d = d[(d["Volume"] > 0) & (d["Close"] > 0)].copy()
    if len(d) < 120:
        return None
    adj = d["Adj Close"] if "Adj Close" in d else d["Close"]
    f = (adj / d["Close"]).fillna(1.0)
    o, h, l, c = d["Open"] * f, d["High"] * f, d["Low"] * f, adj
    v, raw = d["Volume"], d["Close"]
    x = pd.DataFrame({"o": o, "h": h, "l": l, "c": c, "v": v, "raw": raw})
    x["avgv"] = v.rolling(20).mean().shift(1)                         # 前 20 日均量（不含當日）
    x["value20"] = (raw * v).rolling(20).mean()
    x["ma8"], x["ma21"] = c.rolling(8).mean(), c.rolling(21).mean()
    x["fast_up"] = xr.ma_will_rise(c, 8) > 0                          # 扣低：8MA 將上揚（活動靶）
    x["slow_up"] = xr.ma_will_rise(c, 21) > 0
    ic = idx_close.reindex(x.index).ffill()
    x["rs10"] = (c / c.shift(10) - ic / ic.shift(10)) * 100            # 相對大盤強弱
    up = c > c.shift(1)
    x["vol_peak"] = v.where(up).rolling(10, min_periods=3).mean() / v.where(~up).rolling(10, min_periods=3).mean()
    x["liquid"] = (raw >= P["min_price"]) & (x.value20 >= P["min_value"])
    x["pre_ok"] = x.liquid & (c > x.ma21) & x.fast_up & x.slow_up & (x.rs10 > 0) & (x.vol_peak >= 1)
    x["push"] = (v >= Q["attack"] * x.avgv) & (c > o) & (c > c.shift(1))     # 攻擊量、量增價漲
    x["big"] = v >= Q["big"] * x.avgv
    x["slip"] = raw.map(xr.tick_size) / raw
    return x


def sector_strength(data, sector_of, idx_close, days=10):
    """族群強弱（等權 days 日報酬 − 大盤）與族群內排名（只在可交易股票中、依 rs10）。回傳 (sec_rs, sec_rank) 兩個 dict。"""
    closes = pd.DataFrame({t: x.c for t, x in data.items()})
    rs10 = pd.DataFrame({t: x.rs10 for t, x in data.items()})
    liquid = pd.DataFrame({t: x.liquid for t, x in data.items()})
    idx_ret = (idx_close / idx_close.shift(days) - 1).reindex(closes.index)
    sec_rs, sec_rank = {}, {}
    for sec in {sector_of.get(t, "") for t in data}:
        cols = [t for t in data if sector_of.get(t, "") == sec]
        srs = (closes[cols] / closes[cols].shift(days) - 1).mean(axis=1).sub(idx_ret) * 100
        rank = rs10[cols].where(liquid[cols]).rank(axis=1, ascending=False)
        for t in cols:
            sec_rs[t], sec_rank[t] = srs, rank[t]
    return sec_rs, sec_rank


def sector_strength_multi(data, groups, idx_close, days=10):
    """一檔可屬多個族群（產業鏈細分）。groups：{族群: [ticker...]}。
    每檔的 sec_rs＝它所屬族群中「它排前三名的族群」的最強族群強度（沒有排前三就取所屬族群最強者），
    sec_rank＝它在「強於大盤的族群」裡的最佳名次（沒有就取所有族群裡的最佳名次）。
    這樣 v3 的「族群強且族群前三」＝存在某個強勢族群，它在裡面排前三。回傳 (sec_rs, sec_rank) 兩個 dict。"""
    closes = pd.DataFrame({t: x.c for t, x in data.items()})
    rs10 = pd.DataFrame({t: x.rs10 for t, x in data.items()}).reindex(closes.index)
    liquid = pd.DataFrame({t: x.liquid for t, x in data.items()}).reindex(closes.index).fillna(False).astype(bool)
    idx_ret = (idx_close / idx_close.shift(days) - 1).reindex(closes.index)
    g_rs, g_rank = {}, {}
    for g, members in groups.items():
        cols = [t for t in members if t in data]
        if len(cols) < 3:
            continue
        g_rs[g] = (closes[cols] / closes[cols].shift(days) - 1).mean(axis=1).sub(idx_ret) * 100
        g_rank[g] = rs10[cols].where(liquid[cols]).rank(axis=1, ascending=False)
    member_of = {}
    for g in g_rs:
        for t in g_rank[g].columns:
            member_of.setdefault(t, []).append(g)
    sec_rs, sec_rank = {}, {}
    for t in data:
        gs = member_of.get(t, [])
        if not gs:
            sec_rs[t] = pd.Series(np.nan, index=closes.index)
            sec_rank[t] = pd.Series(np.nan, index=closes.index)
            continue
        R = pd.DataFrame({g: g_rs[g] for g in gs})
        K = pd.DataFrame({g: g_rank[g][t] for g in gs})
        top3 = K <= Q["top_in_sector"]
        strong = R > 0
        rs_top = R.where(top3).max(axis=1)
        sec_rs[t] = rs_top.fillna(R.max(axis=1))
        sec_rank[t] = K.where(strong).min(axis=1).fillna(K.min(axis=1))
    return sec_rs, sec_rank


def add_features(x, sector_rs, sector_rank, idx_close):
    v = x.v
    x["vma5"], x["vma13"], x["vma21"] = v.rolling(5).mean(), v.rolling(13).mean(), v.rolling(21).mean()
    x["money_in"] = (x.vma5 > x.vma13) & (x.vma13 > x.vma13.shift(1))      # 影片12：5MV 帶出 13MV
    x["ma8_up"], x["ma21_up"] = x.fast_up, x.slow_up
    x["sec_rs"] = sector_rs.reindex(x.index)
    x["sec_rank"] = sector_rank.reindex(x.index)
    ic = idx_close.reindex(x.index).ffill()
    x["mkt_bull"] = ic > ic.rolling(60).mean()                               # 影片7：空頭市場絕對不可追
    return x


def add_v3(x, idx_close):
    """v3 規則需要的欄位（2024 公益班等影片）。"""
    x["vma34"] = x.v.rolling(34).mean()
    x["ma55"] = x.c.rolling(55).mean()
    ic = idx_close.reindex(x.index).ffill()
    x["chg"] = x.c.pct_change()
    x["idx_chg"] = ic.pct_change()
    x["beat_mkt"] = x.chg > x.idx_chg                                        # 當天強於大盤（跟大盤比）
    x["self_strong"] = (x.c - x.l) >= 0.5 * (x.h - x.l)                      # 收在當日區間上半部（跟自己比，近似站上均價線）
    x["wave"] = (x.vma5 > x.vma13) & (x.vma5 > x.vma5.shift(1)) & (x.vma13 > x.vma13.shift(1))   # 波段攻擊量帶出潮汐量
    x["trend_vol"] = x.wave & (x.vma34 > x.vma34.shift(1))                  # 再帶出 34MV＝趨勢量能
    x["idx_below3"] = (ic < ic.rolling(8).mean()) & (ic < ic.rolling(21).mean()) & (ic < ic.rolling(55).mean())
    return x


# 林教授、廖崧沂 2.0 的參考提醒（docs 第十節）：回測當作規則沒有加分，只在面板上提示，不影響訊號。
# 鍵＝面板顯示文字；值＝(老師, 方向 up/down, 說明)
HINTS = {
    "三盤突破": ("2.0", "up", "收盤高於前兩根最高、量大於前 4 根，且 8>21>55（2.0 的買點）。"
                             "回測：當進場條件與 v3 差不多，僅供參考。"),
    "三盤跌破": ("2.0", "down", "收盤跌破前兩根最低（2.0：這一波結束）。"
                              "回測：當全部出場會砍掉大賺的單，持股可減碼參考，不必全出。"),
    "破8MA且下彎": ("2.0", "down", "收盤跌破 8MA 且 8MA 下彎（2.0：賣出；站回且翻揚再買）。"
                                "回測：當全部出場報酬變差，僅供參考。"),
    "破大量關鍵K": ("2.0", "down", "收盤跌破最近一根大量紅K（量 ≥ 5MV 1.5 倍）的低點（2.0：結構被破壞）。"
                                "回測：同時持有 10 檔略好、5 檔較差，僅供參考。"),
    "買進隔天破低": ("林", "down", "昨天出現訊號，今天收黑K且跌破昨天低點，或收盤跌回昨天收盤（林教授：失敗就出）。"
                                "回測：回撤明顯變小（5 檔 −29%→−17%），但報酬也變少，屬於取捨。"),
    "大盤破8/21/55": ("2.0", "down", "加權指數同時在 8、21、55 日均線之下（2.0：不做多）。"
                                  "現行濾網仍用 60MA：2.0 版設計期較好，驗證期沒有重現。"),
}


def teacher_hints(x, t=-1):
    """最後一根日 K 觸發了哪些老師提醒（回傳 HINTS 的鍵）。"""
    t = len(x) + t if t < 0 else t
    if t < 60:
        return []
    o, h, l, c, v = x.o.values, x.h.values, x.l.values, x.c.values, x.v.values
    out = []
    if (c[t] > max(h[t - 1], h[t - 2]) and v[t] > v[t - 4:t].max() and c[t] > o[t]
            and x.ma8.iat[t] > x.ma21.iat[t] > x.ma55.iat[t] and x.ma8.iat[t] > x.ma8.iat[t - 1]):
        out.append("三盤突破")
    if c[t] < min(l[t - 1], l[t - 2]):
        out.append("三盤跌破")
    if c[t] < x.ma8.iat[t] and x.ma8.iat[t] <= x.ma8.iat[t - 1]:
        out.append("破8MA且下彎")
    v5 = x.vma5.values
    key = [j for j in range(t - 20, t) if c[j] > o[j] and v[j] >= 1.5 * v5[j - 1]]
    if key and c[t] < l[key[-1]]:
        out.append("破大量關鍵K")
    sig_y = {i for i, _ in entries_wave(x, trend=True)} | {i for i, _ in entries_v2(x)}
    if t - 1 in sig_y and ((c[t] < o[t] and l[t] < l[t - 1]) or c[t] < c[t - 1]):
        out.append("買進隔天破低")
    if "idx_below3" in x and bool(x.idx_below3.iat[t]):
        out.append("大盤破8/21/55")
    return out


def after_climax(x, days=5):
    """區間極限大量之後、尚未再創新高的冷卻期（影片：極限大量後 5 天內量增也難讓 5MV 上揚，只要不見高 5MV 終究會退）。"""
    climax = (x.v >= Q["climax"] * x.avgv) & (x.h >= x.h.rolling(20).max())
    last = pd.Series(np.where(climax.values, np.arange(len(x)), np.nan), index=x.index).ffill()
    hi = x.h.where(climax).ffill()
    age = np.arange(len(x)) - last.values
    return pd.Series((age >= 1) & (age <= days) & (x.h.values <= hi.values), index=x.index)


def entries_wave(x, day_filter=True, trend=False, cooldown=False, gradual=False, life55=False, main_up=False):
    """v3 進場 B：波段量啟動（5MV 帶出 13MV 的第一天），當天強於大盤與自己、不是瞬間爆量。停損＝前 3 日最低。
    trend=True 時另外要求 34MV 上揚（趨勢量能）。
    cooldown=True：排除區間極限大量後尚未見新高的 5 天；gradual=True：當天量不超過前 20 日均量 2.5 倍（循序漸進的量）。"""
    start = x.wave & ~x.wave.shift(1, fill_value=False)
    base = (start & x.liquid & (x.c > x.ma21) & x.slow_up & (x.rs10 > 0)
            & (x.sec_rs > 0) & (x.sec_rank <= Q["top_in_sector"])
            & (x.c > x.o) & (x.c > x.c.shift(1))
            & (x.v <= Q["spike"] * x.vma5))
    if day_filter:
        base &= x.beat_mkt & x.self_strong
    if trend:
        base &= x.vma34 > x.vma34.shift(1)
    if cooldown:
        base &= ~after_climax(x)
    if gradual:
        base &= x.v <= Q["climax"] * x.avgv
    if life55:                                   # 影片：55MA 是生命線，翻揚才是多頭
        base &= x.ma55 > x.ma55.shift(1)
    if main_up:                                  # 影片：主升段＝均線多頭排列（8>21>55 且 55 上揚）
        base &= (x.ma8 > x.ma21) & (x.ma21 > x.ma55) & (x.ma55 > x.ma55.shift(1))
    low3 = x.l.rolling(3).min().values
    return [(t, low3[t]) for t in np.flatnonzero(base.values)]


# 老師偏好的族群（影片：塑化、水泥、金融再強也不做；以電子、重電、綠能為主）。v3 回測只做這些族群。
PREFERRED = {"半導體", "電腦及週邊設備", "光電業", "通信網路", "電子零組件", "電子通路", "資訊服務", "其他電子",
             "電機機械", "電器電纜", "綠能環保", "數位雲端"}


def checks_v3(x, t=-1):
    """v3 條件逐項（面板顯示用）。"""
    g = lambda col: bool(x[col].iat[t]) if pd.notna(x[col].iat[t]) else False
    return {"大盤多頭": g("mkt_bull"), "流動性": g("liquid"), "站上21MA": bool(x.c.iat[t] > x.ma21.iat[t]), "21MA扣低": g("slow_up"),
            "強於大盤": bool(x.rs10.iat[t] > 0), "族群強": bool(x.sec_rs.iat[t] > 0), "族群前三": bool(x.sec_rank.iat[t] <= Q["top_in_sector"]),
            "5MV>13MV": bool(x.vma5.iat[t] > x.vma13.iat[t]), "13MV↑": bool(x.vma13.iat[t] > x.vma13.iat[t - 1]),
            "34MV↑": bool(x.vma34.iat[t] > x.vma34.iat[t - 1]), "今日強於大盤": g("beat_mkt"), "收上半部": g("self_strong")}


def today_state3(x, preferred=True):
    """v3 今日狀態（最後一根日 K）：
       signal3 ＝ 波段量啟動（5MV 帶出 13MV、34MV 上揚，當天強於大盤與自己）— v3 主訊號，只在偏好族群成立
       signal  ＝ v2 凹洞量轉折
       wave    ＝ 波段進行中（5MV、13MV 都上揚且站上 21MA）：持股續抱，未持有不追
       setup / trend / none 同 v2
    另回傳 warn：持股出場警示（跌破 21MA、均線扣高、大量後量縮）。"""
    t = len(x) - 1
    base = today_state(x)
    info = dict(base, rule="v2" if base["state"] == "signal" else "")
    warn = []
    if x.c.iat[t] < x.ma21.iat[t]:
        warn.append("跌破21MA")
    if (not x.ma8_up.iat[t]) and (not x.ma21_up.iat[t]) and x.c.iat[t] < x.ma8.iat[t]:
        warn.append("8/21MA 扣高")
    if t >= 1 and x.v.iat[t - 1] >= 1.6 * x.vma5.iat[t - 2] and x.vma5.iat[t] < x.vma5.iat[t - 1] and x.h.iat[t] <= x.h.iat[t - 1]:
        warn.append("大量後量縮不見高")
    info["warn"] = "、".join(warn)
    info["hints"] = "、".join(teacher_hints(x))
    sig = dict(entries_wave(x, trend=True))
    if t in sig and bool(x.mkt_bull.iat[t]):
        if preferred:
            info.update(state="signal3", rule="v3", stop=sig[t], high=x.h.iat[t], push_date=x.index[t],
                        note="波段量啟動：5MV 帶出 13MV、34MV 上揚，當天強於大盤（收盤可買，停損＝前 3 日低點）")
            return info
        info["note"] = "波段量啟動，但非偏好族群（回測較弱，僅觀察）"
    if base["state"] in ("signal", "setup"):
        return info
    if bool(x.wave.iat[t]) and x.c.iat[t] > x.ma21.iat[t]:
        info.update(state="wave", note="波段進行中：5MV、13MV 上揚，持股續抱；未持有不追高，等量縮回檔")
    return info


# ---------------------------------------------------------------- 進場
def _last_push(x):
    ar = np.arange(len(x))
    lp = pd.Series(np.where(x.push.values, ar, np.nan), index=x.index).ffill().shift(Q["push_min"])
    return ar, lp


def _pullback_ok(x, p_, t):
    """攻擊日 p_ 之後到 t-1 的回檔是否為「量縮、角度緩、守住攻擊日低點、尚未突破」。回傳 (ok, 回檔低點, 攻擊段高點)。"""
    o_, h_, l_, c_, v_ = x.o.values, x.h.values, x.l.values, x.c.values, x.v.values
    k = p_ + int(np.argmax(h_[p_:t]))
    if k >= t - 1:
        return False, np.nan, h_[k]
    pull = slice(k + 1, t)
    leg_vol, pull_vol = v_[p_:k + 1].mean(), v_[pull].mean()
    up_slope = (h_[k] / c_[max(p_ - 1, 0)] - 1) / (k - p_ + 1)
    dn_slope = (h_[k] - c_[t - 1]) / h_[k] / (t - 1 - k)
    ok = (pull_vol <= Q["pull_vol"] * leg_vol            # 影片10/12：壓回量縮
          and dn_slope < 0.5 * up_slope                   # 影片10：壓回角度緩
          and l_[pull].min() > l_[p_])                    # 沒跌破攻擊日低點
    return ok, l_[pull].min(), h_[k]


def entries_v2(x):
    """凹洞量轉折（突破前買進）。回傳 [(t, 結構停損價)]。"""
    ar, lp = _last_push(x)
    base = (x.pre_ok & x.money_in & (x.sec_rs > 0) & (x.sec_rank <= Q["top_in_sector"])
            & (x.c > x.o) & (x.c > x.c.shift(1))                     # 量縮價穩後轉折：收紅、收高
            & (x.v > x.v.shift(1)) & (x.v > x.v.shift(5))            # 影片2：凹洞量回升且大於 5 天前（5MV 扣低上揚）
            & (x.v <= Q["spike"] * x.vma5)                           # 影片11：不是瞬間爆量
            & lp.notna() & ((ar - lp) <= Q["push_max"]))
    out = []
    for t in np.flatnonzero(base.values):
        p_ = int(lp.iloc[t])
        ok, low, high = _pullback_ok(x, p_, t)
        if ok and x.c.iat[t] < high:                          # 影片11/12：突破前的轉折點買，不追突破
            out.append((t, low))
    return out


# ---------------------------------------------------------------- 出場
def exit_path(x, e, stop, max_hold=MAX_HOLD, climax_rule="avg20", tide_exit=False):
    """從 e 日起逐日檢查，回傳 [(出場idx, 比例, 原因)]；出場在判斷日的下一日開盤成交。資料不夠時最後一筆為「持有中」。
    climax_rule：'avg20'＝量 ≥ 前 20 日均量 2.5 倍（預設）；'mv5'＝量 ≥ 前一日 5MV 的 160%（影片：波段攻擊量的 160%）。
    tide_exit：13MV（潮汐量）由升轉降的那天全部出場（影片：13MV 轉折＝絕項的項，八成是波段高點）。"""
    n = len(x)
    legs, left, climax, maxv = [], 1.0, None, x.v.iat[e]
    v13 = x.vma13.values if tide_exit else None
    for j in range(e, min(e + max_hold, n - 1)):
        c, v = x.c.iat[j], x.v.iat[j]
        if climax is not None and left > 0.5 and v < x.v.iat[climax] and x.h.iat[j] <= x.h.iat[climax]:
            legs.append((j + 1, 0.5, "極限大量後量縮不見高（出一半）"))      # 影片10：黃燈之後不見高
            left = 0.5
        big = v >= Q["climax"] * x.avgv.iat[j] if climax_rule == "avg20" else v >= 1.6 * x.vma5.iat[j - 1]
        if big and v >= maxv:
            climax = j                                                       # 自下而上區間的極限大量
        maxv = max(maxv, v)
        reason = None
        if c < stop:
            reason = "跌破回檔低點"
        elif tide_exit and j - 2 >= 0 and v13[j] < v13[j - 1] and v13[j - 1] >= v13[j - 2]:
            reason = "13MV轉折（潮汐量退）"
        elif c < x.ma21.iat[j]:
            reason = "跌破21MA"
        elif (not x.ma8_up.iat[j]) and (not x.ma21_up.iat[j]) and c < x.ma8.iat[j]:
            reason = "均線扣高反轉"
        if reason:
            legs.append((j + 1, left, reason))
            return legs
    legs.append((min(e + max_hold, n - 1), left, f"持有滿{max_hold}天"))
    return legs


# ---------------------------------------------------------------- 今日狀態（面板／排程用）
def today_state(x):
    """最後一根日 K 的狀態：
       signal  ＝ 今日出現凹洞量轉折訊號（收盤可買）
       setup   ＝ 攻擊後正在量縮整理，等凹洞量回升
       trend   ＝ 符合盤前條件，但還沒有攻擊／整理型態
       none    ＝ 不符盤前條件
    回傳 dict(state, stop, high, push_date, note)。"""
    t = len(x) - 1
    info = {"state": "none", "stop": np.nan, "high": np.nan, "push_date": None, "note": ""}
    if t < 30 or not bool(x.pre_ok.iat[t]):
        missing = [k for k, ok in (("流動性", x.liquid.iat[t]), ("站上21MA", x.c.iat[t] > x.ma21.iat[t]),
                                   ("均線扣低", bool(x.fast_up.iat[t] and x.slow_up.iat[t])), ("強於大盤", x.rs10.iat[t] > 0),
                                   ("量在峰", x.vol_peak.iat[t] >= 1)) if not ok]
        info["note"] = "缺：" + "、".join(missing) if missing else ""
        return info
    if any(i == t for i, _ in entries_v2(x)):
        stop = dict(entries_v2(x))[t]
        ar, lp = _last_push(x)
        _, _, high = _pullback_ok(x, int(lp.iloc[t]), t)
        info.update(state="signal", stop=stop, high=high, push_date=x.index[int(lp.iloc[t])])
        return info
    ar, lp = _last_push(x)
    # 是否處於「攻擊後回檔」：最近一次攻擊在 2~12 天內，且回檔量縮、守住攻擊日低點
    lp_now = pd.Series(np.where(x.push.values, ar, np.nan), index=x.index).ffill()
    p_ = lp_now.iat[t]
    if np.isfinite(p_) and 1 <= t - int(p_) <= Q["push_max"]:
        ok, low, high = _pullback_ok(x, int(p_), t + 1)
        if ok and x.c.iat[t] < high:
            gate = []
            if not bool(x.money_in.iat[t]):
                gate.append("均量線未轉強")
            if not (x.sec_rs.iat[t] > 0):
                gate.append("族群未強於大盤")
            if not (x.sec_rank.iat[t] <= Q["top_in_sector"]):
                gate.append("非族群前三強")
            info.update(state="setup", stop=low, high=high, push_date=x.index[int(p_)],
                        note=("量縮整理中，等量大於5天前" + ("；" + "、".join(gate) if gate else "")))
            return info
    info.update(state="trend", note="符合盤前條件，尚無攻擊後回檔型態")
    return info
