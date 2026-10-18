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
def exit_path(x, e, stop, max_hold=MAX_HOLD):
    """從 e 日起逐日檢查，回傳 [(出場idx, 比例, 原因)]；出場在判斷日的下一日開盤成交。資料不夠時最後一筆為「持有中」。"""
    n = len(x)
    legs, left, climax, maxv = [], 1.0, None, x.v.iat[e]
    for j in range(e, min(e + max_hold, n - 1)):
        c, v = x.c.iat[j], x.v.iat[j]
        if climax is not None and left > 0.5 and v < x.v.iat[climax] and x.h.iat[j] <= x.h.iat[climax]:
            legs.append((j + 1, 0.5, "極限大量後量縮不見高（出一半）"))      # 影片10：黃燈之後不見高
            left = 0.5
        if v >= Q["climax"] * x.avgv.iat[j] and v >= maxv:
            climax = j                                                       # 自下而上區間的極限大量
        maxv = max(maxv, v)
        reason = None
        if c < stop:
            reason = "跌破回檔低點"
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
