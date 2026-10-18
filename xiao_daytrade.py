"""蕭明道「量、價、時間、角度」當沖模組：盤前濾網 + 15 分 K 狀態機。

回測（research/backtest_daytrade.py）與盤中引擎共用同一個 DayMachine，確保兩邊規則一模一樣。
規則旁的註解對應影片原意：
  影片1〈量價時間角度獨家大公開〉、影片2〈千檔股票快速篩選族群→切入強勢股〉、影片3〈強勢股選股方法〉

每一根 K 棒是 dict（只含當根與過去資訊，不偷看未來）：
  time 'HH:MM'、open/high/low/close/volume、slot_ratio（同時段量比）、vwap（均價線）、
  chg（個股相對昨收 %）、idx_chg（大盤相對昨收 %）、tick（升降單位）
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

import xiao_rules as xr


@dataclass
class Params:
    # ---- 盤前濾網（日 K，只用昨天以前資料）----
    min_price: float = 100.0          # 影片1：喜歡 2、3 百塊以上、有量的高價股，進出快
    min_value: float = 3e8            # 20 日平均成交值（流動性）
    ma_fast: int = 8                  # 影片1/2：8MA、扣抵（活動靶）
    ma_slow: int = 21
    rs_days: int = 10                 # 相對大盤強弱
    vol_peak_ratio: float = 1.0       # 影片2：多頭「量在峰」＝上漲日均量 ≥ 下跌日均量
    use_sector: bool = False          # 影片2：先選強勢族群，再選族群內強勢股
    # ---- 盤中（15 分 K）----
    push_end: str = "10:30"           # 影片3：開盤後找開高出量的股票
    entry_end: str = "12:15"
    attack_ratio: float = 1.5         # 攻擊量：同時段量比
    pull_vol: float = 0.6             # 影片3：出大量後壓回「量縮」＝量 ≤ 攻擊棒的 60%
    require_gap: bool = True          # 影片3：開高（開盤 ≥ 昨收）且強於大盤
    # ---- 出場 ----
    big_ratio: float = 2.0            # 影片1：出大量
    big_shrink: bool = False          # 影片1「出大量、量縮、不見高」：下一根還要量縮才出場
    stop_pct: float = 2.0             # 結構停損的上限（%）
    exit_time: str = "13:00"          # 這根收盤（約 13:15）強制平倉，當沖不留倉
    use_vwap_exit: bool = True        # 影片1：最起碼要站在黃色均價線上方才能說它不弱


# ======================= 盤前濾網 =======================
def daily_context(daily, index_daily, p: Params, sector_rs=None):
    """以交易日為 index，回傳當天開盤前就能知道的條件（全部來自前一日以前）。"""
    c, v = daily["Close"], daily["Volume"]
    value20 = (c * v).rolling(20).mean()
    ma_s = c.rolling(p.ma_slow).mean()
    fast_up = xr.ma_will_rise(c, p.ma_fast) > 0          # 扣低：均線即將上揚
    slow_up = xr.ma_will_rise(c, p.ma_slow) > 0
    idx = index_daily["Close"].reindex(c.index).ffill()
    rs = (c / c.shift(p.rs_days) - idx / idx.shift(p.rs_days)) * 100
    up = c > c.shift(1)
    vol_peak = v.where(up).rolling(10, min_periods=3).mean() / v.where(~up).rolling(10, min_periods=3).mean()
    ctx = pd.DataFrame({"prev_close": c, "value20": value20, "rs": rs, "vol_peak": vol_peak,
                        "fast_up": fast_up, "slow_up": slow_up, "above_slow": c > ma_s})
    liquid = (c >= p.min_price) & (value20 >= p.min_value)
    ctx["long_ok"] = liquid & ctx.above_slow & fast_up & slow_up & (rs > 0) & (vol_peak >= p.vol_peak_ratio)
    ctx["short_ok"] = liquid & ~ctx.above_slow & ~fast_up & ~slow_up & (rs < 0) & (vol_peak <= 1 / p.vol_peak_ratio)
    if p.use_sector and sector_rs is not None:
        srs = sector_rs.reindex(c.index)
        ctx["long_ok"] &= srs > 0
        ctx["short_ok"] &= srs < 0
    return ctx.shift(1)   # 第 D 天只能用 D-1 收盤後的資訊


# ======================= 15 分 K 欄位 =======================
def prepare_bars(m15, prev_close_by_day, idx_chg):
    """15 分 K → 狀態機欄位。prev_close_by_day：以日期(Timestamp) 為 key 的昨收；idx_chg：大盤相對昨收 %（與 m15 同時間）。"""
    f = pd.DataFrame(index=m15.index)
    f["open"], f["high"], f["low"], f["close"], f["volume"] = m15.Open, m15.High, m15.Low, m15.Close, m15.Volume
    f["slot_ratio"] = xr.slot_volume_ratio(m15)
    f["vwap"] = xr.intraday_vwap(m15)
    f["prev_close"] = pd.Series(m15.index.date, index=m15.index).map(
        lambda d: prev_close_by_day.get(pd.Timestamp(d), np.nan))
    f["chg"] = (f.close / f.prev_close - 1) * 100
    f["idx_chg"] = idx_chg.reindex(m15.index)
    f["time"] = m15.index.strftime("%H:%M")
    f["tick"] = f.close.map(xr.tick_size)
    return f


def index_intraday_change(idx_m15, idx_daily):
    """大盤每根 15 分 K 相對昨收的漲跌 %。"""
    prev = idx_daily["Close"].shift(1)
    ref = pd.Series(idx_m15.index.date, index=idx_m15.index).map(lambda d: prev.get(pd.Timestamp(d), np.nan))
    return (idx_m15["Close"] / ref - 1) * 100


# ======================= 盤中狀態機 =======================
class DayMachine:
    """一檔股票、一天、一個方向。依序餵入每根「已收完」的 15 分 K：
       on_bar() 回傳 None、('enter', 參考價, 停損價) 或 ('exit', 價格, 原因)。
       enter 的成交在「下一根開盤」，由呼叫端（回測或下單引擎）處理。"""

    def __init__(self, side, prev_close, p: Params):
        self.side, self.prev_close, self.p = side, prev_close, p
        self.state = "wait_push"
        self.push = None          # 攻擊棒
        self.box_high = self.box_low = np.nan
        self.pulled = False
        self.prev_bar = None
        self.pos = None           # 持倉：dict(entry, stop, watch, big_high, big_low)
        self.traded = False
        self.events = []          # (時間, 事件)，給訊號面板顯示
        self.trigger = None       # 再攻訊號：dict(time, price, stop)

    # ---------- 進場前 ----------
    def _strong(self, bar):
        s = self.side
        return (s * (bar["close"] - bar["vwap"]) > 0) and (s * (bar["chg"] - bar["idx_chg"]) > 0)

    def _is_push(self, bar):
        s, p = self.side, self.p
        if bar["time"] > p.push_end or not np.isfinite(bar["slot_ratio"]):
            return False
        if bar["slot_ratio"] < p.attack_ratio or s * (bar["close"] - bar["open"]) <= 0:
            return False                                           # 量增價漲（空方：量增價跌）
        if p.require_gap and s * (bar["open"] - self.prev_close) < 0 and bar["time"] == "09:00":
            return False                                           # 影片3：開高（做空則開低）
        return self._strong(bar)                                   # 在均價線上方、強於大盤

    def _pre_entry(self, bar):
        s, p = self.side, self.p
        if self.state == "wait_push":
            if self._is_push(bar):
                self.state, self.push, self.pulled = "wait_pull", bar, False
                self.box_high, self.box_low = bar["high"], bar["low"]
                self.events.append((bar["time"], "攻擊量出現"))
            return None
        # 已有攻擊棒：更新整理區間
        self.box_high, self.box_low = max(self.box_high, bar["high"]), min(self.box_low, bar["low"])
        # 背影殺手：跌破攻擊棒低點或均價線 → 假強，重新等下一次攻擊
        broke = (s > 0 and (bar["close"] < self.push["low"] or bar["close"] < bar["vwap"])) or \
                (s < 0 and (bar["close"] > self.push["high"] or bar["close"] > bar["vwap"]))
        if broke:
            self.state, self.push = "wait_push", None
            self.events.append((bar["time"], "假強（背影殺手）"))
            return None
        if self.state == "wait_pull":
            if bar["volume"] <= p.pull_vol * self.push["volume"]:   # 影片3：出大量後壓回量縮
                self.state, self.pulled = "armed", True
                self.events.append((bar["time"], "量縮壓回"))
            return None
        # armed：整理後再攻（誰先發動誰贏）
        prev = self.prev_bar
        rng = bar["high"] - bar["low"]
        level = self.box_high_before if s > 0 else self.box_low_before
        trigger = (bar["time"] <= p.entry_end and rng > 0
                   and s * (bar["close"] - level) > 0                                  # 突破整理區
                   and bar["volume"] > prev["volume"]                                   # 量增
                   and (bar["close"] - bar["low"] if s > 0 else bar["high"] - bar["close"]) >= rng * 0.5
                   and self._strong(bar))
        if trigger:
            stop_struct = self.box_low - bar["tick"] if s > 0 else self.box_high + bar["tick"]
            cap = bar["close"] * (1 - s * p.stop_pct / 100)
            stop = max(stop_struct, cap) if s > 0 else min(stop_struct, cap)
            self.state, self.traded = "entering", True
            self.trigger = {"time": bar["time"], "price": bar["close"], "stop": stop}
            self.events.append((bar["time"], "再攻訊號"))
            return ("enter", bar["close"], stop)
        return None

    # ---------- 持倉中 ----------
    def _exit(self, bar):
        s, p, pos = self.side, self.p, self.pos
        if s > 0 and bar["low"] <= pos["stop"]:
            return ("exit", min(pos["stop"], bar["open"]), "停損")
        if s < 0 and bar["high"] >= pos["stop"]:
            return ("exit", max(pos["stop"], bar["open"]), "停損")
        if pos["watch"]:                                            # 影片1：出大量，下一根不見高就出
            shrink_ok = (not p.big_shrink) or bar["volume"] < pos["big_vol"]
            if shrink_ok and ((s > 0 and bar["high"] <= pos["big_high"]) or (s < 0 and bar["low"] >= pos["big_low"])):
                return ("exit", bar["close"], "出大量不見高" if s > 0 else "出大量不見低")
            pos["watch"] = False
        if p.use_vwap_exit and s * (bar["close"] - bar["vwap"]) < 0:
            return ("exit", bar["close"], "跌破均價線" if s > 0 else "站回均價線")
        if bar["time"] >= p.exit_time:
            return ("exit", bar["close"], "收盤前平倉")
        if np.isfinite(bar["slot_ratio"]) and bar["slot_ratio"] >= p.big_ratio:
            pos.update(watch=True, big_high=bar["high"], big_low=bar["low"], big_vol=bar["volume"])
        return None

    # ---------- 對外介面 ----------
    def filled(self, price, stop):
        self.pos = {"entry": price, "stop": stop, "watch": False, "big_high": np.nan, "big_low": np.nan, "big_vol": np.nan}
        self.state = "in_pos"

    def on_bar(self, bar):
        self.box_high_before, self.box_low_before = self.box_high, self.box_low
        if self.state == "in_pos":
            out = self._exit(bar)
            if out:
                self.state, self.pos = "done", None
                self.events.append((bar["time"], "出場：" + out[2]))
        elif self.state in ("done", "entering") or self.traded:
            out = None
        else:
            out = self._pre_entry(bar)
        self.prev_bar = bar
        return out
