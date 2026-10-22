"""量、價、時間、角度：共用基礎函式（回測與盤中訊號共用，避免兩邊算法不一致）。

只放「算法」，不放進出場決策；決策在 xiao_daytrade.py。
所有函式只使用當根與過去資料，不偷看未來。
"""
import numpy as np
import pandas as pd


# ---------- 價格單位 ----------
def tick_size(price):
    """台股升降單位。"""
    p = float(price)
    if p < 10:
        return 0.01
    if p < 50:
        return 0.05
    if p < 100:
        return 0.1
    if p < 500:
        return 0.5
    if p < 1000:
        return 1.0
    return 5.0


# ---------- 扣抵／活動靶 ----------
def deduct_value(close, n):
    """下一根 n 期均線要「扣掉」的那一筆收盤價（扣抵值）。"""
    return close.shift(n - 1)


def ma_will_rise(close, n):
    """價格不變的前提下，下一根 n 期均線會不會上揚：目前價 > 扣抵值 = 扣低 → 均線上揚（活動靶向上）。
    回傳 +1 上揚、-1 下彎、0 持平。"""
    diff = close - deduct_value(close, n)
    return np.sign(diff)


# ---------- 角度 ----------


# ---------- 量 ----------
def slot_volume_ratio(bars, lookback_days=10):
    """15 分 K 的量 ÷ 過去 lookback_days 天「同一時段」的平均量。
    台股開盤與收盤量本來就大，跟同時段比較才看得出是不是真的攻擊量。只用過去日子，不含當天。"""
    df = bars[["Volume"]].copy()
    df["slot"] = df.index.strftime("%H:%M")
    df["day"] = df.index.date
    pivot = df.pivot_table(index="day", columns="slot", values="Volume", aggfunc="sum")
    hist = pivot.shift(1).rolling(lookback_days, min_periods=max(3, lookback_days // 2)).mean()
    ref = hist.stack().rename("ref")
    keyed = df.set_index(["day", "slot"], append=True)
    out = df["Volume"].values / keyed.join(ref, on=["day", "slot"])["ref"].values
    return pd.Series(out, index=bars.index).replace([np.inf, -np.inf], np.nan)


# ---------- 盤中均價線與相對強弱 ----------
def intraday_vwap(bars):
    """盤中均價線（看盤軟體的黃色線）：當日累積 典型價×量 ÷ 累積量。"""
    day = bars.index.date
    typical = (bars["High"] + bars["Low"] + bars["Close"]) / 3
    pv = (typical * bars["Volume"]).groupby(day).cumsum()
    vol = bars["Volume"].groupby(day).cumsum()
    return (pv / vol.replace(0, np.nan)).ffill()

