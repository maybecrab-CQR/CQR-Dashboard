"""CQR｜全市場動能決策臺 — v19 清爽介面、MA21與個股盤中更新版
執行：python -m streamlit run app.py
安裝：pip install streamlit pandas yfinance plotly streamlit-aggrid beautifulsoup4 requests tzdata
策略：全市場板塊 5／10／20 日 RS（含正負值）→ 成分股相對強弱 → 官方股期標記。
當日漲幅採今日參考價；盤中報價須通過時間戳驗證。每5分鐘刷新；法人與資券為獨立日期的盤後資料。
"""
from html import escape
from bs4 import BeautifulSoup
import math
import json
import re
import requests
import tempfile
import time as clock
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import huanan_panel
import xiao_panel
import industry_chain
import hmac
import os

# 雲端模式：非 Windows 主機（Streamlit Cloud 等）沒有華南元件與憑證，自動關閉登入／下單／帳務；CQR_CLOUD=1/0 可強制開關。
IS_CLOUD=os.environ.get('CQR_CLOUD')=='1' or (os.environ.get('CQR_CLOUD')!='0' and os.name!='nt')
MODULES=["主面板","量價訊號"]  # 頂部策略模組；新增模組時加在這裡，並在 dashboard() 補上該模組的左右欄內容
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from plotly.offline import get_plotlyjs
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

sector_stocks = {
    "1. 半導體與晶圓代工": ["2330.TW", "2454.TW", "2303.TW", "3711.TW", "2379.TW", "3034.TW", "6488.TW", "3105.TW", "5347.TW", "8299.TW", "6415.TW", "3661.TW"],
    "2. AI伺服器與電腦": ["2382.TW", "3231.TW", "2376.TW", "6669.TW", "2356.TW", "2324.TW", "2353.TW", "3706.TW"],
    "3. 電子零組件與PCB": ["2308.TW", "2368.TW", "2383.TW", "3037.TW", "8046.TW", "3017.TW", "3324.TW", "6239.TW", "3044.TW"],
    "4. 光電與面板顯示": ["2409.TW", "3481.TW", "6116.TW", "3008.TW", "3406.TW", "2340.TW", "2448.TW", "6202.TW"],
    "5. 網通與通訊設備": ["2345.TW", "3596.TW", "5388.TW", "3380.TW", "6285.TW", "2419.TW"],
    "6. 智慧車與車用電子": ["2360.TW", "1536.TW", "6279.TW", "3665.TW", "2201.TW", "2207.TW"],
    "7. 重電綠能與電機": ["1519.TW", "1513.TW", "1503.TW", "1514.TW", "1504.TW", "1605.TW", "3708.TW", "6806.TW"],
    "8. 金融保險與證券": ["2881.TW", "2882.TW", "2891.TW", "2886.TW", "2884.TW", "2885.TW", "2892.TW", "2880.TW", "2883.TW", "2887.TW", "2890.TW"],
    "9. 航運與海運物流": ["2603.TW", "2609.TW", "2615.TW", "2618.TW", "2610.TW", "2606.TW", "2637.TW", "2611.TW"],
    "10. 鋼鐵與基本金屬": ["2002.TW", "2014.TW", "2027.TW", "2006.TW", "2031.TW"],
    "11. 塑化與化學工業": ["1301.TW", "1303.TW", "1326.TW", "1304.TW", "1308.TW", "1711.TW", "4739.TW"],
    "12. 生技醫療與照護": ["1795.TW", "6446.TW", "4743.TW", "1701.TW", "1762.TW"],
    "13. 營建建材與資產": ["2542.TW", "2504.TW", "2520.TW", "2548.TW", "5522.TW"],
    "14. 觀光餐飲與休閒": ["2707.TW", "2727.TW", "2731.TW", "2723.TW"],
    "15. 紡織水泥與傳產": ["1101.TW", "1102.TW", "1402.TW", "1476.TW", "1477.TW", "9904.TW"]
}
stock_names = {
    "2330": "台積電", "2454": "聯發科", "2303": "聯電", "3711": "日月光", "2379": "瑞昱", "3034": "聯詠", "6488": "環球晶", "3105": "穩懋", "5347": "世界", "8299": "群聯", "6415": "矽力", "3661": "世芯",
    "2382": "廣達", "3231": "緯創", "2376": "技嘉", "6669": "緯穎", "2356": "英業達", "2324": "仁寶", "2353": "宏碁", "3706": "神達",
    "2308": "台達電", "2368": "金像電", "2383": "台光電", "3037": "欣興", "8046": "南電", "3017": "奇鋐", "3324": "雙鴻", "6239": "力成", "3044": "健鼎",
    "2409": "友達", "3481": "群創", "6116": "彩晶", "3008": "大立光", "3406": "玉晶光", "2340": "台亞", "2448": "晶電", "6202": "盛群",
    "2345": "智邦", "3596": "智易", "5388": "中磊", "3380": "明泰", "6285": "啟碁", "2419": "仲琦",
    "2360": "致茂", "1536": "和大", "6279": "胡連", "3665": "貿聯", "2201": "裕隆", "2207": "和泰車",
    "1519": "華城", "1513": "中興電", "1503": "士電", "1514": "亞力", "1504": "東元", "1605": "華新", "3708": "上緯", "6806": "森崴",
    "2881": "富邦金", "2882": "國泰金", "2891": "中信金", "2886": "兆豐金", "2884": "玉山金", "2885": "元大金", "2892": "第一金", "2880": "華南金", "2883": "開發金", "2887": "台新金", "2890": "永豐金",
    "2603": "長榮", "2609": "陽明", "2615": "萬海", "2618": "長榮航", "2610": "華航", "2606": "裕民", "2637": "慧洋", "2611": "志信",
    "2002": "中鋼", "2014": "中鴻", "2027": "大成鋼", "2006": "東和", "2031": "新光鋼",
    "1301": "台塑", "1303": "南亞", "1326": "台化", "1304": "台聚", "1308": "亞聚", "1711": "永光", "4739": "康普",
    "1795": "美時", "6446": "藥華藥", "4743": "合一", "1701": "中化", "1762": "中化生",
    "2542": "興富發", "2504": "國產", "2520": "冠德", "2548": "華固", "5522": "遠雄",
    "2707": "晶華", "2727": "王品", "2731": "雄獅", "2723": "美食",
    "1101": "台泥", "1102": "亞泥", "1402": "遠東新", "1476": "儒鴻", "1477": "聚陽", "9904": "寶成"
}


# 名称移除序號，對應的基準與股票名單保持一致。
sector_stocks = {re.sub(r"^\d+\.\s*", "", k): v for k,v in sector_stocks.items()}

CSS = """
<style>
:root {color-scheme:dark;}
.stApp {background:#090d13;color:#e7ebf2;}
header[data-testid="stHeader"] {background:#090d13;}
.block-container {padding:1.4rem 2.1rem 1.6rem;max-width:1920px;}
[data-testid="stToolbar"] {right:1rem;}
h1,h2,h3 {font-family:"Segoe UI","Microsoft JhengHei",sans-serif;color:#eef1f6;}
[data-testid="stMarkdownContainer"] p {color:#abb5c5;}
.brand {display:flex;align-items:center;justify-content:space-between;padding:10px 0 22px;border-bottom:1px solid #28303b;margin-bottom:20px;gap:16px;}
.brand-left {display:flex;gap:15px;align-items:center;}
.monogram {width:44px;height:44px;border:1px solid #a78e58;border-radius:12px;display:grid;place-items:center;color:#deca94;font-family:Georgia,serif;font-size:25px;background:linear-gradient(145deg,#302a1d,#101720);}
.eyebrow {font-size:10px;letter-spacing:3px;color:#bda979;margin-bottom:4px;}
.brand-title {font-size:24px;font-weight:650;letter-spacing:1px;color:#edf1f8;}
.brand-meta {text-align:right;font-size:11px;color:#8794a8;line-height:1.9;}
.pill {display:inline-block;border:1px solid #384438;border-radius:20px;padding:3px 10px;color:#bfc9ad;font-size:11px;letter-spacing:.8px;}
.metric-row {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0 0 23px;}
.metric {background:linear-gradient(115deg,#141c27,#0f151f);border:1px solid #263140;border-radius:12px;padding:15px 18px;min-height:102px;}
.metric-label {font-size:11px;color:#929fb1;letter-spacing:.8px;}
.metric-value {font-size:23px;line-height:1.65;color:#e8edf6;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.metric-note {font-size:11px;color:#8794a8;}
.up {color:#f17c7e!important;} .down {color:#55c8a4!important;} .gold {color:#d7bf84!important;}
.section {display:flex;align-items:baseline;justify-content:space-between;margin:3px 0 10px;gap:8px;}
.section-title {font-size:15px;font-weight:600;color:#e7ecf4;}
.section-number {font-size:11px;color:#c8b078;margin-right:8px;font-family:monospace;}
.section-note {font-size:10px;color:#8490a2;}
.stock-head {display:flex;align-items:center;gap:12px;margin:3px 0 7px;}
.stock-head h2 {margin:0;padding:0;font-size:27px;line-height:1.5;}
.stock-code {font-family:monospace;font-size:14px;color:#cbb57e;border:1px solid #3b3527;border-radius:6px;padding:4px 8px;}
.price-line {display:flex;align-items:baseline;gap:12px;margin-bottom:10px;flex-wrap:wrap;}
.last-price {font-size:34px;letter-spacing:-1px;color:#edf1f7;font-variant-numeric:tabular-nums;font-weight:600;}
.price-details {font-size:12px;color:#9ba8ba;}
.footer {border-top:1px solid #26303d;margin-top:18px;padding-top:12px;font-size:11px;color:#7e8b9d;display:flex;justify-content:space-between;gap:16px;}
[data-testid="stSelectbox"] label,[data-testid="stCheckbox"] label {color:#a5b1c1;}
[data-baseweb="select"]>div {background:#111924!important;border-color:#303b4c!important;color:#e4eaf3!important;border-radius:8px;}
[data-testid="stButton"] button {background:#17202b;border:1px solid #3b4656;color:#dbc58e;border-radius:8px;}
[data-testid="stButton"] button:hover {border-color:#bba167;color:#f0deb0;}
[data-testid="stCaptionContainer"] {color:#8490a2;}
@media(max-width:850px){.block-container{padding:1rem}.metric-row{grid-template-columns:repeat(2,1fr)}.brand-meta{display:none}.brand-title{font-size:19px}.metric-value{font-size:20px}}
[data-testid="stCaptionContainer"] p {font-size:14px!important;color:#aebbd0!important;}
[data-testid="stHeader"]{display:none}.brand{padding:8px 0 14px;margin-bottom:12px}.metric{min-height:90px;padding:12px 16px}.metric-row{margin-bottom:16px}.brand-title{font-size:29px}.eyebrow{font-size:12px}.section-title{font-size:19px}.section-note,.section-number{font-size:13px}.metric-label,.metric-note{font-size:14px}.metric-value{font-size:28px}.price-details{font-size:15px}.last-price{font-size:44px}.footer{font-size:13px}.stock-head h2{font-size:31px}.block-container{padding-top:1.3rem}.price-line{margin-bottom:4px}
</style>
"""

def taipei_now():
    return datetime.now(ZoneInfo("Asia/Taipei"))


def roc_date(value):
    text=re.sub(r"[^0-9]", "", str(value))
    if len(text)==7:
        text=str(int(text[:3])+1911)+text[3:]
    return pd.Timestamp(datetime.strptime(text,"%Y%m%d"),tz="Asia/Taipei")


def number(value):
    return float(str(value).replace(",", ""))


def number_or_nan(value):
    try:return number(value)
    except (ValueError,TypeError):return float("nan")


def get_json(url, params=None):
    error=None
    for attempt in range(2):
        try:
            response=requests.get(url,params=params,timeout=15,headers={"User-Agent":"Mozilla/5.0"})
            response.raise_for_status()
            return response.json()
        except (requests.RequestException,ValueError) as exc:error=exc
    raise ValueError(f"資料來源讀取失敗：{error}")


@st.cache_data(ttl=86400, show_spinner=False)
def exchange_holidays(year):
    data=get_json("https://www.twse.com.tw/holidaySchedule/holidaySchedule",
                  {"response":"json","queryYear":year-1911})
    if str(data.get("stat","")).lower()!="ok" or not data.get("data"):
        raise ValueError("交易日曆取得失敗")
    holidays=set()
    for row in data["data"]:
        # 表中亦有開始交易／最後交易日，不能當成休市。
        if "開始交易" in row[1] or "最後交易" in row[1]:
            continue
        holidays.add(pd.Timestamp(row[0]).date())
    return holidays


def expected_session(now=None):
    now=now or taipei_now()
    try:
        holidays=exchange_holidays(now.year)
        if now.month==1 and now.day<=7:holidays|=exchange_holidays(now.year-1)
    except Exception:
        return None
    day=now.date() if now.time()>=time(13,30) else now.date()-timedelta(days=1)
    while day.weekday()>=5 or day in holidays:
        day-=timedelta(days=1)
    return day


@st.cache_data(ttl=60, show_spinner=False)
def official_month(code, month):
    report="FMTQIK" if code=="^TWII" else "STOCK_DAY"
    params={"response":"json","date":month}
    if code!="^TWII":params["stockNo"]=code
    try:data=get_json(f"https://www.twse.com.tw/exchangeReport/{report}",params)
    except Exception:
        if code=="^TWII":raise
        return otc_month(code,month)
    if str(data.get("stat","")).upper()!="OK":
        if code!="^TWII":return otc_month(code,month)
        raise ValueError(f"證交所 {code} {month} 無可用日資料")
    fields=data.get("fields",[]);rows=[]
    for row in data.get("data",[]):
        r=dict(zip(fields,row))
        try:
            date=roc_date(r["日期"])
            if code=="^TWII":
                close=number(r["發行量加權股價指數"])
                rows.append({"Date":date,"Close":close})
            else:
                rows.append({"Date":date,"Open":number(r["開盤價"]),"High":number(r["最高價"]),
                             "Low":number(r["最低價"]),"Close":number(r["收盤價"]),"Volume":number(r["成交股數"])})
        except (KeyError,ValueError,TypeError):
            continue
    if not rows:raise ValueError("證交所回傳資料無有效價格")
    frame=pd.DataFrame(rows).set_index("Date").sort_index()
    return frame.loc[frame.index.date<=taipei_now().date()]


def parse_otc_month(data):
    rows=[]
    for table in data.get("tables",[]):
        for values in table.get("data",[]):
            r=dict(zip(table.get("fields",[]),values))
            try:
                rows.append({"Date":roc_date(r["日 期"]),"Open":number(r["開盤"]),
                             "High":number(r["最高"]),"Low":number(r["最低"]),
                             "Close":number(r["收盤"]),"Volume":number(r["成交張數"])*1000})
            except (KeyError,ValueError,TypeError):continue
    if not rows:raise ValueError("櫃買中心無可用日資料")
    frame=pd.DataFrame(rows).set_index("Date").sort_index()
    return frame.loc[frame.index.date<=taipei_now().date()]


@st.cache_data(ttl=60,show_spinner=False)
def otc_month(code,month):
    data=get_json("https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock",
                  {"code":code,"date":f"{month[:4]}/{month[4:6]}/01","response":"json"})
    return parse_otc_month(data)


def normalize(frame):
    if frame.empty:return frame
    frame=frame.copy().sort_index()
    if frame.index.tz is None:frame.index=frame.index.tz_localize("Asia/Taipei")
    else:frame.index=frame.index.tz_convert("Asia/Taipei")
    return frame.loc[~frame.index.duplicated(keep="last")].dropna(subset=["Close"])


def yahoo_history(ticker,period,interval="1d",adjusted=True):
    # 同時查長區間與近一個月，解決部分 Yahoo 長區間回應落後。
    obj=yf.Ticker(ticker);parts=[];errors=[]
    requests_to_make=({"period":"5d"},) if interval=="1m" else ({"period":period},{"start":(taipei_now()-timedelta(days=30)).strftime("%Y-%m-%d"),"end":(taipei_now()+timedelta(days=1)).strftime("%Y-%m-%d")})
    for kwargs in requests_to_make:
        try:
            f=normalize(obj.history(interval=interval,auto_adjust=adjusted,timeout=15,**kwargs))
            if not f.empty:parts.append(f)
        except Exception as exc:errors.append(str(exc))
    if not parts:raise ValueError("Yahoo 未回傳有效資料；"+"; ".join(errors))
    return normalize(pd.concat(parts))


@st.cache_data(ttl=60, show_spinner=False)
def history(ticker, period, interval="1d"):
    try:
        frame=yahoo_history(ticker,period,interval,True)  # RS 沿用原本還原價格
    except Exception:
        if ticker!="^TWII":raise
        frame=pd.DataFrame(columns=["Close"],index=pd.DatetimeIndex([],tz="Asia/Taipei"))
    if ticker=="^TWII" and interval=="1d":
        try:
            patch=official_month("^TWII",taipei_now().strftime("%Y%m01"))
            for idx,row in patch.iterrows():frame.loc[idx,"Close"]=row.Close
            frame=normalize(frame)
        except Exception:
            pass
    if frame.empty:raise ValueError("加權指數資料無法取得")
    return frame,taipei_now().strftime("%Y/%m/%d %H:%M:%S")


def load_history(ticker,period,interval="1d"):
    return history(ticker,period,interval)


def merge_daily(base,patch):
    # 全部使用未還原 OHLC，絕不把交易所原始價接到還原價上。
    columns=["Open","High","Low","Close","Volume"]
    if base.empty:return normalize(patch[columns])
    return normalize(pd.concat([base[columns],patch[columns]]))


def chart_yahoo(ticker,period,interval):
    errors=[]
    for symbol in [ticker]+([ticker.removesuffix(".TW")+".TWO"] if ticker.endswith(".TW") else []):
        try:
            frame=yahoo_history(symbol,period,interval,False)
            if not frame.empty:return frame
        except Exception as exc:errors.append(str(exc))
    raise ValueError("; ".join(errors) or "無行情")


@st.cache_data(ttl=300, show_spinner=False)
def chart_history(ticker, period, interval):
    if interval.endswith("m"):
        frame=chart_yahoo(ticker,period,interval)
        frame.attrs.update(source="Yahoo 分鐘資料",last_trade=str(frame.index[-1].date()),notes=[])
        return frame,taipei_now().strftime("%Y/%m/%d %H:%M:%S")
    notes=[]
    try:frame=chart_yahoo(ticker,"1y","1d")
    except Exception as exc:
        frame=pd.DataFrame();notes.append(str(exc))
    had_yahoo=not frame.empty
    now=taipei_now();official_ok=False
    # 最近兩個月全部補齊，避免只補最後一天而漏掉中間交易日。
    for month in ((pd.Timestamp(now)-pd.DateOffset(months=1)).strftime("%Y%m01"),now.strftime("%Y%m01")):
        try:
            patch=month_frame(ticker.split(".")[0],month)
            frame=merge_daily(frame,patch);official_ok=True
        except Exception as exc:notes.append(str(exc))
    if len(frame)<65:
        for offset in (2,3,4):
            try:
                patch=month_frame(ticker.split(".")[0],(pd.Timestamp(now)-pd.DateOffset(months=offset)).strftime("%Y%m01"))
                frame=merge_daily(frame,patch)
            except Exception as exc:notes.append(str(exc))
            if len(frame)>=65:break
    if frame.empty:raise ValueError("Yahoo 與證交所皆無資料："+"; ".join(notes))
    frame=frame.dropna(subset=["Open","High","Low","Close"]).sort_index()
    last_trade=frame.index[-1].date()
    if interval in ("1wk","1mo"):
        rule="W-MON" if interval=="1wk" else "MS"
        frame=frame.resample(rule,label="left",closed="left").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna(subset=["Close"])
    frame.attrs.update(source=("Yahoo 歷史＋交易所日資料" if had_yahoo else "交易所日資料（Yahoo 暫不可用）") if official_ok else "Yahoo（日資料未經證交所補齊）",
                       last_trade=str(last_trade),notes=notes)
    return frame,taipei_now().strftime("%Y/%m/%d %H:%M:%S")


def fetch_chart(ticker, period, interval):
    try:
        return chart_history(ticker, period, interval)
    except Exception as exc:
        return pd.DataFrame(), f"{type(exc).__name__}: {exc}"


def fetch(ticker, period, interval="1d"):
    try:
        return history(ticker, period, interval)
    except Exception:
        return pd.DataFrame(), "讀取失敗"


def rs_momentum(numerator, denominator, periods=10):
    # 日期相同（絕大多數情況）直接用 numpy，比 pd.concat 對齊快約 20 倍；日期不同才對齊。
    if numerator.index.equals(denominator.index):
        a=numerator.to_numpy(dtype=float);b=denominator.to_numpy(dtype=float)
        ok=~(np.isnan(a)|np.isnan(b));a=a[ok];b=b[ok]
    else:
        pair=pd.concat([numerator,denominator],axis=1).dropna()
        a=pair.iloc[:,0].to_numpy(dtype=float);b=pair.iloc[:,1].to_numpy(dtype=float)
    if len(a)<periods+1 or (a<=0).any() or (b<=0).any():return None
    ratio=a/b
    return float(ratio[-1]/ratio[-periods-1]-1)


@st.cache_data(ttl=86400, show_spinner=False)
def archived_month(code, month):
    return official_month(code, month)


def month_frame(code, month):
    if month==taipei_now().strftime("%Y%m01"):
        return official_month(code,month)
    return archived_month(code,month)


@st.cache_data(ttl=60, show_spinner=False)
def ranking_history(ticker, asof=None):
    # 一致的原始成交價基準：不能將還原價與證交所原始價拼接。
    code=ticker if ticker=="^TWII" else ticker.split(".")[0]
    now=taipei_now();parts=[];errors=[]
    for month in ((pd.Timestamp(now)-pd.DateOffset(months=1)).strftime("%Y%m01"),now.strftime("%Y%m01")):
        try:parts.append(month_frame(code,month))
        except Exception as exc:errors.append(str(exc))
    frame=normalize(pd.concat(parts)) if parts else pd.DataFrame()
    required=asof or expected_session()
    if required is None:
        raise ValueError("無法確認應有交易日，暫不產生最新排名")
    if frame.empty or frame.index[-1].date()<required or len(frame)<11:
        # 上櫃或交易所未提供的標的，僅接受同為未還原且日期足夠的新資料。
        for symbol in [ticker]+([code+".TWO"] if ticker.endswith(".TW") else []):
            try:
                candidate=yahoo_history(symbol,"3mo","1d",False)
                if candidate.index[-1].date()>=required and len(candidate)>=11:
                    frame=candidate;break
            except Exception as exc:errors.append(str(exc))
    if frame.empty:raise ValueError("; ".join(errors) or "無日資料")
    frame=frame.loc[frame.index.date<=required]
    if frame.empty:raise ValueError(f"{required} 以前無有效日資料")
    return frame


def safe_rank_frame(ticker,asof=None):
    try:return ranking_history(ticker,asof),None
    except Exception as exc:return pd.DataFrame(),str(exc)


def parse_futures_html(html):
    soup=BeautifulSoup(html,"html.parser");result={};seen=0
    for table in soup.select("table"):
        if "是否為" not in table.get_text() or "股票期貨" not in table.get_text():continue
        for tr in table.select("tr"):
            cells=[c.get_text(" ",strip=True) for c in tr.find_all(["td","th"],recursive=False)]
            if len(cells)<12 or not re.fullmatch(r"\d{4,6}",cells[2]):continue
            seen+=1
            if "●" in cells[4]:
                result.setdefault(cells[2],[]).append(cells[0])
    if seen<50 or len(result)<50:raise ValueError("官方股期名單格式或筆數異常")
    return {code:" / ".join(dict.fromkeys(contracts)) for code,contracts in result.items()}


def parse_futures_json(rows):
    result={}
    for row in rows:
        code=str(row.get("StockCode",""));contract=str(row.get("Contract",""))
        if re.fullmatch(r"\d{4,6}",code) and re.fullmatch(r"[A-Z0-9]+",contract):
            result.setdefault(code,[]).append(contract)
    if len(result)<50:raise ValueError("官方股期 API 名單格式或筆數異常")
    return {code:" / ".join(dict.fromkeys(values)) for code,values in result.items()}


@st.cache_data(ttl=3600,show_spinner=False)
def futures_catalog():
    try:catalog=parse_futures_json(get_json("https://openapi.taifex.com.tw/v1/SSFLists"))
    except Exception:
        response=requests.get("https://www.taifex.com.tw/cht/2/stockLists",timeout=20,headers={"User-Agent":"Mozilla/5.0"})
        response.raise_for_status();response.encoding="utf-8"
        catalog=parse_futures_html(response.text)
    return catalog,taipei_now().strftime("%Y/%m/%d %H:%M")


def load_futures():
    try:
        catalog,stamp=futures_catalog()
        return catalog,f"期交所名單核對 {stamp}"
    except Exception as exc:return None,f"股期名單待核對：{exc}"


def equal_weight_basket(tickers,frames,calendar):
    # Fixed membership throughout the selected window; never fill missing closes.
    valid={};missing=[]
    for ticker in tickers:
        frame=frames.get(ticker,pd.DataFrame())
        close=frame.Close.reindex(calendar) if not frame.empty else pd.Series(index=calendar,dtype=float)
        if close.isna().any() or (close<=0).any():missing.append(ticker)
        else:valid[ticker]=close
    minimum=max(min(3,len(tickers)),math.ceil(len(tickers)*0.8))
    if len(valid)<minimum:return pd.DataFrame(),valid,missing
    prices=pd.DataFrame(valid)
    returns=prices.pct_change(fill_method=None).iloc[1:].mean(axis=1)
    index=pd.Series(100.0,index=calendar)
    index.iloc[1:]=100*(1+returns).cumprod()
    return pd.DataFrame({"Close":index}),valid,missing


@st.cache_data(ttl=300,show_spinner=False)
def screening_snapshot(periods=10):
    required=expected_session()
    market,error=safe_rank_frame("^TWII")
    empty=pd.DataFrame(columns=["趨勢","族群板塊","動能(%)","漲幅(%)","覆蓋","資料日"])
    stamp=taipei_now().strftime("%Y/%m/%d %H:%M:%S")
    if market.empty or required is None or len(market)<periods+1:
        return empty,market,stamp,[f"加權指數資料未齊：{error or '交易日或樣本不足'}"],{}
    # Accept only the latest published benchmark, at most one completed session behind.
    prior=expected_session(datetime.combine(required,time(12),tzinfo=ZoneInfo("Asia/Taipei")))
    asof=market.index[-1].date()
    if prior is None or asof<prior:
        return empty,market,stamp,["大盤資料落後超過一個交易日，暫停篩選"],{}
    calendar=market.index[-periods-1:];benchmark=market.Close.reindex(calendar)
    tickers=sorted({t for members in sector_stocks.values() for t in members})
    with ThreadPoolExecutor(max_workers=4) as pool:
        fetched=list(pool.map(lambda ticker:safe_rank_frame(ticker,asof),tickers))
    frames={t:f for t,(f,err) in zip(tickers,fetched)}
    rows=[];missing=[];groups={}
    for name,members in sector_stocks.items():
        basket,valid,excluded=equal_weight_basket(members,frames,calendar)
        missing.extend(f"{name}：{t}" for t in excluded)
        if basket.empty:continue
        value=rs_momentum(basket.Close,benchmark,periods)
        if value is None:continue
        groups[name]={"basket":basket,"members":valid,"missing":excluded,"rs":value}
        rows.append({"趨勢":"強勢" if value>0 else "弱勢","族群板塊":name,
                     "動能(%)":value*100,"漲幅(%)":(basket.Close.iloc[-1]/basket.Close.iloc[-2]-1)*100,
                     "覆蓋":f"{len(valid)}/{len(members)}","資料日":str(asof)})
    table=pd.DataFrame(rows,columns=empty.columns)
    return table.sort_values("動能(%)",ascending=False).reset_index(drop=True),market,stamp,missing,groups


def leader_table(group,catalog,periods=10,rising_only=False,futures_only=False,rs_filter="全部"):
    columns=["代號","名稱","屬性","動能(%)","漲幅(%)","相對狀態","股期商品","資料日"]
    if not group:return pd.DataFrame(columns=columns)
    # 同一次掃描結果、同樣條件只算一次（換頁籤時不用重算族群內 RS）
    memo=st.session_state.setdefault("_leader_memo",{})
    key=(id(group),periods,rising_only,futures_only,rs_filter,catalog is None)
    if key in memo and memo[key][0] is group:return memo[key][1].copy()
    table=_leader_table(group,catalog,periods,rising_only,futures_only,rs_filter,columns)
    if len(memo)>400:memo.clear()
    memo[key]=(group,table)
    return table.copy()


def _leader_table(group,catalog,periods,rising_only,futures_only,rs_filter,columns):
    rows=[]
    for ticker,close in group["members"].items():
        value=rs_momentum(close,group["basket"].Close,periods)
        change=group.get("day_changes",{}).get(ticker,float(close.iloc[-1]/close.iloc[-2]-1)*100)
        code=ticker.split(".")[0]
        available=catalog is not None and code in catalog
        if value is None or (rising_only and change<=0) or (futures_only and not available):continue
        if rs_filter=="只看 RS > 0" and value<=1e-12:continue
        if rs_filter=="只看 RS ≤ 0" and value>1e-12:continue
        state="相對領先" if value>1e-12 else "相對落後" if value< -1e-12 else "與族群同步"
        rows.append({"代號":code,"名稱":stock_names.get(code,""),"屬性":"股期" if available else "待核對" if catalog is None else "—",
                     "動能(%)":value*100,"漲幅(%)":change,"相對狀態":state,"股期商品":catalog.get(code,"") if catalog is not None else "待核對",
                     "資料日":str(close.index[-1].date())})
    return pd.DataFrame(rows,columns=columns).sort_values("動能(%)",ascending=False).reset_index(drop=True)


def strongest_picks(sectors,groups,catalog,quotes,periods=10,n_sec=3,n=3,min_price=50,min_value=2e8):
    """蕭氏選股：先取相對大盤最強的前三個板塊（RS>0），再在每個板塊內取強於族群（RS>0）、
    可交易（股價 ≥ 50、今日成交值 ≥ 2 億）的前三強股票，以及其中有股票期貨的前三強。"""
    columns=["板塊","類別","代號","名稱","屬性","動能(%)","漲幅(%)","股期商品","相對狀態","資料日","_sector","_ticker"]
    top=sectors[sectors["動能(%)"]>0].head(n_sec) if not sectors.empty else sectors
    rows=[]
    for rank,sname in enumerate(top["族群板塊"],1):
        table=leader_table(groups.get(sname),catalog,periods,rs_filter="只看 RS > 0")
        if table.empty:continue
        tickers={t.split(".")[0]:t for t in groups[sname]["members"]}
        table=table.assign(_sector=sname,_ticker=table["代號"].map(tickers))
        def tradable(code):
            q=quotes.get(code) or {};price=q.get("price") or 0
            return price>=min_price and price*(q.get("Volume") or 0)>=min_value
        table=table[table["代號"].map(tradable)]
        stock_top=set(table.head(n)["代號"]);fut_top=set(table[table["屬性"]=="股期"].head(n)["代號"])
        for r in table[table["代號"].isin(stock_top|fut_top)].to_dict("records"):   # 同時入選者只列一次
            kind="股＋期" if r["代號"] in stock_top and r["代號"] in fut_top else "股票" if r["代號"] in stock_top else "股期"
            rows.append({"板塊":f"{rank} {sname}","類別":kind,**r})
    return top,pd.DataFrame(rows,columns=columns)


# 全市場：官方普通股名單；即時來源與收盤來源嚴格分開。
INDUSTRIES={"01":"水泥工業","02":"食品工業","03":"塑膠工業","04":"紡織纖維","05":"電機機械","06":"電器電纜","08":"玻璃陶瓷","09":"造紙工業","10":"鋼鐵工業","11":"橡膠工業","12":"汽車工業","14":"建材營造","15":"航運業","16":"觀光餐旅","17":"金融保險","18":"貿易百貨","19":"綜合","20":"其他","21":"化學工業","22":"生技醫療","23":"油電燃氣","24":"半導體","25":"電腦及週邊設備","26":"光電業","27":"通信網路","28":"電子零組件","29":"電子通路","30":"資訊服務","31":"其他電子","32":"文化創意","33":"農業科技","35":"綠能環保","36":"數位雲端","37":"運動休閒","38":"居家生活"}


def parse_universe(listed,otc):
    rows=[]
    for market,data in [("上市",listed),("上櫃",otc)]:
        if not isinstance(data,list) or len(data)<500:raise ValueError(f"{market}名單筆數異常")
        before=len(rows)
        for r in data:
            code=str(r.get("公司代號",r.get("SecuritiesCompanyCode",""))).strip()
            industry=str(r.get("產業別",r.get("SecuritiesIndustryCode",""))).zfill(2)
            if not re.fullmatch(r"\d{4}",code) or industry=="91":continue
            name=str(r.get("公司簡稱",r.get("CompanyAbbreviation",code))).strip()
            rows.append({"code":code,"name":name,"market":market,"sector":INDUSTRIES.get(industry,f"其他產業 {industry}"),
                         "ticker":code+(".TW" if market=="上市" else ".TWO"),"channel":("tse_" if market=="上市" else "otc_")+code+".tw",
                         "list_date":str(r.get("出表日期",r.get("Date","")))})
        if len(rows)-before<500:raise ValueError(f"{market}名單欄位解析不完整")
    table=pd.DataFrame(rows)
    if table.code.duplicated().any():raise ValueError("上市上櫃名單出現重複代碼，暫停掃描以免重複計權")
    return table


@st.cache_data(ttl=21600,show_spinner=False)
def market_universe():
    urls=["https://openapi.twse.com.tw/v1/opendata/t187ap03_L","https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"]
    with ThreadPoolExecutor(max_workers=2) as pool:data=list(pool.map(get_json,urls))
    return parse_universe(*data)


def quote_record(code,price,reference,stamp,**extra):
    price=number(price);reference=number(reference);stamp=pd.Timestamp(stamp)
    if stamp.tzinfo is None:stamp=stamp.tz_localize("Asia/Taipei")
    else:stamp=stamp.tz_convert("Asia/Taipei")
    if not math.isfinite(price) or not math.isfinite(reference) or price<=0 or reference<=0:raise ValueError("無有效成交價或參考價")
    return dict(code=code,price=price,reference=reference,timestamp=stamp,**extra)


def parse_mis(payload):
    result={}
    for r in payload.get("msgArray",[]):
        try:
            code="^TWII" if r.get("c")=="t00" and r.get("ex")=="tse" else str(r["c"])
            stamp=pd.Timestamp(f"{r['d']} {r['t']}",tz="Asia/Taipei")
            # 5 秒快照內剛好沒成交時 z 是「-」：改用前一筆成交價 pz，再沒有就用最佳委買委賣中間價（標示來源）
            price,kind=r.get("z"),"成交價"
            if not math.isfinite(number_or_nan(price)):
                bid=number_or_nan(str(r.get("b","")).split("_")[0]);ask=number_or_nan(str(r.get("a","")).split("_")[0])
                if math.isfinite(number_or_nan(r.get("pz"))):price,kind=r.get("pz"),"前一筆成交價"
                elif math.isfinite(bid) and math.isfinite(ask) and bid>0 and ask>0:price,kind=(bid+ask)/2,"委買委賣中間價"
            q=quote_record(code,price,r["y"],stamp,price_kind=kind)
            for out,field,scale in [("Open","o",1),("High","h",1),("Low","l",1),("Volume","v",1000)]:
                try:q[out]=number(r[field])*scale
                except (KeyError,ValueError):pass
            result[code]=q
        except (KeyError,ValueError,TypeError):continue
    return result


def mis_batch(channels):
    response=requests.get("https://mis.twse.com.tw/stock/api/getStockInfo.jsp",
        params={"ex_ch":"|".join(channels),"json":"1","delay":"0"},timeout=12,
        headers={"User-Agent":"Mozilla/5.0","Referer":"https://mis.twse.com.tw/stock/index.jsp"})
    response.raise_for_status()
    return parse_mis(response.json())


@st.cache_data(ttl=30,show_spinner=False)
def public_quotes(channels):
    # Verify benchmark first; do not launch a full scan against an unavailable endpoint.
    quotes=mis_batch(["tse_t00.tw"])
    if "^TWII" not in quotes:raise ValueError("公開盤中來源未提供加權指數有效成交價；不改用昨收代替")
    batches=[list(channels[i:i+50]) for i in range(0,len(channels),50)];errors=[]
    def safe(batch):
        try:return mis_batch(batch),None
        except Exception as exc:return {},str(exc)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for data,error in pool.map(safe,batches):
            quotes.update(data)
            if error:errors.append(error)
    # Benchmark is refreshed after batching; timestamps still gate every stock below.
    quotes.update(mis_batch(["tse_t00.tw"]))
    return quotes,errors,"證交所 MIS 盤中快照"



@st.cache_resource
def yahoo_state16():
    return {'lock':threading.Lock(),'cooldown':0.,'day':None,'cursor':0,'frames':{}}


def is_rate_limit16(exc):
    return any(x in str(exc).lower() for x in ('429','ratelimit','rate limited','too many requests'))


@st.cache_data(ttl=21600,show_spinner=False)
def daily_reference16(symbol,previous):
    f=yahoo_minute_frame(yf.Ticker(symbol).history(period='1mo',interval='1d',auto_adjust=False,actions=False,raise_errors=True,timeout=12))
    f=f.loc[f.index.date==previous]
    if f.empty:raise ValueError(f'{symbol} 缺少 {previous} 正式日線昨收')
    return float(f.Close.iloc[-1])


def aligned_quote16(code,frame,anchor,reference,alignment=300):
    frame=yahoo_minute_frame(frame)
    f=frame.loc[(frame.index.date==anchor.date())&(frame.index<=anchor)].between_time('09:00','13:30')
    if f.empty:raise ValueError('共同截止時間以前無當日分鐘棒')
    stamp=f.index[-1]
    # 冷門股最後一筆成交可能早於大盤時間；沒有新成交時最後成交價就是最新價。保留原成交時間並標記 carry。
    stale=(anchor-stamp).total_seconds()>alignment
    if stale and code=='^TWII':raise ValueError('大盤時間差超過設定')
    carry=stale
    # Keep original bar timestamp, never replace with anchor/request time.
    return quote_record(code,f.Close.iloc[-1],reference,stamp,Open=float(f.Open.iloc[0]),High=float(f.High.max()),Low=float(f.Low.min()),Volume=float(f.Volume.sum(min_count=1)),reference_kind='前一交易日正式收盤',source='Yahoo延遲分鐘資料',carry=carry)


@st.cache_data(ttl=300,show_spinner=False)
def yahoo_scan16(members,asof,max_age,alignment):
    state=yahoo_state16()
    if clock.monotonic()<state['cooldown']:raise ValueError('Yahoo限流冷卻中，請稍後再試；手動更新不會取消冷卻')
    if not state['lock'].acquire(blocking=False):raise ValueError('另一輪Yahoo掃描進行中，請等待完成')
    try:
        now=pd.Timestamp(taipei_now());diag={'started_at':str(now),'requested_stocks':len(members),'errors':[]}
        previous=expected_session(datetime.combine(asof,time(8),tzinfo=ZoneInfo('Asia/Taipei')))
        if previous is None:raise ValueError('交易日曆不可用，不能猜測前一交易日')
        benchmark=yahoo_minute_frame(yf.Ticker('^TWII').history(period='1d',interval='1m',auto_adjust=False,actions=False,raise_errors=True,timeout=12))
        completed=benchmark.loc[(benchmark.index.date==asof)&(benchmark.index+pd.Timedelta(minutes=1)<=now)].between_time('09:00','13:30') if not benchmark.empty else benchmark
        if completed.empty:raise ValueError(f'Yahoo未提供 {asof} 已完成大盤分鐘棒')
        anchor=completed.index[-1]
        intraday=now.date()==asof and time(9)<=now.time()<time(13,30)
        if intraday and (now-anchor).total_seconds()>max_age:raise ValueError(f'Yahoo大盤截至 {anchor}，已超過容許延遲 {max_age/60:.0f} 分鐘')
        try:refs,ref_errors,_=closing_quotes(previous)
        except Exception as exc:refs={};ref_errors=[str(exc)]
        diag['previous_close_date']=str(previous);diag['previous_close_errors']=ref_errors
        ref=refs.get('^TWII',{}).get('price') or daily_reference16('^TWII',previous)
        quotes={'^TWII':aligned_quote16('^TWII',completed,anchor,ref,alignment)}
        if state['day']!=asof:state.update(day=asof,cursor=0,frames={})
        start=state['cursor']%max(1,len(members));ordered=list(members[start:])+list(members[:start]);began=clock.monotonic();attempted=0
        def read(member):
            code,symbol=member
            try:
                f=yahoo_minute_frame(yf.Ticker(symbol).history(period='1d',interval='1m',auto_adjust=False,actions=False,raise_errors=True,timeout=12))
                if f.empty:raise ValueError('Yahoo回傳空分鐘資料')
                return code,f,None
            except Exception as exc:return code,None,str(exc)
        for offset in range(0,len(ordered),12):
            if clock.monotonic()-began>=240:diag['stop_reason']='本輪240秒預算已到，下輪從未查詢處繼續';break
            batch=ordered[offset:offset+12]
            with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(read,batch))
            attempted+=len(batch);limited=False
            for code,f,error in results:
                if error:
                    diag['errors'].append({'code':code,'stage':'download','error':error})
                    if is_rate_limit16(error):limited=True
                else:state['frames'][code]=f
            if limited:
                state['cooldown']=clock.monotonic()+300
                diag['stop_reason']='Yahoo限流，停止後續批次並冷卻5分鐘';break
        state['cursor']=(start+attempted)%max(1,len(members))
        diag['attempted_this_round']=attempted;diag['next_start_offset']=state['cursor'];diag['anchor']=str(anchor)
        diag['downloaded_stock_frames']=len(state['frames']);diag['missing_previous_close']=0
        missing_refs=[symbol for code,symbol in members if code in state['frames'] and code not in refs]
        if missing_refs:
            fixed,notes=repair_history17(missing_refs,[previous],limit=40)
            diag['reference_repair_notes']=notes
            refs=dict(refs)
            for code,symbol in members:
                value=fixed.get(symbol,{}).get(previous)
                if value and code not in refs:refs[code]={'price':value}
        current=pd.Timestamp(taipei_now())
        for code,symbol in members:
            f=state['frames'].get(code)
            if f is None:continue
            reference=refs.get(code,{}).get('price')
            if not reference:
                diag['missing_previous_close']+=1
                diag['errors'].append({'code':code,'stage':'reference','error':'缺少前一交易日正式收盤；保留下載結果，不用尾盤分鐘價猜昨收'})
                continue
            try:
                q=aligned_quote16(code,f,anchor,reference,alignment)
                if intraday and (current-q['timestamp']).total_seconds()>max_age:raise ValueError('下載完成時報價已過期')
                quotes[code]=q
            except Exception as exc:diag['errors'].append({'code':code,'stage':'alignment','error':str(exc)})
        diag['valid_stock_quotes']=len(quotes)-1;diag['finished_at']=str(current)
        age=(current-anchor).total_seconds()/60
        source=f'Yahoo分鐘資料 · 截至 {anchor:%m/%d %H:%M} · '+(f'落後 {age:.1f} 分鐘（非逐筆）' if intraday else '盤後歷史快照，非正式收盤價')
        errors=[f"{x['code']} {x['stage']}：{x['error']}" for x in diag['errors']]
        if diag.get('stop_reason'):errors.insert(0,diag['stop_reason'])
        return quotes,errors,source,None if intraday else asof,'Yahoo延遲掃描' if intraday else 'Yahoo盤後歷史快照',diag
    except Exception as exc:
        if is_rate_limit16(exc):state['cooldown']=clock.monotonic()+300
        raise
    finally:state['lock'].release()


def load_yahoo16(universe,max_age,alignment):
    asof=expected_session(taipei_now().replace(hour=14,minute=0,second=0,microsecond=0))
    if asof is None:raise ValueError('交易日曆不可用')
    return yahoo_scan16(tuple(zip(universe.code,universe.ticker)),asof,max_age,alignment)


def broker_quotes(path,now=None,max_age=120):
    if not path:raise ValueError("尚未設定券商即時報價檔，請先由已登入的券商程式輸出報價")
    now=pd.Timestamp(now or taipei_now())
    payload=json.loads(Path(path).expanduser().read_text(encoding="utf-8-sig"))
    generated=pd.Timestamp(payload["generated_at"])
    if generated.tzinfo is None:raise ValueError("generated_at 必須附時區")
    if not -5<=(now-generated).total_seconds()<=max_age:raise ValueError("券商報價檔已過期或時間異常")
    quotes={}
    for r in payload.get("quotes",[]):
        try:
            stamp=pd.Timestamp(r["timestamp"])
            if stamp.tzinfo is None:continue
            q=quote_record(str(r["code"]),r["price"],r["reference_price"],stamp)
            for key in ("Open","High","Low","Volume"):
                if key in r and math.isfinite(float(r[key])):q[key]=float(r[key])
            quotes[q["code"]]=q
        except (KeyError,ValueError,TypeError):continue
    return quotes,[],str(payload.get("source","券商報價檔"))


def report_tables(data):
    if data.get("tables"):return data["tables"]
    return [{"fields":v,"data":data.get("data"+k[6:],[])} for k,v in data.items() if k.startswith("fields")]


def parse_close_quotes(data,market,day):
    # Daily endpoints must explicitly identify the requested session.
    returned=re.sub(r"\D","",str(data.get("date","")))
    if returned!=day.strftime("%Y%m%d"):raise ValueError(f"{market}回傳日期不符")
    quotes={};stamp=pd.Timestamp(datetime.combine(day,time(13,30),tzinfo=ZoneInfo("Asia/Taipei")))
    for table in report_tables(data):
        for values in table.get("data",[]):
            r=dict(zip(table.get("fields",[]),values))
            try:
                if "指數" in r and r["指數"]=="發行量加權股價指數":
                    code="^TWII";price=number(r["收盤指數"]);change=number(r["漲跌點數"])
                    sign=BeautifulSoup(r.get("漲跌(+/-)",""),"html.parser").get_text().strip()
                    change= -abs(change) if sign=="-" else abs(change) if sign=="+" else 0
                    q=quote_record(code,price,price-change,stamp)
                elif market=="上市" and "證券代號" in r:
                    code=str(r["證券代號"]);price=number(r["收盤價"])
                    sign=BeautifulSoup(r["漲跌(+/-)"],"html.parser").get_text().strip()
                    if sign not in ("+","-",""):continue
                    change=number(r["漲跌價差"])*(-1 if sign=="-" else 1)
                    q=quote_record(code,price,price-change,stamp,Open=number(r["開盤價"]),High=number(r["最高價"]),Low=number(r["最低價"]),Volume=number(r["成交股數"]))
                elif market=="上櫃" and "代號" in r:
                    code=str(r["代號"]);price=number(r["收盤"]);change=number(r["漲跌"])
                    q=quote_record(code,price,price-change,stamp,Open=number(r["開盤"]),High=number(r["最高"]),Low=number(r["最低"]),Volume=number(r["成交股數"]))
                else:continue
                quotes[code]=q
            except (ValueError,KeyError,TypeError):continue
    if not quotes:raise ValueError(f"{market}尚無 {day} 有效收盤資料")
    return quotes


@st.cache_data(ttl=60,show_spinner=False)
def closing_quotes(day):
    urls=[("上市","https://www.twse.com.tw/exchangeReport/MI_INDEX",{"date":day.strftime("%Y%m%d"),"type":"ALLBUT0999","response":"json"}),
          ("上櫃","https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes",{"date":day.strftime("%Y/%m/%d"),"response":"json"})]
    def read(item):
        market,url,params=item;last=None
        for attempt in range(3):  # 交易所偶發失敗：重試，避免整個市場被靜默漏掉
            try:return parse_close_quotes(get_json(url,params),market,day),None
            except Exception as exc:
                last=exc;clock.sleep(1.5*(attempt+1))
        return {},f"{market}：{last}"
    quotes={};errors=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for data,error in pool.map(read,urls):
            quotes.update(data)
            if error:errors.append(error)
    if "^TWII" not in quotes:raise ValueError("；".join(errors) or "加權指數收盤未發布")
    return quotes,errors,"交易所正式收盤日資料"


def session_quote_snapshot(universe,max_age=120,now=None):
    """The public snapshot mode follows market sessions; it never labels a close as live."""
    now=now or taipei_now()
    today_session=expected_session(now.replace(hour=14,minute=0,second=0,microsecond=0))
    if today_session is None:raise ValueError("交易日曆待確認，無法判定盤中或盤後")
    live=today_session==now.date() and time(9)<=now.time()<time(13,30)
    if live:
        quotes,errors,source=public_quotes(tuple(universe.channel))
        return quotes,errors,source,None,"盤中快照"
    day=expected_session(now)
    if day is None:raise ValueError("最近收盤交易日待確認")
    quotes,errors,source=closing_quotes(day)
    phase="盤前" if today_session==now.date() and now.time()<time(9) else "盤後／休市"
    return quotes,errors,f"{phase} · {source} · {day}",day,f"{phase}收盤 {day:%m/%d}"


def resolve_snapshot(state,key,loader):
    """Keep an explicitly labelled successful snapshot across display-filter reruns."""
    try:
        result=loader()
        if result["valid"]==0 and result["all_sectors"].empty:
            if not result.get("quotes"):
                raise ValueError("；".join(result["missing"]) or "沒有有效行情")
            return result,False,None
        state[key]=result
        return result,False,None
    except Exception as exc:
        if key in state:return state[key],True,str(exc)
        raise


def intraday_tables(universe,quotes,now=None,max_age=120,closing_day=None):
    now=pd.Timestamp(now or taipei_now());market=quotes.get("^TWII")
    columns=["趨勢","族群板塊","動能(%)","漲幅(%)","覆蓋","資料日"]
    empty=pd.DataFrame(columns=columns)
    def fresh(q):
        if not q:return False
        ts=q["timestamp"]
        if closing_day is not None:return ts.date()==closing_day
        age=(now-ts).total_seconds()
        return ts.date()==now.date() and -5<=age<=max_age
    if not fresh(market):return empty,{},["加權指數非當日有效報價或已過期"],0
    valid={};missing=[]
    for code in universe.code:
        q=quotes.get(code)
        if not fresh(q) or abs((q["timestamp"]-market["timestamp"]).total_seconds())>max_age:
            missing.append(code);continue
        valid[code]=q
    index=pd.DatetimeIndex([market["timestamp"]-pd.Timedelta(days=1),market["timestamp"]])
    market_ratio=market["price"]/market["reference"]
    groups={};rows=[]
    for name,members in universe.groupby("sector",sort=True):
        eligible=members[members.code.isin(valid)]
        minimum=max(min(3,len(members)),math.ceil(len(members)*.8))
        if len(eligible)<minimum:continue
        ratios=[valid[c]["price"]/valid[c]["reference"] for c in eligible.code]
        sector_ratio=sum(ratios)/len(ratios)
        rs=sector_ratio/market_ratio-1
        basket=pd.DataFrame({"Close":[100,100*sector_ratio]},index=index)
        prices={r.ticker:pd.Series([valid[r.code]["reference"],valid[r.code]["price"]],index=index) for r in eligible.itertuples()}
        groups[name]={"rs":rs,"basket":basket,"members":prices,"missing":list(members.loc[~members.code.isin(valid),"code"]),"quotes":{c:valid[c] for c in eligible.code}}
        rows.append({"趨勢":"強勢" if rs>0 else "弱勢","族群板塊":name,"動能(%)":rs*100,"漲幅(%)":(sector_ratio-1)*100,
                     "覆蓋":f"{len(eligible)}/{len(members)}","資料日":str(market["timestamp"].date())})
    return pd.DataFrame(rows,columns=columns).sort_values("動能(%)",ascending=False).reset_index(drop=True),groups,missing,len(valid)


@st.cache_data(ttl=300,show_spinner=False)
def historical_close_snapshot(day):
    quotes,errors,source=closing_quotes(day)
    # 任一市場缺資料就不接受：殘缺的一天會讓整個市場（例如上櫃）的歷史都不齊。
    if not quotes or errors:raise ValueError("歷史收盤資料不完整："+"；".join(errors))
    return quotes


@st.cache_data(ttl=300,show_spinner=False)
def market_history_window(asof,periods=20):
    # One bulk request per market/day, shared by every stock and all lookbacks.
    previous=expected_session(datetime.combine(asof,time(8),tzinfo=ZoneInfo("Asia/Taipei")))
    market=ranking_history("^TWII",previous)
    days=list(market.index[market.index.date<asof][-periods:].date)
    if len(days)<periods or days[-1]!=previous:raise ValueError(f"大盤歷史交易日不足或尚未更新，無法計算 {periods} 日比較")
    def read(day):
        try:return day,historical_close_snapshot(day),None
        except Exception as exc:return day,{},f"{day}：{exc}"
    with ThreadPoolExecutor(max_workers=3) as pool:items=list(pool.map(read,days))
    return days,{day:q for day,q,error in items},[error for day,q,error in items if error]


@st.cache_resource
def history_repair_state17():
    return {'lock':threading.Lock(),'frames':{},'attempts':{}}


def repair_history17(symbols,days,limit=120):
    """Bounded daily-history fallback. Keep dates exact; never fill missing sessions."""
    state=history_repair_state17();quotes_state=yahoo_state16();result={};notes=[]
    if not days:return result,notes
    required=set(days);key_day=max(days)
    if not state['lock'].acquire(blocking=False):return {},['歷史補資料已在執行，下一輪再檢查']
    try:
        pending=[]
        for symbol in dict.fromkeys(symbols):
            item=state['frames'].get(symbol)
            if item is not None and required.issubset(set(item.index.date)):
                result[symbol]={d:float(item.loc[item.index.date==d,'Close'].iloc[-1]) for d in days};continue
            if clock.monotonic()-state['attempts'].get((symbol,key_day),-1e9)>=300:pending.append(symbol)
        pending.sort(key=lambda sym:state['attempts'].get((sym,key_day),-1e9))
        started=clock.monotonic();attempted=0
        def read(symbol):
            try:
                f=yahoo_minute_frame(yf.Ticker(symbol).history(period='3mo',interval='1d',auto_adjust=False,actions=False,raise_errors=True,timeout=12))
                f=f.loc[f.index.date<=key_day]
                if f.empty:raise ValueError('日線回傳空資料')
                return symbol,f,None
            except Exception as exc:return symbol,None,str(exc)
        for offset in range(0,min(limit,len(pending)),6):
            if clock.monotonic()<quotes_state['cooldown']:
                notes.append('Yahoo限流冷卻中，保留歷史缺口');break
            if clock.monotonic()-started>=90:
                notes.append('本輪歷史補資料時間已到，下輪繼續');break
            batch=pending[offset:min(offset+6,limit)]
            with ThreadPoolExecutor(max_workers=2) as pool:items=list(pool.map(read,batch))
            limited=False;attempted+=len(batch)
            for symbol,f,error in items:
                state['attempts'][(symbol,key_day)]=clock.monotonic()
                if error:
                    notes.append(f'{symbol} 日線補資料：{error}')
                    if is_rate_limit16(error):limited=True
                else:
                    state['frames'][symbol]=f
                    # Partial successful dates can repair individual cells, without fabricating others.
                    result[symbol]={d:float(f.loc[f.index.date==d,'Close'].iloc[-1]) for d in days if d in set(f.index.date)}
            if limited:
                quotes_state['cooldown']=clock.monotonic()+300;notes.append('Yahoo日線限流，停止補資料');break
        if len(pending)>attempted:notes.append(f'尚有 {len(pending)-attempted} 檔待補日線；受單輪上限／冷卻限制')
        return result,notes
    finally:state['lock'].release()


GROUPING_MODES=["產業鏈細分","官方產業別"]


def sector_groups(universe,grouping="產業鏈細分"):
    """族群分組：產業鏈細分（櫃買中心產業價值鏈，一檔可屬多個族群）或官方產業別。回傳 [(族群名, 成分DataFrame)]。"""
    if grouping=="官方產業別":
        return list(universe.groupby('sector',sort=True))
    try:
        gmap=industry_chain.groups(set(universe.code))
    except Exception:
        return list(universe.groupby('sector',sort=True))   # 產業鏈資料取不到時退回官方產業別
    bycode=universe.set_index('code',drop=False)
    return [(name,bycode.loc[[c for c in codes if c in bycode.index]]) for name,codes in sorted(gmap.items())]


def multiday_market_tables(universe,quotes,periods=10,now=None,max_age=120,closing_day=None,history=None,grouping="產業鏈細分"):
    now=pd.Timestamp(now or taipei_now());market=quotes.get('^TWII')
    columns=['趨勢','族群板塊','動能(%)','漲幅(%)','成交值(億)','覆蓋','資料日']
    records=[];current={};errors=[];sector_audit=[]
    def fresh(q):
        if not q:return False
        stamp=q['timestamp']
        if q.get('carry'):return stamp.date()==(closing_day if closing_day is not None else now.date())
        return stamp.date()==closing_day if closing_day is not None else stamp.date()==now.date() and -5<=(now-stamp).total_seconds()<=max_age
    benchmark_ok=fresh(market)
    for r in universe.itertuples():
        q=quotes.get(r.code);status='行情有效'
        if not q:status='缺報價或昨收'
        elif not fresh(q):status='報價日期不符或過期'
        elif not benchmark_ok:status='大盤無有效報價'
        elif not q.get('carry') and abs((q['timestamp']-market['timestamp']).total_seconds())>max_age:status='與大盤時間差過大'
        else:current[r.code]=q
        records.append({'代碼':r.code,'名稱':r.name,'板塊':r.sector,'狀態':status,'缺歷史日期':'','報價時間':str(q['timestamp']) if q else ''})
    received=sum(r.code in quotes for r in universe.itertuples());history_complete=set();included=set();groups={};rows=[]
    def finish():
        counts={}
        for r in records:counts[r['狀態']]=counts.get(r['狀態'],0)+1
        table=pd.DataFrame(rows,columns=columns).sort_values('動能(%)',ascending=False).reset_index(drop=True)
        table.attrs['audit17']={'counts':{'名單股數':len(universe),'有價格及參考價':received,'通過時間檢查':len(current),'歷史齊全':len(history_complete),'進入板塊排名':len(included)},'excluded_counts':counts,'stocks':records,'sectors':sector_audit,'errors':errors,'history_source':'交易所；缺漏時以Yahoo未還原日線補齊'}
        missing=[f"{r['代碼']}：{r['狀態']} {r['缺歷史日期']}" for r in records if r['狀態']!='進入板塊排名']+errors
        if not rows:missing.insert(0,f'行情有效 {len(current)} 檔，歷史齊全 {len(history_complete)} 檔；沒有板塊通過覆蓋門檻，請看排除明細')
        return table,groups,missing,len(included)
    if not current:return finish()
    asof=market['timestamp'].date()
    try:
        days,past,history_errors=history if history is not None else market_history_window(asof,periods)
        errors.extend(history_errors);days=[d for d in days if d<asof][-periods:]
        if len(days)!=periods:raise ValueError(f'需 {periods} 個共同歷史交易日，實際 {len(days)}')
    except Exception as exc:
        errors.append(str(exc))
        for r in records:
            if r['代碼'] in current:r['狀態']='歷史交易日取得失敗'
        return finish()
    # Copy shared cached data before repairing individual missing prices.
    past={d:dict(past.get(d,{})) for d in days}
    symbols={r.code:r.ticker for r in universe.itertuples() if r.code in current};symbols['^TWII']='^TWII'
    need=[symbol for code,symbol in symbols.items() if any(code not in past[d] for d in days)]
    if need and history is None:
        fixes,notes=repair_history17(need,days);errors.extend(notes)
        for code,symbol in symbols.items():
            for d,value in fixes.get(symbol,{}).items():
                if code not in past[d] and math.isfinite(value) and value>0:past[d][code]={'price':value,'source':'Yahoo未還原日線補齊'}
    if any('^TWII' not in past[d] for d in days):
        errors.append('大盤歷史仍缺漏，暫停RS；不使用零值或前值填補')
        for r in records:
            if r['代碼'] in current:r['狀態']='大盤歷史不足'
        return finish()
    calendar=pd.DatetimeIndex([pd.Timestamp(d,tz='Asia/Taipei') for d in days+[asof]])
    benchmark=pd.Series([past[d]['^TWII']['price'] for d in days]+[market['price']],index=calendar)
    bycode={r['代碼']:r for r in records};frames={}
    for code,q in current.items():
        absent=[str(d) for d in days if code not in past[d]]
        if absent:
            bycode[code]['狀態']='個股歷史不足';bycode[code]['缺歷史日期']=','.join(absent);continue
        history_complete.add(code)
        frames[symbols[code]]=pd.DataFrame({'Close':[past[d][code]['price'] for d in days]+[q['price']]},index=calendar)
        bycode[code]['狀態']='板塊覆蓋不足'
    for name,members in sector_groups(universe,grouping):
        minimum=max(min(3,len(members)),math.ceil(len(members)*.8))
        complete=[c for c in members.code if c in history_complete]
        sector_audit.append({'板塊':name,'全部':len(members),'有價格及參考價':sum(c in quotes for c in members.code),'時間有效':sum(c in current for c in members.code),'歷史齊全':len(complete),'最低需要':minimum,'尚缺':max(0,minimum-len(complete)),'狀態':'可排名' if len(complete)>=minimum else '覆蓋不足'})
        basket,valid,excluded=equal_weight_basket(list(members.ticker),frames,calendar)
        if basket.empty:continue
        rs=rs_momentum(basket.Close,benchmark,periods)
        changes={ticker:(quotes[ticker.split('.')[0]]['price']/quotes[ticker.split('.')[0]]['reference']-1)*100 for ticker in valid}
        codes=[t.split('.')[0] for t in valid];included.update(codes)
        for c in codes:bycode[c]['狀態']='進入板塊排名'
        groups[name]={'basket':basket,'members':valid,'rs':rs,'missing':excluded,'day_changes':changes,'quotes':{c:quotes[c] for c in codes}}
        # 當日成交值（億元）＝成分股 價格×成交股數 加總：相對強勢要有量才是真金白銀
        value=sum(quotes[c]['price']*(quotes[c].get('Volume') or 0) for c in codes)/1e8
        rows.append({'趨勢':'強勢' if rs>0 else '弱勢','族群板塊':name,'動能(%)':rs*100,'漲幅(%)':sum(changes.values())/len(changes),
                     '成交值(億)':value,'覆蓋':f'{len(valid)}/{len(members)}','資料日':str(asof)})
    return finish()



def chip_number(value):
    text=re.sub(r'<[^>]+>','',str(value)).replace(',','').strip().replace('−','-')
    if not text or text in ('--','---','N/A'):raise ValueError('籌碼欄位缺值')
    number=float(text)
    if not math.isfinite(number):raise ValueError('籌碼欄位數字異常')
    return number


def parse_chip_report(payload,market,kind,day):
    if str(payload.get('stat','')).lower()!='ok':raise ValueError('交易所尚未提供此日資料')
    if str(payload.get('date',''))!=day.strftime('%Y%m%d'):raise ValueError('籌碼報表日期不符')
    tables=payload.get('tables') or [payload]
    result={}
    for table in tables:
        fields=table.get('fields',[]);rows=table.get('data',[])
        if not fields or fields[0] not in ('代號','證券代號'):continue
        if kind=='institution':
            if market=='上市':
                required=['外陸資買賣超股數(不含外資自營商)','投信買賣超股數','自營商買賣超股數','三大法人買賣超股數']
                if not all(k in fields for k in required):raise ValueError('上市法人欄位已變更')
                indexes=[fields.index(k) for k in required]
            else:
                if len(fields)!=24 or fields[-1]!='三大法人買賣超股數合計':raise ValueError('上櫃法人欄位已變更')
                indexes=[10,13,22,23] # foreign total, trust, dealer total, reported total
            for row in rows:
                try:
                    vals=[chip_number(row[i])/1000 for i in indexes]
                    if abs(sum(vals[:3])-vals[3])>.002:continue
                    result[str(row[0]).strip()]=dict(zip(['foreign','trust','dealer','total'],vals))
                except (ValueError,IndexError):continue
        else:
            if market=='上市':
                if len(fields)!=16 or fields[2:7]!=['買進','賣出','現金償還','前日餘額','今日餘額']:raise ValueError('上市資券欄位已變更')
                indexes=[5,6,2,3,4,11,12,8,9,10]
            else:
                names=['前資餘額(張)','資餘額','資買','資賣','現償','前券餘額(張)','券餘額','券買','券賣','券償']
                if not all(k in fields for k in names):raise ValueError('上櫃資券欄位已變更')
                indexes=[fields.index(k) for k in names]
            keys=['fin_previous','fin_balance','fin_buy','fin_sell','fin_repay','short_previous','short_balance','short_buy','short_sell','short_repay']
            for row in rows:
                try:
                    values=[chip_number(row[i]) for i in indexes]
                    if min(values)<0:continue
                    record=dict(zip(keys,values))
                    record['fin_change']=record['fin_balance']-record['fin_previous']
                    record['short_change']=record['short_balance']-record['short_previous']
                    result[str(row[0]).strip()]=record
                except (ValueError,IndexError):continue
    if not result:raise ValueError('報表尚無可用個股資料')
    return result


@st.cache_data(ttl=300,show_spinner=False)
def chip_report(market,kind,day):
    if market=='上市':
        path='fund/T86' if kind=='institution' else 'exchangeReport/MI_MARGN'
        url='https://www.twse.com.tw/'+path
        params={'date':day.strftime('%Y%m%d'),'selectType':'ALLBUT0999' if kind=='institution' else 'ALL','response':'json'}
    else:
        url='https://www.tpex.org.tw/www/zh-tw/'+('insti/dailyTrade' if kind=='institution' else 'margin/balance')
        params={'date':day.strftime('%Y/%m/%d'),'response':'json'}
        if kind=='institution':params['type']='Daily'
    return parse_chip_report(get_json(url,params),market,kind,day)


@st.cache_data(ttl=300,show_spinner=False)
def latest_chip_report(market,kind,target):
    day=target;errors=[]
    for attempt in range(3):
        try:return {'records':chip_report(market,kind,day),'date':day,'errors':errors}
        except Exception as exc:errors.append(f'{day}：{exc}')
        day=expected_session(datetime.combine(day,time(8),tzinfo=ZoneInfo('Asia/Taipei')))
        if day is None:break
    return {'records':{},'date':None,'errors':errors}


def load_stock_chips(code,market,target):
    if target is None:return {kind:{'record':None,'date':None,'status':'交易日曆待確認','errors':[]} for kind in ('institution','margin')}
    def read(kind):
        try:
            report=latest_chip_report(market,kind,target)
            record=report['records'].get(code)
            status='查詢交易日已發布' if report['date']==target else '較早資料・請留意日期'
            if record is None:status='報表未列此股（不代表為零）' if report['date'] else '來源未就緒'
            return kind,{'record':record,'date':report['date'],'status':status,'errors':report['errors']}
        except Exception as exc:return kind,{'record':None,'date':None,'status':'來源未就緒','errors':[str(exc)]}
    with ThreadPoolExecutor(max_workers=2) as pool:return dict(pool.map(read,('institution','margin')))


CHIP_CSS='''<style>
[data-testid="stSelectbox"] select,[data-testid="stSelectbox"] [role="combobox"],[data-testid="stSelectbox"] [data-baseweb="select"]>div{background:#17222f!important;color:#d5dfec!important;border-color:#394759!important}
[data-testid="stButtonGroup"] button{background:#14202c!important;color:#aebfd3!important;border-color:#394759!important}
[data-testid="stButtonGroup"] button[data-selected="true"]{background:#3b3423!important;color:#efc979!important}

[data-testid="stButtonGroup"] [data-variant="segmented_control"],[data-testid="stButtonGroup"] button{background:#18212d!important;color:#bdcbdc!important;border:1px solid #344150!important;font-size:16px!important}[data-testid="stButtonGroup"] [data-variant="segmented_control"][data-selected],[data-testid="stButtonGroup"] [data-variant="segmented_control"][aria-pressed="true"],[data-testid="stButtonGroup"] button[aria-pressed="true"],[data-testid="stBaseButton-segmented_controlActive"]{background:#353024!important;color:#ead29a!important;border-color:#67583b!important}
.chip-shell{border:1px solid #344150;border-radius:12px;background:#101823;padding:18px;margin-bottom:12px}.chip-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px}.chip-heading b{font-size:20px;color:#ecf1f8}.chip-date{font-size:13px;color:#c7b47e}.chip-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.chip-card{background:#182330;border-radius:8px;padding:14px 10px;min-width:0}.chip-label{color:#aebccd;font-size:14px}.chip-value{font-size:24px;font-weight:650;letter-spacing:-.5px;font-variant-numeric:tabular-nums;white-space:nowrap}.chip-note{color:#aab9cb;font-size:13px;line-height:1.6;margin-top:12px}.chip-status{color:#d6bd80;font-size:13px;margin-bottom:10px}.chip-margin{display:grid;grid-template-columns:1fr 1fr;gap:16px}.chip-margin h4{margin:0 0 10px;font-size:18px;color:#dfc88e}.chip-margin table{width:100%;border-collapse:collapse;font-size:15px;margin:0!important}.chip-margin h4{padding:0!important;line-height:1.3!important}.chip-margin td{padding:7px 0;border-bottom:1px solid #283543}.chip-margin td:last-child{text-align:right;font-variant-numeric:tabular-nums}.chip-up{color:#f17c7e}.chip-down{color:#55c8a4}.chip-neutral{color:#e7edf5}.chip-empty{padding:20px;color:#b8c6d6}.chip-title{font-size:25px;font-weight:650;margin:4px 0 14px}.chip-title small{font-size:15px;color:#c4ad79;margin-left:10px}
[data-testid="stTabs"] [data-baseweb="tab-list"]{gap:20px}[data-testid="stTabs"] [data-baseweb="tab"]{font-size:17px;height:42px}
@media(max-height:820px){.chip-shell{padding:12px;margin-bottom:8px}.chip-card{padding:9px}.chip-heading{margin-bottom:8px}.chip-value{font-size:21px}.chip-margin td{padding:3px 0!important;font-size:14px;line-height:1.25!important}.chip-note{margin-top:7px;font-size:12px}.chip-title{margin-bottom:8px;font-size:23px}}
</style>'''


def render_chip_panel(code,name,market,chips):
    def num(v,signed=False):return (f'{round(v):+,}' if round(v) else '0') if signed else f'{round(v):,}'   # 張數取整數
    def color(v):return 'chip-up' if v>0 else 'chip-down' if v<0 else 'chip-neutral'
    def heading(title,info):
        date=info['date'].isoformat() if info['date'] else '日期待確認'
        return f'<div class="chip-heading"><b>{title}</b><span class="chip-date">{date} · 張</span></div><div class="chip-status">{escape(info["status"])}</div>'
    out=f'<div class="chip-title">{escape(name)}<small>{escape(code)} · {market} · 盤後籌碼</small></div>'
    info=chips['institution'];r=info['record'];out+='<div class="chip-shell">'+heading('三大法人買賣超',info)
    if r:
        out+='<div class="chip-grid">'+''.join(f'<div class="chip-card"><div class="chip-label">{label}</div><div class="chip-value {color(r[key])}">{num(r[key],True)}</div></div>' for key,label in [('foreign','外資及陸資'),('trust','投信'),('dealer','自營商'),('total','三大法人合計')])+'</div>'
        out+='<div class="chip-note">正值＝買超，負值＝賣超；自營商含自行買賣與避險。'+('外資不含外資自營商。' if market=='上市' else '外資採櫃買中心外資及陸資合計口徑。')+'</div>'
    else:out+='<div class="chip-empty">尚無可顯示數字；未列入報表不等於買賣超為 0。</div>'
    out+='</div>';info=chips['margin'];r=info['record'];out+='<div class="chip-shell">'+heading('融資融券',info)
    if r:
        out+='<div class="chip-margin">'
        for prefix,title in [('fin','融資'),('short','融券')]:
            out+=f'<div><h4>{title}餘額 <span class="chip-neutral">{num(r[prefix+"_balance"])}</span> 張</h4><table>'
            for suffix,label in [('change','較前日增減'),('previous','前日餘額'),('buy','買進' if prefix=='fin' else '買進回補'),('sell','賣出' if prefix=='fin' else '賣出'),('repay','現金償還' if prefix=='fin' else '現券償還')]:
                v=r[prefix+'_'+suffix];cls=color(v) if suffix=='change' else 'chip-neutral'
                out+=f'<tr><td>{label}</td><td class="{cls}">{num(v,suffix=="change")}</td></tr>'
            out+='</table></div>'
        out+='</div><div class="chip-note">餘額增減＝當日餘額－前日餘額。增減顏色只表示方向，不代表看多或看空；融券不含借券賣出。</div>'
    else:out+='<div class="chip-empty">尚無可顯示數字；可能尚未發布、來源失敗或報表未列此股，不以 0 代替。</div>'
    out+='</div>'
    source='臺灣證券交易所' if market=='上市' else '證券櫃檯買賣中心'
    out+=f'<div class="chip-note">來源：{source}｜兩類資料分別核對日期。資料僅供觀察，不改變 RS 排名；每 5 分鐘重查，亦可按「全部更新」。</div>'
    st.markdown(out,unsafe_allow_html=True)
    errors=[e for info in chips.values() for e in info['errors']]
    if errors:
        with st.expander('資料發布／來源狀態'):st.write('\n\n'.join(errors))


@st.cache_data(ttl=300,show_spinner=False)
def chip_history_reports(market,kind,target,count=10):
    days=[];day=target
    for _ in range(count):
        if day is None:break
        days.append(day)
        day=expected_session(datetime.combine(day,time(8),tzinfo=ZoneInfo('Asia/Taipei')))
    def read(day):
        try:return day,chip_report(market,kind,day),None
        except Exception as exc:return day,{},str(exc)
    with ThreadPoolExecutor(max_workers=min(10,max(1,len(days)))) as pool:items=list(pool.map(read,days))
    return sorted(items,key=lambda item:item[0])


_CHIP_WARM={"key":None}


def warm_chip_reports():
    """背景預先下載上市／上櫃的法人、資券報表（全市場共用），切到「法人／資券」頁籤時就不用等。"""
    target=expected_session()
    if target is None or _CHIP_WARM["key"]==(target,taipei_now().strftime("%H%M")[:3]):return
    _CHIP_WARM["key"]=(target,taipei_now().strftime("%H%M")[:3])   # 約每 10 分鐘最多預熱一次
    def job():
        for market in ("上市","上櫃"):
            for kind in ("institution","margin"):
                try:chip_history_reports(market,kind,target,10)
                except Exception:pass
    threading.Thread(target=job,daemon=True,name="cqr-chip-warm").start()


@st.cache_data(ttl=300,show_spinner=False,max_entries=256)
def stock_chip_history(code,ticker,market,kind,target,count=10):
    reports=chip_history_reports(market,kind,target,count)
    errors=[];rows=[]
    try:
        history=ranking_history(ticker,target)
        prices={i.date():float(v) for i,v in history.Close.items()}
    except Exception as exc:prices={};errors.append('股價歷史：'+str(exc))
    for day,records,error in reports:
        r=records.get(code)
        row={'date':day.isoformat(),'price':prices.get(day),'available':r is not None}
        if r:row.update(r)
        if error:errors.append(f'{day}：{error}')
        elif r is None:errors.append(f'{day}：報表未列此股')
        if kind=='margin':row['ratio']=(r['short_balance']/r['fin_balance']*100) if r and r['fin_balance']>0 else None
        rows.append(row)
    return rows,errors


def momentum_score(rs):
    return round(50+50*math.tanh(float(rs)/10)) if pd.notna(rs) else None


@st.cache_resource
def interactive_chart_component():
    path=Path(tempfile.mkdtemp(prefix='cqr_chart_'))
    (path/'index.html').write_text('''<!doctype html><html><body style="margin:0;overflow:hidden"><iframe id="inner" style="width:100%;border:0;display:block" title="互動K線"></iframe><script>
const frame=document.getElementById('inner');let last='';
const send=(type,extra={})=>parent.postMessage({isStreamlitMessage:true,type,...extra},'*');
window.addEventListener('message',e=>{if(e.data.type==='streamlit:render'){const a=e.data.args;frame.style.height=a.height+'px';if(last!==a.html){last=a.html;frame.srcdoc=a.html;}send('streamlit:setFrameHeight',{height:a.height});}
if(e.source===frame.contentWindow&&e.data.type==='cq-timeframe'&&['日K','周K','月K','1分','15分','30分','60分'].includes(e.data.value)){send('streamlit:setComponentValue',{value:{timeframe:e.data.value,event:Date.now()},dataType:'json'});}});
send('streamlit:componentReady',{apiVersion:1});
</script></body></html>''',encoding='utf-8')
    return components.declare_component('cqr_interactive_chart',path=str(path))


def chip_trend_html(rows,kind,mode,height):
    labels=[r['date'][5:] for r in rows];x=list(range(len(rows)))
    if kind=='institution':
        all_series=[('foreign','外資','#16a5df'),('trust','投信','#f37373'),('dealer','自營商','#a77cdd')]
        series=all_series if mode=='全部' else [s for s in all_series if s[1]==mode]
        fields=[('foreign','外資'),('trust','投信'),('dealer','自營商'),('total','合計')];unit='張'
    elif mode=='每日增減':
        series=[('fin_change','融資','#16a5df'),('short_change','融券','#f37373')]
        fields=[('fin_change','融資增減'),('short_change','融券增減'),('fin_balance','融資餘額'),('short_balance','融券餘額')];unit='張'
    elif mode=='餘額':
        series=[('fin_balance','融資餘額','#16a5df'),('short_balance','融券餘額','#f37373')]
        fields=[('fin_balance','融資餘額'),('short_balance','融券餘額'),('fin_change','融資增減'),('short_change','融券增減')];unit='張'
    else:
        series=[('ratio','券資比','#16a5df')]
        fields=[('ratio','券資比%'),('fin_balance','融資餘額'),('short_balance','融券餘額')];unit='%'
    fig=make_subplots(specs=[[{'secondary_y':True}]])
    for key,label,color in series:
        fig.add_trace(go.Bar(x=x,y=[r.get(key) for r in rows],name=label,marker_color=color,hovertemplate=label+(' %{y:,.2f} ' if unit=='%' else ' %{y:,.0f} ')+unit+'<extra></extra>'),secondary_y=False)
    fig.add_trace(go.Scatter(x=x,y=[r.get('price') for r in rows],name='股價',mode='lines+markers',connectgaps=False,line=dict(color='#edbf53',width=2),marker_size=5,hovertemplate='股價 %{y:,.2f}<extra></extra>'),secondary_y=True)
    graph_height=max(160,int(height*.48))
    fig.update_layout(template='plotly_dark',paper_bgcolor='#101823',plot_bgcolor='#101823',height=graph_height,
        margin=dict(l=56,r=58,t=36,b=30),barmode='relative' if kind=='institution' else 'group',bargap=.25,
        font=dict(family='Microsoft JhengHei,Segoe UI,sans-serif',size=13,color='#bac9dc'),
        legend=dict(orientation='h',y=1.18,x=0,font_size=13),hovermode='x unified',hoverlabel_font_size=14)
    fig.update_xaxes(tickvals=x,ticktext=labels,showgrid=False,tickfont_size=12)
    fig.update_yaxes(title_text=unit,secondary_y=False,gridcolor='#253241',zerolinecolor='#9aa9b8',nticks=5)
    fig.update_yaxes(title_text='股價',secondary_y=True,showgrid=False,nticks=5)
    def value(v,signed=False,key=''):
        if v is None:return '—'
        if key=='ratio':return f'{v:,.2f}'                       # 券資比（%）保留兩位
        n=round(v)
        return (f'{n:+,}' if n else '0') if signed else f'{n:,}'   # 張數取整數，不顯示零股
    heads='<th>日期</th>'+''.join('<th>'+label+'</th>' for key,label in fields)+'<th>股價</th>'
    body=''
    for row in reversed(rows):
        body+='<tr><td>'+row['date'][5:]+'</td>'
        for key,label in fields:
            v=row.get(key);signed=key in ('foreign','trust','dealer','total','fin_change','short_change')
            color=('#f37373' if v>0 else '#55c8a4' if v<0 else '#c2cede') if signed and v is not None else '#c2cede'
            body+=f'<td style="color:{color}">{value(v,signed,key)}</td>'
        body+='<td style="color:#edbf53">'+(f"{row['price']:,.2f}" if row.get('price') is not None else '—')+'</td></tr>'
    n=sum(r['available'] for r in rows);last=next((r['date'] for r in reversed(rows) if r['available']),'尚未取得')
    caption=f'盤後資料 · 最新可用 {last} · {n}/{len(rows)} 日有資料 · 單位：{unit}／股價元'
    notes='空白為未發布、未列此股或來源失敗，不視為零。' + ('券資比＝融券餘額÷融資餘額；融資餘額為零時不計算。' if mode=='券資比' else '')
    payload=json.dumps(json.loads(fig.to_json())).replace('</','<\\/')
    return '''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;background:#101823;color:#c2cede;font:15px 'Microsoft JhengHei','Segoe UI',sans-serif}.shell{height:100vh;border:1px solid #344150;border-radius:12px;overflow:hidden;display:flex;flex-direction:column}.caption{padding:10px 14px;color:#c6b17c;font-size:13px;border-bottom:1px solid #293746}.chart{flex:none}.table{flex:1;overflow:auto;min-height:80px}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th{position:sticky;top:0;background:#1b2734;color:#aebfd3;font-size:13px;z-index:2}td,th{padding:10px 9px;text-align:right;white-space:nowrap;border-bottom:1px solid #293746}td:first-child,th:first-child{text-align:left}tr:first-child td{background:#1a2631;font-weight:650}tbody tr:hover{background:#202d3c}.note{font-size:12px;padding:8px 12px;color:#99adc5;border-top:1px solid #293746}@media(max-height:520px){td,th{padding:7px 8px}.caption{padding:7px 12px}}
</style><script>'''+plotly_bundle()+'''</script></head><body><div class="shell"><div class="caption">'''+caption+'''</div><div id="chip-graph" class="chart"></div><div class="table"><table><thead><tr>'''+heads+'''</tr></thead><tbody>'''+body+'''</tbody></table></div><div class="note">'''+notes+'''</div></div><script>const f='''+payload+''';Plotly.newPlot('chip-graph',f.data,f.layout,{responsive:true,displayModeBar:false,displaylogo:false});</script></body></html>'''


@st.fragment
def render_chip_trends(code,name,ticker,market,kind,quote,workspace):
    title,count_col,mode_col=st.columns([2.8,1,1.4])
    with title:st.markdown(f'<div class="stock-head"><h2>{escape(name)}</h2><span class="stock-code">{code}</span></div>',unsafe_allow_html=True)
    with count_col:count=st.selectbox('近期交易日',[5,10,20],index=1,key='chip_days11',format_func=lambda n:f'近 {n} 日',label_visibility='collapsed')
    choices=['全部','外資','投信','自營商'] if kind=='institution' else ['每日增減','餘額','券資比']
    with mode_col:mode=st.selectbox('籌碼顯示',choices,key='chip_mode11_'+kind,label_visibility='collapsed')
    if quote:
        price=quote['price'];delta=price-quote['reference'];pct=delta/quote['reference']*100
        st.markdown(f'<div class="price-line"><span class="last-price">{price:,.2f}</span><span class="{"up" if delta>0 else "down"}">{delta:+,.2f} ({pct:+.2f}%)</span><span class="price-details">{market} · {"法人買賣超" if kind=="institution" else "融資融券"} · 盤後資料</span></div>',unsafe_allow_html=True)
    else:st.markdown('<div class="price-line"><span class="price-details">盤後籌碼 · 各日資料獨立核對</span></div>',unsafe_allow_html=True)
    target=expected_session()
    if target is None:st.warning('交易日曆待確認');return
    with st.spinner('讀取近期籌碼與對應股價…'):
        try:rows,errors=stock_chip_history(code,ticker,market,kind,target,count)
        except Exception as exc:st.warning(f'籌碼歷史暫不可用：{exc}');return
    components.html(chip_trend_html(rows,kind,mode,max(300,workspace-110)),height=max(300,workspace-110),scrolling=False)
    message='；'.join(errors) if errors else '所選日期資料已齊全'
    st.markdown(f'<div class="note-line" title="{escape(message)}">來源：{"證交所" if market=="上市" else "櫃買中心"} · 逐日核對 · {escape(message)}</div>',unsafe_allow_html=True)

def indicators(frame):
    frame = frame.copy()
    for n in (3, 10, 21, 52):
        frame[f"MA{n}"] = frame["Close"].rolling(n).mean()
    for n in (5, 13, 34):
        frame[f"VMA{n}"] = frame["Volume"].rolling(n).mean()
    return frame


def section(number, title, note="", cls=""):
    st.markdown(f'<div class="section {cls}"><div class="section-title"><span class="section-number">{number}</span>{escape(title)}</div><span class="section-note">{escape(note)}</span></div>', unsafe_allow_html=True)


def ranking_grid(frame, key, height, chosen_column):
    frame=frame.copy()
    frame["Momentum"]=frame["動能(%)"].map(momentum_score)
    builder = GridOptionsBuilder.from_dataframe(frame)
    builder.configure_default_column(resizable=True, sortable=True, filter=False, suppressMovable=True,suppressHeaderMenuButton=True,suppressHeaderFilterButton=True)
    builder.configure_selection("single", use_checkbox=False, pre_selected_rows=[0])
    builder.configure_grid_options(rowHeight=42, headerHeight=52, suppressCellFocus=True,
                                   animateRows=False, suppressRowClickSelection=False,
                                   onGridSizeChanged=JsCode("function(p){p.api.sizeColumnsToFit();}"))
    builder.configure_column("資料日",hide=True)
    builder.configure_column("漲幅(%)",headerName="當日漲幅%",headerTooltip="僅資料日期當天的漲跌幅，不受 RS 比較期影響",width=96,minWidth=78,maxWidth=110,wrapHeaderText=True,type=["numericColumn"],valueFormatter=JsCode("function(p){return Number(p.value).toFixed(2);}"))
    if "覆蓋" in frame:builder.configure_column("覆蓋",hide=True)
    if "成交值(億)" in frame:
        builder.configure_column("成交值(億)",headerName="成交值(億)",headerTooltip="族群成分股今日成交值加總（價格×成交股數，億元）。相對強勢要有量才是真金白銀",
            width=96,minWidth=80,maxWidth=110,type=["numericColumn"],
            valueFormatter=JsCode("function(p){return p.value==null?'—':Number(p.value).toLocaleString('en-US',{maximumFractionDigits:p.value>=100?0:1});}"),
            cellStyle=JsCode("function(p){return {color:p.value>=100?'#f2c14e':p.value>=20?'#dbe2ec':'#7a8a9e',fontVariantNumeric:'tabular-nums'};}"))
    if "股期商品" in frame:builder.configure_column("股期商品",hide=True)
    if "相對狀態" in frame:builder.configure_column("相對狀態",hide=True)
    builder.configure_column("趨勢", hide=True, width=65, minWidth=62, maxWidth=72,
        cellStyle=JsCode("function(p){return {color:p.value==='強勢'?'#f17c7e':'#55c8a4',fontSize:'14px'};}"))
    builder.configure_column("動能(%)", headerName="相較大盤動能%" if "族群板塊" in frame else "相較族群動能%",headerTooltip="依所選 5／10／20 個交易日計算 RS；正值跑贏，負值落後",width=112, minWidth=92, maxWidth=140,wrapHeaderText=True, type=["numericColumn"],
        valueFormatter=JsCode("function(p){return (p.value>0?'+':'')+Number(p.value).toFixed(2);}"),
        cellStyle=JsCode("function(p){return {color:p.value>0?'#f17c7e':'#55c8a4',fontWeight:'600',fontVariantNumeric:'tabular-nums'};}"))
    for hidden in ("_sector","_ticker"):
        if hidden in frame:builder.configure_column(hidden,hide=True)
    if "訊號" in frame:
        for col in ("訊號","整理","入選"):
            builder.configure_column(col,width=58,minWidth=52,maxWidth=66,type=["numericColumn"],
                cellStyle=JsCode("function(p){return {color:p.value>0?'"+("#f17c7e" if col=="訊號" else "#efc979" if col=="整理" else "#c2cede")+"':'#5d6b7d',fontWeight:'600'};}"))
    if "狀態" in frame:
        builder.configure_column("狀態",width=120,minWidth=96,maxWidth=150,tooltipField="狀態",
            cellStyle=JsCode("function(p){const m={'轉折訊號':'#ff9ea1','量縮整理':'#efc979','趨勢・無型態':'#a9b6c9'};return {color:m[p.value]||'#66778c',fontSize:'17px',fontWeight:p.value==='轉折訊號'?'700':'400'};}"))
    if "類別" in frame:
        if "板塊" in frame:builder.configure_column("板塊",width=104,minWidth=88,maxWidth=150,tooltipField="板塊",cellStyle=JsCode("function(p){return {color:'#d9c58e',fontSize:'17px'};}"))
        builder.configure_column("類別",width=66,minWidth=60,maxWidth=72,headerTooltip="股票＝現股前三強；股期＝有股票期貨者前三強；股＋期＝兩邊都入選",cellStyle=JsCode("function(p){return {color:p.value==='股票'?'#9fb3c8':'#e2c47c',fontWeight:p.value==='股票'?'400':'700',fontSize:'17px'};}"))
        builder.configure_column("屬性",hide=True)
    if "族群板塊" in frame:
        builder.configure_column("族群板塊", width=190, minWidth=130,maxWidth=260,tooltipField="族群板塊")
    else:
        builder.configure_column("趨勢", hide=True)
        builder.configure_column("代號", width=70, minWidth=68,maxWidth=80)
        builder.configure_column("名稱", width=100, minWidth=82,maxWidth=130,tooltipField="相對狀態")
        if "類別" not in frame:builder.configure_column("屬性", width=60, minWidth=58, maxWidth=64, tooltipField="股期商品",cellStyle=JsCode("function(p){return {color:p.value==='股期'?'#e2c47c':'#8895a7',fontWeight:p.value==='股期'?'700':'400'};}"))
    battery=JsCode("""class Battery {init(p){const v=Number(p.value);this.e=document.createElement('div');this.e.style.cssText='display:flex;align-items:center;gap:6px;height:100%;font-size:12px';if(p.value==null){this.e.textContent='—';return;}this.e.title='RS '+Number(p.data['動能(%)']).toFixed(2)+'%；相對強度 '+v+'/100，50為中性，非勝率';const b=document.createElement('div');b.style.cssText='display:flex;gap:2px;border:1px solid #718095;border-radius:4px;padding:3px;flex:1;height:20px;min-width:48px';const color=v>50?'#efbd67':v<50?'#4fb7ad':'#8798ad';for(let i=0;i<10;i++){const c=document.createElement('i');c.style.cssText='flex:1;border-radius:1px;background:'+(i<Math.round(v/10)?color:'#263340');b.appendChild(c);}const n=document.createElement('span');n.style.cssText='width:23px;color:'+color;n.textContent=v;this.e.append(b,n);}getGui(){return this.e;}}""")
    builder.configure_column('Momentum',headerName='Momentum',headerTooltip='RS換算相對多方強度：0～100，50為中性；非勝率、不代表股價一定上漲',minWidth=112,width=130,flex=1,cellRenderer=battery,hide="類別" in frame or "訊號" in frame)
    if st.session_state.get("_mobile"):
        height=min(height,52+42*len(frame)+6)   # 筆數少時表格不留大片空白
        # 手機：只留最重要的欄位，避免表格左右捲動
        drop=["Momentum","覆蓋","屬性"]+(["漲幅(%)","入選","代號","成交值(億)"] if ("訊號" in frame or "狀態" in frame) else [])
        for col in drop:
            if col in frame:builder.configure_column(col,hide=True)
        builder.configure_column("動能(%)",headerName="RS%",width=78,minWidth=70,maxWidth=90,wrapHeaderText=False)
        if "名稱" in frame:builder.configure_column("名稱",minWidth=72,flex=1)
        if "類別" in frame:builder.configure_column("類別",width=72,minWidth=70,maxWidth=76)
        if "狀態" in frame:builder.configure_column("狀態",width=124,minWidth=118,maxWidth=130)
    response = AgGrid(frame, gridOptions=builder.build(), height=height, theme="alpine",
        update_on=["selectionChanged"], fit_columns_on_grid_load=True, key=f"{key}_{height}",
        allow_unsafe_jscode=True, custom_css={
            ".ag-cell,.ag-header-cell": {"padding-left":"6px !important","padding-right":"6px !important"},
            ".ag-root-wrapper": {"background-color":"#0f1620 !important", "border":"1px solid #293442 !important", "border-radius":"10px !important"},
            ".ag-header": {"background-color":"#18212d !important", "color":"#c3cedc !important", "font-size":"16px !important", "border-bottom":"1px solid #2c3746 !important"},
            ".ag-header-cell-text": {"font-weight":"600 !important"},
            ".ag-row": {"background-color":"#101721 !important", "color":"#dbe2ec !important", "font-size":"19px !important", "border-bottom":"1px solid #1c2633 !important"},
            ".ag-row-odd": {"background-color":"#121b26 !important"},
            ".ag-row-hover": {"background-color":"#202b37 !important"},
            ".ag-row-selected": {"background-color":"#2a2b24 !important", "border-left":"3px solid #cfb679 !important"},
            ".ag-body-viewport": {"background-color":"#101721 !important"},
            ".ag-body-horizontal-scroll-viewport": {"background-color":"#101721 !important"},
        })
    rows = response.get("selected_rows")
    if rows is not None and len(rows):
        choice = rows.iloc[0][chosen_column] if isinstance(rows, pd.DataFrame) else rows[0][chosen_column]
        if choice in frame[chosen_column].values:
            return choice
    return frame.iloc[0][chosen_column]


@st.cache_resource
def plotly_bundle():
    # 內嵌 JS，不依賴 CDN，也不需要新增 Streamlit 事件套件。
    return get_plotlyjs()


@st.cache_data(ttl=300,show_spinner=False,max_entries=32)
def chart_html(frame, ticker, interval, height=600, marks=(), levels=()):
    """marks：((日期, 'v3'|'v2', 停損), ...) 歷史訊號標記；levels：((價格, 標籤, 顏色), ...) 水平參考線。只用在日 K。"""
    df = indicators(frame)
    labels = df.index.strftime("%Y-%m-%d %H:%M" if interval.endswith("m") else "%Y-%m-%d").tolist()
    x = list(range(len(df)))  # 連續交易棒座標，週末與休市不佔空間
    colors = ["#eed393", "#acbed5", "#86b7ee", "#b48a64"]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=.045, row_heights=[.76,.24])
    fig.add_trace(go.Candlestick(x=x, open=df.Open.tolist(), high=df.High.tolist(), low=df.Low.tolist(), close=df.Close.tolist(),
        name="K線", increasing=dict(line=dict(color="#f17c7e",width=1),fillcolor="#f17c7e"),
        decreasing=dict(line=dict(color="#55c8a4",width=1),fillcolor="#55c8a4"),
        text=labels, hoverinfo="text+name"),row=1,col=1)
    for n, color in zip((3,10,21,52), colors):
        fig.add_trace(go.Scatter(x=x,y=df[f"MA{n}"].tolist(),name=f"MA{n}",line=dict(color=color,width=1.5),
            hovertemplate=f"MA{n} %{{y:.2f}}<extra></extra>"),row=1,col=1)
    fig.add_trace(go.Bar(x=x,y=df.Volume.tolist(),name="成交量",marker_color=["#f17c7e" if c>o else "#55c8a4" for c,o in zip(df.Close,df.Open)],opacity=.65,
        hovertemplate="成交量 %{y:,.0f}<extra></extra>"),row=2,col=1)
    for n,color in zip((5,13,34),colors):
        fig.add_trace(go.Scatter(x=x,y=df[f"VMA{n}"].tolist(),name=f"VMA{n}",line=dict(color=color,width=1,dash="dot"),
            hovertemplate=f"VMA{n} %{{y:,.0f}}<extra></extra>"),row=2,col=1)
    # 訊號標記與參考線一定加在最後：圖內 JS 以序號 1～8 對應均線／均量（自動 Y 軸用）
    if interval=="1d" and marks:
        pos={d:i for i,d in enumerate(labels)}
        for kind,color,name in (("v3","#f2c14e","v3 波段量啟動"),("v2","#5fd0ff","v2 凹洞量轉折")):
            pts=[(pos[d],float(df.Low.iloc[pos[d]])) for d,k,_ in marks if k==kind and d in pos]
            if pts:
                fig.add_trace(go.Scatter(x=[p for p,_ in pts],y=[lo*0.985 for _,lo in pts],mode="markers",name=name,
                    marker=dict(symbol="triangle-up",size=13,color=color,line=dict(color="#0f1620",width=1)),
                    hovertemplate=name+"<extra></extra>"),row=1,col=1)
    if interval=="1d":
        for price,label,color in levels:
            if price and math.isfinite(price):
                fig.add_hline(y=price,line=dict(color=color,width=1.2,dash="dash"),annotation_text=label,annotation_position="top left",
                              annotation_font=dict(color=color,size=13),row=1,col=1)
    # 下一根新增時會移出的第 -N 根：均價取收盤價，均量取成交量。
    for row, periods, column, prefix in [(1,(3,10,21,52),"Close","MA"),(2,(5,13,34),"Volume","VMA")]:
        for i,(n,color) in enumerate(zip(periods,colors)):
            if len(df)>=n:
                fig.add_annotation(x=len(df)-n,y=float(df[column].iloc[-n]),xref="x" if row==1 else "x2",yref="y" if row==1 else "y2",
                    text=f"{prefix}{n}",font=dict(size=13,color=color),showarrow=True,
                    arrowcolor=color,arrowhead=2,arrowwidth=1,ax=-18 if i==0 else 18,ay=-22,
                    bgcolor="#101721",borderpad=3)
    fig.update_yaxes(nticks=5,tickfont=dict(size=16),row=1,col=1)
    fig.update_yaxes(nticks=3,tickfont=dict(size=15),row=2,col=1)
    fig.update_layout(template="plotly_dark",paper_bgcolor="#0f1620",plot_bgcolor="#0f1620",
        height=height,margin=dict(l=14,r=96,t=36,b=36),dragmode="pan",hovermode=False,
        hoverlabel=dict(bgcolor="#1b2532",font_size=12),font=dict(family="Segoe UI, Microsoft JhengHei, sans-serif",size=16,color="#bdc9da"),
        showlegend=True,legend=dict(orientation="h",x=0,y=1.04,font=dict(size=14),bgcolor="rgba(0,0,0,0)"),
        yaxis=dict(side="right",fixedrange=True,gridcolor="#202a38",zeroline=False,tickformat=",.2f"),
        yaxis2=dict(side="right",fixedrange=True,gridcolor="#202a38",zeroline=False,tickformat=".3s"))
    fig.update_xaxes(type="linear",rangeslider_visible=False,showgrid=True,gridcolor="#202a38",zeroline=False,showspikes=False,
                     spikemode="across",spikesnap="cursor",spikecolor="#66768d",spikethickness=1,tickangle=0)
    fig.update_xaxes(matches="x2",row=1,col=1)
    fig.update_xaxes(matches=None,row=2,col=1)
    payload = json.loads(fig.to_json())
    def values(series):
        return [None if pd.isna(v) else float(v) for v in series]
    meta = {"labels":labels,"open":values(df.Open),"high":values(df.High),"low":values(df.Low),"close":values(df.Close),
            "volume":values(df.Volume),"priceLines":[values(df[f"MA{n}"]) for n in (3,10,21,52)],
            "volumeLines":[values(df[f"VMA{n}"]) for n in (5,13,34)],"key":f"cq-viewport-v2-{ticker}-{interval}","height":height,"timeframe":interval}
    template = CHART_TEMPLATE.replace("__PLOTLY__",plotly_bundle()).replace("__FIGURE__",json.dumps(payload).replace("</","<\\/"))
    return template.replace("__META__",json.dumps(meta).replace("</","<\\/"))


CHART_TEMPLATE = r'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;background:#0f1620;color:#cbd6e5;font:12px "Segoe UI","Microsoft JhengHei",sans-serif}
.shell{border:1px solid #293442;border-radius:12px;overflow:hidden}.toolbar{display:flex;align-items:center;gap:5px;flex-wrap:wrap;padding:10px 12px;border-bottom:1px solid #25303e;background:#121c28}
#timeframe{background:#1a2633;color:#e7ce97;border:1px solid #65593f;border-radius:5px;padding:5px;font:inherit;max-width:80px}button{background:transparent;color:#9aaabd;border:1px solid transparent;border-radius:5px;padding:6px 9px;font:inherit;cursor:pointer}button:hover{background:#243144;color:#f0dba2}button.active{background:#353024;color:#ead29a;border-color:#67583b}button:focus-visible{outline:2px solid #d6bd80}.sep{height:18px;width:1px;background:#334051;margin:0 4px}.spacer{flex:1}.label{font-size:10px;color:#71829a;letter-spacing:1px}.ohlc{padding:10px 14px 0;min-height:30px;color:#a1afc1;font:11px monospace;line-height:1.5}.hint{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;padding:8px 13px;border-top:1px solid #25303e;color:#7e8fa6;font-size:10px}#chart{width:100%}.shell:fullscreen{height:100vh;border:0;border-radius:0;display:flex;flex-direction:column}.shell:fullscreen #chart{flex:1;min-height:0}
body{font-size:14px}.bar-date{padding-top:6px!important}.ohlc{padding-top:3px!important;padding-bottom:6px!important}.ohlc b{font-size:18px!important}#ma-values{padding-bottom:2px!important}.label,.hint{font-size:12px;color:#b2bed0}.toolbar{gap:3px;padding:9px}.toolbar button{padding:7px}.ohlc{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;padding:7px 14px 12px}.ohlc span{display:block;font:12px "Microsoft JhengHei",sans-serif;color:#a9b6c9}.ohlc b{display:block;font:600 19px "Segoe UI",sans-serif;color:#eff3fa;font-variant-numeric:tabular-nums}.bar-date{padding:12px 14px 0;font-size:13px;color:#dcc58c}#ma-values{padding:0 14px 8px;color:#c7b88f;font-size:13px}.chart-wrap{position:relative}.cross,.axis-tag{position:absolute;pointer-events:none;display:none;z-index:20}.vertical{border-left:1px dashed #e5cf9b}.horizontal{border-top:1px dashed #c4b58f;opacity:.7}.axis-tag{background:#e3cb94;color:#101721;border-radius:3px;padding:3px 5px;font:600 12px monospace;white-space:nowrap}.time-tag{font-size:12px}.shell:fullscreen .chart-wrap{flex:1;min-height:0}
body{font-size:16px}.toolbar{flex-wrap:wrap;gap:3px;padding:6px}.toolbar button{padding:5px}.ohlc b{font-size:21px!important}.ohlc span{font-size:14px}.bar-date,#ma-values{font-size:14px}.ohlc>div{min-width:0}.ohlc b{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.axis-tag{font-size:14px}.hint{font-size:12px}
#deduct-values{padding:0 14px 4px;font-size:13px;line-height:20px}#deduct-values .deduct-row{display:flex;flex-wrap:wrap;gap:4px 12px;white-space:nowrap}#deduct-values .deduct-title{color:#b7c5d6;min-width:108px}#deduct-values .deduct-item{font-variant-numeric:tabular-nums}#deduct-values b{font-size:14px}
body{font-size:17px}.label,.hint{font-size:14px!important;color:#b9c5d6}.toolbar button,#timeframe{font-size:16px}.ohlc span{font-size:15px!important}.ohlc b{font-size:23px!important}.bar-date,#ma-values{font-size:15px!important}#deduct-values{font-size:15px;line-height:23px}#deduct-values .deduct-title{min-width:122px}#deduct-values b{font-size:16px}
@media(max-width:600px){body{font-size:15px}.toolbar button,#timeframe{font-size:14px;padding:5px 6px}.ohlc b{font-size:17px!important}.ohlc span{font-size:13px!important}#deduct-values{font-size:13px;line-height:20px}#deduct-values b{font-size:14px}.hint{display:none}#chart .legend{display:none}#ma-values{font-size:13px!important}}
@media(max-width:600px){.ohlc b{font-size:16px}.ohlc{gap:5px}.toolbar button{font-size:12px}}
</style><script>__PLOTLY__</script></head><body><div class="shell" id="shell">
<div class="toolbar"><span class="label">視野</span><button data-bars="30">30 根</button><button data-bars="60">60 根</button><button data-bars="120">120 根</button><button data-bars="all">全部</button><span class="sep"></span><button id="auto" class="active" title="可視 K 棒與均線自動適配價格及成交量軸">自動 Y 軸</button><button id="deduct" class="active" title="標示以最新 K 棒為準、下一根將移出的均價／均量資料">扣抵標示</button><select id="timeframe" aria-label="K線週期" title="切換K線週期"><option value="日K">日K</option><option value="周K">周K</option><option value="月K">月K</option><option value="1分">1分</option><option value="15分">15分</option><option value="30分">30分</option><option value="60分">60分</option></select><span class="spacer"></span><button id="latest" class="active">回到最新</button><button id="reset">重設</button><button id="full">全螢幕</button></div>
<div class="bar-date" id="bar-date"></div><div class="ohlc">
<div><span>開盤</span><b id="v-open"></b></div><div><span>最高</span><b id="v-high"></b></div><div><span>最低</span><b id="v-low"></b></div><div><span>收盤</span><b id="v-close"></b></div><div><span>成交量（張）</span><b id="v-volume"></b></div></div>
<div id="ma-values"></div><div id="deduct-values" aria-label="下一根扣抵值"></div><div class="chart-wrap"><div id="chart"></div><div id="cross-v" class="cross vertical"></div><div id="cross-p" class="cross horizontal"></div><div id="cross-q" class="cross horizontal"></div><div id="tag-p" class="axis-tag"></div><div id="tag-q" class="axis-tag"></div><div id="tag-t" class="axis-tag time-tag"></div></div><div class="hint"><span>上下圖同一根 K 棒 · 橫線標示收盤／成交量 · 滾輪縮放 · 拖曳平移</span><span id="range"></span></div></div>
<script>
const f=__FIGURE__, m=__META__, g=document.getElementById('chart'), N=m.labels.length;
const tf=document.getElementById('timeframe');tf.value=({'1d':'日K','1wk':'周K','1mo':'月K','1m':'1分','15m':'15分','30m':'30分','60m':'60分'})[m.timeframe];tf.onchange=()=>parent.postMessage({type:'cq-timeframe',value:tf.value},'*');
let autoY=true, showDeduct=true, pending=false, raf=0, follow=true;
const baseAnnotations=f.layout.annotations||[];
const initial=[Math.max(-.7,N-Math.min(60,N)-.7),N+1.5];
let current=initial.slice();
try{const v=JSON.parse(localStorage.getItem(m.key));if(v && Array.isArray(v.range) && v.range.every(Number.isFinite)){follow=v.follow!==false;if(follow){const w=v.range[1]-v.range[0];current=[N+1.5-w,N+1.5];}else if(v.last===m.labels[N-1])current=v.range;}}catch(e){}
function clamp(r){const width=Math.max(Math.min(8,N)+1,Math.min(N+2.2,r[1]-r[0]));let a=Math.max(-.7,Math.min(r[0],N+1.5-width));return [a,a+width];}
current=clamp(current);
const fmt=v=>v==null?'—':Number(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
function updateOHLC(i){
 i=Math.max(0,Math.min(N-1,Math.round(i)));
 document.getElementById('bar-date').textContent=m.labels[i]+(i===N-1?' · 資料最後一根':' · 歷史 K 棒');
 for(const k of ['open','high','low','close'])document.getElementById('v-'+k).textContent=fmt(m[k][i]);
 document.getElementById('v-volume').textContent=(Number(m.volume[i])/1000).toLocaleString('en-US',{maximumFractionDigits:1});
 document.getElementById('v-close').style.color=m.close[i]>=m.open[i]?'#f17c7e':'#55c8a4';
 document.getElementById('ma-values').textContent=m.priceLines.map((l,j)=>`MA${[3,10,21,52][j]} ${fmt(l[i])}`).join('    ·    ');
}
function updateDeduct(){
 const box=document.getElementById('deduct-values');
 box.style.display=showDeduct?'block':'none';
 box.innerHTML=[["下根均價扣抵",[3,10,21,52],m.close,1,"MA"],["下根均量扣抵",[5,13,34],m.volume,1000,"VMA"]].map(([title,periods,data,unit,prefix])=>
 '<div class="deduct-row"><span class="deduct-title">'+title+'</span>'+periods.map((n,j)=>{const i=N-n;const value=i>=0?data[i]:null;return '<span class="deduct-item" style="color:'+(prefix==='MA'?['#d6bb7c','#9fb8c7','#86b7ee','#a88e68']:['#d6bb7c','#9fb8c7','#86b7ee'])[j]+'" title="'+(i>=0?m.labels[i]+'：下一根會移出這筆資料':'資料不足')+'">'+prefix+n+' <b>'+(value==null?'—':unit===1000?(value/unit).toLocaleString('en-US',{maximumFractionDigits:1})+' 張':fmt(value))+'</b></span>';}).join('')+'</div>').join('');
}
updateDeduct();
const crossIds=['cross-v','cross-p','cross-q','tag-p','tag-q','tag-t'];
function hideCross(){crossIds.forEach(id=>document.getElementById(id).style.display='none');}
function place(id,x,y,w,h,text){const el=document.getElementById(id);el.style.display='block';el.style.left=x+'px';el.style.top=y+'px';if(w!=null)el.style.width=w+'px';if(h!=null)el.style.height=h+'px';if(text!=null)el.textContent=text;}
function crosshair(e){
 const L=g._fullLayout;if(!L)return;const xa=L.xaxis,ya=L.yaxis,va=L.yaxis2,r=g.getBoundingClientRect();
 const mx=e.clientX-r.left,my=e.clientY-r.top;
 if(mx<xa._offset||mx>xa._offset+xa._length||my<ya._offset||my>va._offset+va._length){hideCross();return;}
 const i=Math.max(0,Math.min(N-1,Math.round(xa.p2d(mx-xa._offset))));
 const px=xa._offset+xa.d2p(i);if(px<xa._offset||px>xa._offset+xa._length){hideCross();return;}
 updateOHLC(i);
 const py=Math.max(ya._offset,Math.min(ya._offset+ya._length,ya._offset+ya.d2p(m.close[i])));
 const vy=Math.max(va._offset,Math.min(va._offset+va._length,va._offset+va.d2p(m.volume[i])));
 place('cross-v',px,ya._offset,0,va._offset+va._length-ya._offset);
 place('cross-p',xa._offset,py,xa._length,0);place('cross-q',xa._offset,vy,xa._length,0);
 place('tag-p',xa._offset+xa._length+4,py-12,null,null,fmt(m.close[i]));
 place('tag-q',xa._offset+xa._length+4,vy-12,null,null,Number(m.volume[i]).toLocaleString('en-US'));
 place('tag-t',Math.max(xa._offset,Math.min(px-75,xa._offset+xa._length-155)),va._offset+va._length+5,null,null,m.labels[i]);
}
function rangePatch(r){
 const a=Math.max(0,Math.ceil(r[0])), b=Math.min(N-1,Math.floor(r[1]));
 const step=Math.max(1,Math.ceil((b-a+1)/Math.max(3,Math.floor(g.clientWidth/110))));let ticks=[];for(let i=a;i<=b;i+=step)ticks.push(i);
 let p={'xaxis.range':r,'xaxis2.range':r,'xaxis.autorange':false,'xaxis2.autorange':false,'xaxis2.tickvals':ticks,'xaxis2.ticktext':ticks.map(i=>m.labels[i].slice(5))};
 p.annotations=showDeduct?baseAnnotations.filter(x=>x.x>=a&&x.x<=b).map(x=>({...x,text:g._fullLayout.height<240?"":x.text,ay:g._fullLayout.height<240?-10:x.yref==="y"?20:-22})):[];
 if(autoY){let lo=Infinity,hi=-Infinity,vol=0;for(let i=a;i<=b;i++){
  lo=Math.min(lo,m.low[i]);hi=Math.max(hi,m.high[i]);vol=Math.max(vol,m.volume[i]||0);
  m.priceLines.forEach((l,j)=>{if(l[i]!=null&&g.data[j+1].visible!=='legendonly'){lo=Math.min(lo,l[i]);hi=Math.max(hi,l[i]);}});
  m.volumeLines.forEach((l,j)=>{if(l[i]!=null&&g.data[j+2+m.priceLines.length].visible!=='legendonly')vol=Math.max(vol,l[i]);});
 }
 if(Number.isFinite(lo)&&Number.isFinite(hi)){const span=Math.max(hi-lo,Math.abs(hi)*.01,.01);p['yaxis.range']=[lo-span*.09,hi+span*(showDeduct?.24:.09)];p['yaxis.autorange']=false;}
 p['yaxis2.range']=[0,Math.max(vol,1)*(showDeduct?1.65:1.12)];p['yaxis2.autorange']=false;
 }
 document.getElementById('range').textContent=`${m.labels[a]} — ${m.labels[b]}  /  ${b-a+1} 根`;
 return p;
}
function save(){try{localStorage.setItem(m.key,JSON.stringify({range:current,last:m.labels[N-1],follow:current[1]>=N-.5}));}catch(e){}}
function apply(r){hideCross();current=clamp(r);cancelAnimationFrame(raf);raf=requestAnimationFrame(()=>{pending=true;Plotly.relayout(g,rangePatch(current)).then(()=>{pending=false;save();});});}
f.layout.xaxis.range=current;f.layout.xaxis2.range=current;
Plotly.newPlot(g,f.data,f.layout,{responsive:true,scrollZoom:false,displayModeBar:false,doubleClick:false,displaylogo:false}).then(()=>{
 apply(current);updateOHLC(N-1);
 function fitChart(){
  const shell=document.getElementById('shell'), wrap=document.querySelector('.chart-wrap');
  const nonChart=shell.scrollHeight-g.getBoundingClientRect().height;
  const h=Math.max(140,window.innerHeight-nonChart-4);
  if(Math.abs(g._fullLayout.height-h)>2)Plotly.relayout(g,{height:h,showlegend:h>=240,'margin.t':h>=240?36:10}).then(()=>apply(current));
 }
 window.addEventListener('resize',fitChart);window.fitChart=fitChart;setTimeout(fitChart,50);

 g.on('plotly_relayout',e=>{if(pending)return;let r=e['xaxis.range']||e['xaxis2.range'];if(!r && e['xaxis.range[0]']!==undefined)r=[e['xaxis.range[0]'],e['xaxis.range[1]']];if(!r && e['xaxis2.range[0]']!==undefined)r=[e['xaxis2.range[0]'],e['xaxis2.range[1]']];if(r){document.querySelectorAll('[data-bars]').forEach(b=>b.classList.remove('active'));apply(r);}});
 g.addEventListener('mousemove',crosshair);g.addEventListener('mouseleave',()=>{hideCross();updateOHLC(N-1);});
 g.on('plotly_restyle',()=>apply(current));
 g.addEventListener('wheel',e=>{
  const rect=g.getBoundingClientRect(),axis=g._fullLayout.xaxis;const px=e.clientX-rect.left-axis._offset;if(px<0||px>axis._length)return;
  e.preventDefault();const ratio=Math.max(0,Math.min(1,px/axis._length)),span=current[1]-current[0],anchor=current[0]+span*ratio;
  const delta=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?600:1),width=Math.max(Math.min(8,N)+1,Math.min(N+2.2,span*Math.exp(Math.max(-.35,Math.min(.35,delta*.002)))));
  document.querySelectorAll('[data-bars]').forEach(b=>b.classList.remove('active'));apply([anchor-width*ratio,anchor+width*(1-ratio)]);
 },{passive:false});
 g.addEventListener('dblclick',()=>apply(initial));
});
document.querySelectorAll('[data-bars]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-bars]').forEach(x=>x.classList.toggle('active',x===b));const count=b.dataset.bars==='all'?N:Math.min(N,Number(b.dataset.bars));apply([N-count-.7,N+1.5]);});
document.getElementById('latest').onclick=()=>{const w=current[1]-current[0];apply([N+1.5-w,N+1.5]);};
document.getElementById('reset').onclick=()=>{document.querySelectorAll('[data-bars]').forEach(b=>b.classList.toggle('active',b.dataset.bars==='60'));apply(initial);};
document.getElementById('auto').onclick=e=>{autoY=!autoY;e.target.classList.toggle('active',autoY);Plotly.relayout(g,{'yaxis.fixedrange':autoY,'yaxis2.fixedrange':autoY}).then(()=>apply(current));};
document.getElementById('deduct').onclick=e=>{showDeduct=!showDeduct;e.target.classList.toggle('active',showDeduct);updateDeduct();apply(current);setTimeout(()=>window.fitChart&&window.fitChart(),60);};
document.getElementById('full').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.getElementById('shell').requestFullscreen();}catch(e){document.getElementById('full').textContent='請用上方「主圖放大」';}};
document.addEventListener('fullscreenchange',()=>{document.getElementById('full').textContent=document.fullscreenElement?'退出全螢幕':'全螢幕';Plotly.relayout(g,{height:document.fullscreenElement?window.innerHeight-210:m.height});});
</script></body></html>'''


VIEWPORT_HTML = """<!doctype html><html><body><script>
const send=(type,extra={})=>parent.postMessage({isStreamlitMessage:true,type,...extra},'*');
send('streamlit:componentReady',{apiVersion:1});send('streamlit:setFrameHeight',{height:0});
let timer,lastValue="",ready=false;function report(){if(!ready)return;let w,h;try{w=parent.innerWidth;h=parent.innerHeight;}catch(e){w=screen.availWidth;h=screen.availHeight;}const value=JSON.stringify({width:w,height:h});if(value===lastValue)return;lastValue=value;send('streamlit:setComponentValue',{value:{width:w,height:h},dataType:'json'});}
window.addEventListener('message',e=>{if(e.data.type==='streamlit:render'){ready=true;report();}});
try{parent.addEventListener('resize',()=>{clearTimeout(timer);timer=setTimeout(report,180)});}catch(e){}
report();
</script></body></html>"""


@st.cache_resource
def viewport_component():
    path=Path(tempfile.mkdtemp(prefix="chenquant_viewport_"))
    (path/"index.html").write_text(VIEWPORT_HTML,encoding="utf-8")
    return components.declare_component("cq_viewport",path=str(path))


COMPACT_CSS="""<style>
[data-testid="stHeader"],footer,.st-key-dimensions{display:none!important}
.block-container{padding:12px 18px 6px!important;max-width:none!important}
[data-testid="stVerticalBlock"]{gap:8px}
.brand{border:0;padding:0;margin:0;height:48px}.brand-title{font-size:24px}.eyebrow{font-size:10px;letter-spacing:2px}.monogram{width:38px;height:38px}.brand-meta{display:none}
.metric-row{margin:0;gap:8px}.metric{min-height:0;padding:8px 12px;border-radius:8px}.metric-label{font-size:11px}.metric-value{font-size:21px;line-height:1.4}.metric-note{font-size:11px}
.section{height:24px;margin:0;align-items:center}.section-title{font-size:16px}.section-note{font-size:12px}.section-number{display:none}
.stock-head{margin:0;height:40px}.stock-head h2{font-size:25px}.stock-code{font-size:14px}.price-line{margin:0;height:38px;gap:10px;align-items:center;line-height:1}.last-price{font-size:30px;line-height:1}.price-details{font-size:13px}
[data-testid="stSelectbox"] label{display:none}[data-baseweb="select"]>div{min-height:36px}
[data-testid="stButton"] button{min-height:36px;padding:4px 10px}
.stElementContainer:has(.price-line){height:38px!important;min-height:38px!important}.stElementContainer:has(.strip){height:28px!important;min-height:28px!important}.stElementContainer:has(.section){height:24px!important;min-height:24px!important}
.strip{display:flex;gap:16px;align-items:center;justify-content:space-between;height:28px;padding:4px 10px;background:#121d29;border:1px solid #263342;border-radius:5px;font-size:12px;color:#b7c4d5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.strip.ok{border-color:#285748;color:#8dd8ba}.strip.bad{border-color:#976540;color:#ffd19a}
.note-line{height:22px;line-height:22px;color:#91a2b8;font-size:11px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
[data-testid="stCaptionContainer"] p{font-size:12px!important}.footer{margin-top:0;padding:0;border:0;font-size:11px}
@media(max-width:900px){.metric-row{grid-template-columns:repeat(2,1fr)}.brand-title{font-size:20px}}
</style>"""


READABLE_CSS="""<style>
.stElementContainer:has(.metric-row){height:76px!important;min-height:76px!important}
.stElementContainer:has(.stock-head){height:44px!important;min-height:44px!important}
.stElementContainer:has(.brand){height:52px!important;min-height:52px!important}
[data-testid="stPopover"] button,[data-testid="stPopoverButton"],button[aria-haspopup="dialog"]{background:#18212d!important;border:1px solid #344353!important;color:#cbd6e5!important}

[data-baseweb="select"]>div{background:#18212d!important;color:#dce5ef!important;border-color:#344353!important}[data-baseweb="select"] svg{fill:#dce5ef!important}
.brand-title{font-size:28px}.eyebrow{font-size:12px}.brand{height:52px}
.metric{padding:8px 12px;min-width:0}.metric-label{font-size:14px;line-height:1.5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.metric-value{font-size:25px!important;line-height:1.35}.metric-row{height:76px}
.section{height:32px;min-width:0;gap:8px}.section-title{font-size:19px;white-space:nowrap}.section-note{font-size:14px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.stock-head{height:44px;min-width:0}.stock-head h2{font-size:28px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.3}.stock-code{font-size:16px}
.price-line{height:46px;gap:12px;min-width:0}.last-price{font-size:36px;flex-shrink:0}.price-line>span{white-space:nowrap}.price-details{font-size:15px;overflow:hidden;text-overflow:ellipsis}.price-line .up,.price-line .down{font-size:18px}
.strip{height:34px;font-size:14px;gap:12px}.strip>span{min-width:0;overflow:hidden;text-overflow:ellipsis}.strip>span:last-child{flex-shrink:0}
.note-line{height:24px;line-height:24px;font-size:13px}
.stElementContainer:has(.price-line){height:46px!important;min-height:46px!important}.stElementContainer:has(.strip){height:34px!important;min-height:34px!important}.stElementContainer:has(.section){height:32px!important;min-height:32px!important}
[data-testid="stButton"] button p,[data-testid="stPopover"] button p,[data-baseweb="select"]{font-size:17px!important}
[data-testid="stPopoverBody"] [data-testid="stSelectbox"] label{display:block}[data-testid="stPopoverBody"]{max-height:80vh;overflow:auto}
@media(max-width:1000px){.metric-row{height:auto}.metric-label{font-size:13px}.metric-value{font-size:21px!important}.price-details{font-size:13px}}
</style>"""


def signal_candidates(all_sectors,groups,quotes,periods,selected=None,limit=40):
    """量價訊號候選：強勢族群（RS>0）內、強於族群、股價 ≥ 50、今日成交值 ≥ 2 億；依族群強弱、個股強弱排序。"""
    cands=[]
    if all_sectors is None or all_sectors.empty:return cands
    strong=all_sectors[all_sectors["動能(%)"]>0]
    for sec,srs in zip(strong["族群板塊"],strong["動能(%)"]):
        g=groups.get(sec)
        if not g:continue
        for ticker,close in g["members"].items():
            code=ticker.split(".")[0];q=quotes.get(code) or {}
            rs=rs_momentum(close,g["basket"].Close,periods)
            price=q.get("price");vol=q.get("Volume") or 0
            if rs is None or not price:continue
            entry=dict(code=code,ticker=ticker,name=stock_names.get(code,code),sector=sec,sector_rs=float(srs),stock_rs=rs*100,price=price,value=price*vol)
            if code==selected or (price>=50 and price*vol>=2e8 and rs>0):cands.append(entry)
    cands.sort(key=lambda c:(-c["sector_rs"],-c["stock_rs"]))
    top=cands[:limit]
    if selected and selected not in {c["code"] for c in top}:
        top+= [c for c in cands if c["code"]==selected][:1]
    return top


@st.cache_data(ttl=30,show_spinner=False,max_entries=128)
def selected_quote19(code,ticker,mode):
    now=pd.Timestamp(taipei_now())
    try:
        if mode=='全市場盤中快照':
            channel=('otc_' if ticker.endswith('.TWO') else 'tse_')+code+'.tw'
            q=mis_batch([channel]).get(code)
            if not q:raise ValueError('MIS未提供成交價')
        elif mode=='Yahoo 延遲盤中掃描':
            # 選中個股的即時價：先問 MIS（約 5 秒延遲），失敗才查 Yahoo 分鐘棒
            try:
                channel=('otc_' if ticker.endswith('.TWO') else 'tse_')+code+'.tw'
                q=mis_batch([channel]).get(code)
                if q and q['timestamp'].date()==now.date():return q,None
            except Exception:
                pass
            state=yahoo_state16()
            if clock.monotonic()<state['cooldown']:raise ValueError('Yahoo限流冷卻中')
            if not state['lock'].acquire(blocking=False):raise ValueError('Yahoo全市場更新中')
            try:
                f=yahoo_minute_frame(yf.Ticker(ticker).history(period='1d',interval='1m',auto_adjust=False,actions=False,raise_errors=True,timeout=8))
                f=f.loc[(f.index.date==now.date())&(f.index+pd.Timedelta(minutes=1)<=now)].between_time('09:00','13:30')
                if f.empty:raise ValueError('Yahoo尚無今日完成分鐘棒')
                previous=expected_session(now.to_pydatetime().replace(hour=8,minute=0))
                refs,_,_=closing_quotes(previous)
                ref=refs.get(code,{}).get('price')
                if not ref:raise ValueError('尚無正式昨收')
                q=aligned_quote16(code,f,f.index[-1],ref)
            finally:state['lock'].release()
        else:return None,None
        age=(now-q['timestamp']).total_seconds()
        if q['timestamp'].date()!=now.date() or age< -5:raise ValueError('來源報價日期或時間不符')
        return q,None
    except Exception as exc:
        if mode=='Yahoo 延遲盤中掃描' and is_rate_limit16(exc):yahoo_state16()['cooldown']=clock.monotonic()+300
        return None,str(exc)


def quote_label19(quote,mode,now=None):
    now=pd.Timestamp(now or taipei_now())
    if not quote:return '歷史K線 · 無當次盤中成交價'
    from_yahoo=str(quote.get('source','')).startswith('Yahoo')
    source=('Yahoo 1分K' if from_yahoo else '證交所 MIS') if mode=='Yahoo 延遲盤中掃描' else 'MIS' if mode=='全市場盤中快照' else '券商報價檔' if mode=='券商即時報價檔' else '交易所收盤'
    if quote.get('price_kind') and quote['price_kind']!='成交價':source+=f"（{quote['price_kind']}）"
    stamp=quote['timestamp'];age=max(0,(now-stamp).total_seconds())
    if stamp.date()!=now.date():phase='歷史報價'
    elif now.time()>=time(13,30):phase='收盤資料' if mode in ('全市場盤中快照','全市場收盤') else '盤後最後報價'
    elif now.time()<time(9):phase='盤前資料'
    elif mode=='Yahoo 延遲盤中掃描' and from_yahoo:phase=f'分鐘快照 · 距今 {age/60:.1f} 分鐘'
    elif age>120:phase=f'保留成交價 · 距今 {age/60:.1f} 分鐘'
    else:phase=f'盤中快照 · 距今 {age:.0f} 秒'
    return f'{source} · {phase} · {stamp:%m/%d %H:%M:%S}'


@st.fragment(run_every='30s')
def render_chart(code,rs,chart_space,quote=None,stock_name=None,ticker=None,rs_period=10,show_head=True,marks=(),levels=()):
    ticker=ticker or f"{code}.TW"
    mode=st.session_state.get('scan_mode16','全市場收盤')
    quote_error=None;now=pd.Timestamp(taipei_now())
    if time(9)<=now.time()<time(13,30) and expected_session(now.to_pydatetime().replace(hour=14))==now.date():
        latest,quote_error=selected_quote19(code,ticker,mode)
        if latest and (not quote or latest['timestamp']>=quote['timestamp']):quote=latest
    if show_head:st.markdown(f'<div class="stock-head"><h2>{escape(stock_name or stock_names.get(code,code))}</h2><span class="stock-code">{escape(code)}</span></div>',unsafe_allow_html=True)
    options={'日K':'1d','周K':'1wk','月K':'1mo','1分':'1m','15分':'15m','30分':'30m','60分':'60m'}
    tf=st.session_state.get('timeframe11','日K')
    period="5d" if tf=="1分" else ("1y" if "分" not in tf else "60d")
    frame,stamp=fetch_chart(ticker,period,options[tf])
    if frame.empty:
        st.error("行情來源目前無可用資料。請更新或切換標的。")
        with st.expander("原因"):st.write(stamp)
        return
    if quote and options[tf]=="1d" and all(k in quote for k in ("Open","High","Low","Volume")):
        stamp_day=quote["timestamp"].normalize()
        if quote["Low"]>0 and quote["Low"]<=min(quote["Open"],quote["price"])<=max(quote["Open"],quote["price"])<=quote["High"]:
            attrs=frame.attrs.copy()
            frame=frame.loc[frame.index<=stamp_day].copy()
            frame.loc[stamp_day,["Open","High","Low","Close","Volume"]]=[quote["Open"],quote["High"],quote["Low"],quote["price"],quote["Volume"]]
            frame.attrs=attrs;frame.attrs.update(last_trade=str(stamp_day.date()),source=attrs.get("source","")+"＋掃描快照")
    last=frame.iloc[-1];change=float(last.Close-frame.Close.iloc[-2]) if len(frame)>1 else 0
    pct=change/float(frame.Close.iloc[-2])*100 if len(frame)>1 and frame.Close.iloc[-2] else 0
    display_price=float(last.Close)
    if quote:
        display_price=quote["price"];change=display_price-quote["reference"];pct=change/quote["reference"]*100
    cls="up" if change>0 else "down" if change<0 else ""
    rs_text=(f"{rs:+.2f}% · "+("相對領先" if rs>1e-10 else "相對落後" if rs< -1e-10 else "同步")) if rs is not None else "未取得"
    st.markdown(f'<div class="price-line"><span class="last-price">{display_price:,.2f}</span><span class="{cls}">{change:+,.2f} ({pct:+.2f}%)</span><span class="price-details">{"最新取得價" if quote else "較前一根 "+tf} · {rs_period}日 RS {rs_text}</span></div>',unsafe_allow_html=True)
    required=expected_session();actual=pd.Timestamp(frame.attrs.get("last_trade",str(frame.index[-1].date()))).date()
    ok=required is not None and actual>=required
    state=f"資料涵蓋 {actual}｜核對交易日 {required}" if ok else f"資料未齊：目前 {actual}｜應有 {required or '日曆待確認'}"
    if quote:state=quote_label19(quote,mode)+f"｜圖表日 {actual}"
    if "分" in tf:state+=f"｜K線截至 {frame.index[-1]:%m/%d %H:%M}"
    if quote_error:state+="｜更新未完成，保留原成交時間"
    st.markdown(f'<div class="strip {"ok" if ok else "bad"}"><span>{escape(state)}</span><span>取得 {escape(stamp.split(" ")[-1])}</span></div>',unsafe_allow_html=True)
    content=chart_html(frame,ticker,options[tf],max(180,chart_space-190),tuple(marks),tuple(levels))
    event=interactive_chart_component()(html=content,height=chart_space,key='chart11_'+ticker,default=None)
    if event and event.get('event')!=st.session_state.get('last_chart_event11'):
        st.session_state.last_chart_event11=event['event']
        if event.get('timeframe') in options and event['timeframe']!=tf:
            st.session_state.timeframe11=event['timeframe'];st.rerun()
    source=frame.attrs.get("source","Yahoo")
    note=f"K線來源：{source} · 未還原價 · 所選個股報價與板塊排名分別更新"
    if len(frame)<52:note+=f" · 僅 {len(frame)} 根，MA52 尚不足"
    st.markdown(f'<div class="note-line" title="{escape(note)}">{escape(note)}</div>',unsafe_allow_html=True)


def yahoo_minute_frame(frame):
    if frame is None or frame.empty:return pd.DataFrame()
    frame=frame.copy()
    idx=pd.DatetimeIndex(frame.index)
    if idx.tz is None:raise ValueError('Yahoo 分鐘時間缺少時區，拒絕猜測')
    frame.index=idx.tz_convert('Asia/Taipei')
    return frame[~frame.index.duplicated(keep='last')].sort_index().dropna(subset=['Close'])


@st.cache_resource
def scan_executor18():
    # Bounded process-wide pool; one outstanding scan per browser session.
    return ThreadPoolExecutor(max_workers=2,thread_name_prefix='cqr-scan')


def async_snapshot18(state,key,loader,force=False):
    now=clock.monotonic()
    jobs=state.setdefault('scan_jobs18',{})
    job=jobs.get('active')
    if job and job['future'].done():
        job_key=job['key']
        try:
            result=job['future'].result()
            if not result.get('quotes') and result['all_sectors'].empty:
                raise ValueError('；'.join(result['missing']) or '沒有有效行情')
            jobs[job_key]={'result':result,'finished':now,'error':None}
            if result.get('yahoo_diagnostic') is not None:
                state['scan_diagnostic16']=result['yahoo_diagnostic']
        except Exception as exc:
            entry=jobs.setdefault(job_key,{})
            entry.update(finished=now,error=str(exc))
            state['scan_diagnostic16']={**state.get('scan_diagnostic16',{}),
                'latest_attempt_error':str(exc),'latest_attempt_at':str(taipei_now())}
        jobs.pop('active',None)
    entry=jobs.get(key,{})
    if 'active' not in jobs and (force or now-entry.get('finished',-1e12)>=300):
        jobs['active']={'key':key,'future':scan_executor18().submit(loader),'started':now}
    result=entry.get('result')
    if result is None:
        result=dict(all_sectors=pd.DataFrame(columns=['趨勢','族群板塊','動能(%)','漲幅(%)','覆蓋','資料日']),
            groups={},missing=[entry['error']] if entry.get('error') else [],valid=0,quotes={},
            market_price=None,asof='尚未取得',stamp='—',source='背景掃描中' if 'active' in jobs else '來源未就緒',effective_label='等待資料')
    return result,bool(entry.get('error')),entry.get('error')


@st.fragment(run_every='2s')
def scan_status18():
    jobs=st.session_state.get('scan_jobs18',{})
    job=jobs.get('active')
    if job:
        if job['future'].done():st.rerun()
        elapsed=int(clock.monotonic()-job['started'])
        if st.session_state.get('cqr_splash_on'):
            st.markdown(f'<div class="cqr-elapsed">已等待 {elapsed} 秒 · 完成後自動進入主畫面</div>',unsafe_allow_html=True)
        else:
            st.caption(f'更新中 · {elapsed} 秒')
    else:
        pass


_VIDEO_DIR=Path(__file__).resolve().parent
SPLASH_VIDEO=next((p for p in (_VIDEO_DIR/"123456_hd.mp4",_VIDEO_DIR/"123456.mp4") if p.exists()),_VIDEO_DIR/"123456.mp4")  # 優先使用 AI 放大的 HD 版


def render_splash():
    """首次載入全市場報價時的全螢幕載入畫面：影片循環播放，掃描完成後由 scan_status18 觸發重繪進入主畫面。"""
    with st.container(key="cqr_splash"):
        if SPLASH_VIDEO.exists():
            st.video(str(SPLASH_VIDEO),loop=True,autoplay=True,muted=True)
        st.markdown('<div class="cqr-scrim"></div><div class="cqr-splash-text"><div class="cqr-eyebrow">CHEN QUANT RESEARCH</div>'
                    '<div class="cqr-title">全市場動能決策臺</div><div class="cqr-sub">正在讀取全市場報價與歷史資料…</div>'
                    '<div class="cqr-bar"><i></i></div></div>',unsafe_allow_html=True)
        if st.button("略過等待",key="cqr_skip"):
            st.session_state['cqr_skip_splash']=True
            st.rerun()


@st.fragment(run_every="300s")
def dashboard(width,height):
    if os.environ.get("CQR_TIMING"):           # 只量時間：設定 CQR_TIMING=輸出檔
        t0=clock.perf_counter()
        try:return _dashboard(width,height)
        finally:
            with open(os.environ["CQR_TIMING"],"a",encoding="utf-8") as fh:
                fh.write(f"{st.session_state.get('module')}\t{st.session_state.get('view11')}\t{st.session_state.get('sig_view')}\t{(clock.perf_counter()-t0)*1000:.0f}\n")
    if not os.environ.get("CQR_PROFILE"):return _dashboard(width,height)
    import cProfile                      # 效能分析：設定環境變數 CQR_PROFILE=輸出資料夾 才會啟用
    prof=cProfile.Profile();t0=clock.perf_counter();prof.enable()
    try:return _dashboard(width,height)
    finally:
        prof.disable()
        out=Path(os.environ["CQR_PROFILE"]);out.mkdir(parents=True,exist_ok=True)
        prof.dump_stats(out/f"run_{clock.time():.0f}_{(clock.perf_counter()-t0)*1000:.0f}ms.prof")


def _dashboard(width,height):
    # 載入畫面要在畫任何東西之前就出現：用佔位元件先送出，掃描完成後再移除。
    splash_ph=st.empty()
    if not st.session_state.get('cqr_first_done') and not st.session_state.get('cqr_skip_splash'):
        st.session_state['cqr_splash_on']=True
        with splash_ph.container():render_splash()
    desktop=width>=1000
    mobile=width<700
    st.session_state["_mobile"]=mobile
    workspace=max(420,height-200) if desktop else 760
    chart_space=max(240,workspace-178)
    rank_height=max(126,int((workspace-138)/2))
    if mobile:  # 手機：上下堆疊，表格固定高度、K 線吃滿一個螢幕
        rank_height=min(330,max(260,int(height*.42)));chart_space=max(460,int(height*.78))
    if mobile:
        # 手機：第一列 品牌＋更新＋設定；第二列 策略模組；第三列 頁籤（下單與登入只在電腦版）
        with st.container(key="m_head"):
            brand_col,refresh,details=st.columns([5,1,1],gap="small",vertical_alignment="center")
        nav_col=st.container(key="m_nav");view=st.container(key="m_view");login=None
    else:
        title,rest=st.columns([.40,.60],gap="medium",vertical_alignment="center")
        if IS_CLOUD:
            with rest:view,refresh,details=st.columns([4.5,1.35,1.75],gap="small",vertical_alignment="center")
            login=None
        else:
            with rest:view,login,refresh,details=st.columns([4.0,1.35,1.2,1.5],gap="small",vertical_alignment="center")
        with title:brand_col,nav_col=st.columns([1.4,1],gap="small",vertical_alignment="center")
    with brand_col:st.markdown('<div class="brand"><div class="brand-left"><div class="monogram">C</div><div><div class="eyebrow">CHEN QUANT RESEARCH</div><div class="brand-title">全市場動能決策臺</div></div></div></div>',unsafe_allow_html=True)
    with nav_col,st.container(key="module_nav"):
        # 策略模組：之後新增的模組加在這個清單即可
        module=st.segmented_control("策略模組",MODULES,default=MODULES[0],key="module",label_visibility="collapsed") or MODULES[0]
    if login is not None:
        with login:huanan_panel.login_control()
    with view:
        if module=="主面板":
            tabs=["K線量能","法人","資券"] if IS_CLOUD or mobile else ["K線量能","法人","資券","帳務資訊"]
            if st.session_state.get("view11") not in [None]+tabs:st.session_state["view11"]="K線量能"
            panel=st.segmented_control("個股資訊",tabs,default="K線量能",key="view11",label_visibility="collapsed") or "K線量能"
        else:
            panel=st.segmented_control("模組頁面",["板塊選股","前瞻紀錄"],default="板塊選股",key="sig_view",label_visibility="collapsed") or "板塊選股"
    force_refresh=False
    with refresh:
        if st.button("↻" if mobile else "↻ 全部更新" if width>=1500 else "↻ 更新",use_container_width=True,help="全部更新"):
            if st.session_state.get('scan_jobs18',{}).get('active'):
                st.toast('已有更新進行中，完成後會顯示結果。')
            else:
                force_refresh=True
                for fn in (chart_history,stock_chip_history,chip_history_reports,chip_report,selected_quote19):fn.clear()
    with details:
        with st.popover("⚙" if mobile else "掃描設定／說明" if width>=1640 else "⚙ 設定",use_container_width=True,help="掃描設定／說明"):
            mode="Yahoo 延遲盤中掃描";st.session_state.scan_mode16=mode
            periods=st.selectbox("相對強弱比較期（交易日）",[5,10,20],index=1,key="period9",help="所有模式皆可選 5／10／20 個交易日。RS 依此期間計算；當日漲幅只看資料日期當天。盤中以目前有效報價作為比較終點。")
            rs_filter=st.selectbox("族群內個股範圍",["全部","只看 RS > 0","只看 RS ≤ 0"],key="rs_scope7",help="全部：保留所有有效成分。RS > 0：跑贏所屬族群。RS ≤ 0：與族群同步或落後族群；不一定是股價下跌。")
            grouping=st.selectbox("族群分類",GROUPING_MODES,index=0,key="grouping9",
                help="產業鏈細分：櫃買中心產業價值鏈，約 280 個族群（例：印刷電路板／硬板、軟板、IC載板製造），一檔可屬多個族群。官方產業別：證交所／櫃買 34 類。回測顯示產業鏈細分選出的強勢族群較準。")
            rising_only=st.checkbox("只看自身漲幅 > 0",value=False,key="rising7",help="觀察拉回時請保持關閉；RS < 0 只代表落後族群，不等於已形成買點。")
            futures_only=st.checkbox("只看有股期",value=False,key="futures7",help="只留下期交所名單中有對應股票期貨的現股。表格與 K 線仍是現股行情，不是期貨成交價。")
            if True:
                max_age=st.selectbox('Yahoo 資料最多落後幾分鐘',[10,20,30],index=2,key='yahoo_age16')*60
                alignment=st.selectbox('個股與大盤最多相差幾分鐘',[1,3,5],index=2,key='yahoo_align16')*60
                st.caption('盤中直接下載Yahoo當日1分K；預設容許落後30分鐘、與大盤差5分鐘。昨收來自正式日線，不再要求前日13:29分鐘棒。盤後此模式仍檢查Yahoo分鐘資料，標示盤後歷史快照，不冒充收盤價。')
            feed_path=""
            st.markdown("先按所選期間比較各板塊與加權指數，再查看板塊內的股票。板塊 RS 正、零、負值都會列出，並由高到低排列。下面的個股條件只影響股票清單，不會改變族群排名。")
            with st.expander("篩選條件：每個選項代表什麼？"):
                st.markdown("- **比較幾個交易日**：所有模式皆可選 5／10／20 個交易日。比較 N 日前的收盤到目前有效報價；盤後則比較到該日正式收盤。需要 N＋1 個交易日的價格，不能用日曆天代替。當日漲幅欄不會跟著變成多日漲幅。\n- **族群內個股範圍**：全部＝不限制個股 RS；RS > 0＝跑贏族群；RS ≤ 0＝與族群同步或落後。負 RS 不等於下跌，也不代表已經出現買點。\n- **只看自身漲幅 > 0**：勾選後只留下股價上漲的股票。要觀察下跌或拉回股票，請取消勾選。\n- **只看有股期**：只留下有對應股票期貨的現股。商品代碼可在下方名單查詢；此處顯示的仍是現股價格。股期名單無法確認時，不會猜測哪些股票有股期。\n- **報價最多可落後幾秒**：只用於盤中報價檢查。選 120 就代表超過兩分鐘的報價不計算，股票與大盤時間差也須在兩分鐘內；正式收盤資料不受此限制。\n- **券商報價 JSON 路徑**：填入執行這個 Web 程式的電腦上，券商行情檔案的完整位置；不是券商網址。\n\n條件會一起生效，例如選 RS ≤ 0 再勾選「只看自身漲幅 > 0」，留下的是『股價有漲，但沒有跑贏族群』的股票。")
            with st.expander("表格數字：動能、漲幅、覆蓋怎麼看？"):
                st.markdown("**相較大盤動能%／相較族群動能%（RS）**是相對表現，不是單純漲幅。族群與加權指數比較；個股與所屬族群比較。正值是跑贏，負值是落後。公式為 [(1＋標的漲幅) ÷ (1＋比較對象漲幅) − 1] × 100，公式中的漲幅用小數表示。\n\n**當日漲幅%**只看資料日期當天。MIS／正式收盤以當日交易所參考價為起點；Yahoo模式以正式前日收盤為起點（除權息日與官方漲幅可能不同）；原15族群使用前一交易日收盤。板塊當日漲幅是符合當日與所選歷史期間資料要求的成分股等權平均。切換比較期可能改變有效成分，但這一欄始終只表示單日漲幅。板塊多日表現則以固定成分股每日等權報酬連乘計算。\n\n**覆蓋**是『當日報價與所選期間歷史均齊全的成分股數／族群全部股數』。例如 18/20，代表 20 檔有 18 檔能參與計算；至少 80% 且至少 3 檔才顯示族群，不滿 3 檔的族群須全部有效。\n\n**進入板塊排名／全市場**是最後通過全部門檻的成分股，不是下載成功數。某板塊不到80%，其資料齊全個股也不計入最終排名數。歷史缺漏會以Yahoo未還原日線依精確日期補齊，每輪有數量與時間上限，限流時保留缺口。**強勢／有效／全產業**依序表示跑贏大盤的族群數、資料足夠的族群數、股票名單中的全部族群數。覆蓋不足代表資料不齊，不等於市場沒有強勢股票。")
            with st.expander("資料更新、掃描範圍與圖表扣抵"):
                st.markdown("**更新方式**：全市場排名每 5 分鐘檢查是否需要背景更新；K線頁所選個股盤中每30秒獨立查詢最新報價，不重跑全市場。切換頁籤沿用上次結果，背景完成後更新畫面。首次開啟個股K線或籌碼仍需載入該股資料。按「全部更新」會立即排入背景更新；已有更新時不重複送出；資料供應端仍可能延遲。歷史收盤會共用快取，首次全市場多日掃描較慢，切換天期可重用已下載的歷史資料。按「全部更新」重查行情及籌碼；歷史依快取到期及缺口補齊，保留名單與已補齊日線，避免重複下載；K線週期可在圖內扣抵標示旁切換。資料日期與來源時間會顯示在畫面上。\n\n**來源失敗**：盤中不會拿昨收冒充即時報價。若本次工作階段已有相同模式、日期與比較期等設定的成功結果，會保留並標示『非即時』；沒有可保留結果就顯示來源未就緒。收盤資料尚未發布時，也不會假裝已取得當日收盤。\n\n**全市場範圍**：官方名單中的上市、上櫃普通股，依官方產業分類分組。不含興櫃、ETF、TDR、權證與特別股。這是成分股等權計算的族群表現，不是官方市值加權產業指數。股票名單快取 6 小時，到期後重查。\n\n**圖表扣抵**：預設開啟。MA3／10／21／52 是均價，VMA5／13／34 是均量；圖上箭頭指出扣抵那根 K 棒，數值列顯示『下一根新增時會移出的收盤價或成交量』。以最新 K 棒為準，不隨滑鼠移到歷史 K 棒而改變；滑鼠停在扣抵數字可看日期。量以張顯示，1 張＝1,000 股。縮放後若扣抵位置在畫面外，數值仍會保留；資料不足顯示 —。\n\n例如：下一根 10 期均價＝目前 10 期均價＋（下一根收盤價−MA10 扣抵價）÷10。均量同理。盤中最後一根尚未收完，當根數值仍會變動。日 K 的一期是一天，週 K 的一期是一週。\n\n圖表與多日排名使用未還原價格，除權息可能影響變化。RS 用來找相對表現，不是自動下單訊號。")
            with st.expander("Momentum 電池怎麼看？"):
                st.markdown("電量以目前所選期間的 RS 換算：50＋50×tanh(RS百分點÷10)，範圍0～100。RS＝0為50；RS越高電量越滿，越低越空。板塊比較大盤，個股比較所屬族群；不隨清單名次或篩選條件改變。這是相對多方強度，不是勝率，也不代表自身股價一定上漲。")
            with st.expander("法人與融資融券怎麼看？"):
                st.markdown("**法人買賣超**＝買進股數−賣出股數，顯示時換算成張；正數是買超，負數是賣超。自營商包含自行買賣與避險。\n\n**融資／融券餘額**是當日尚未償還的部位；增減＝當日餘額−前日餘額。融券買進是回補，現券償還是拿股票歸還，兩者不同。融券不包含借券賣出。\n\n**資料日期**：這是盤後資料，不能當成盤中即時籌碼。法人與資券各自標日期；從最近完成交易日往前逐日查詢；來源尚未發布或讀取失敗的日期保留空白，不往前補值。報表未列個股時顯示缺資料，不填 0，也不擅自認定不能融資融券。\n\n可選近5／10／20個交易日；法人長條為買賣超，資券可切換每日增減／餘額／券資比，金色折線是對應日期的股價。券資比＝融券餘額÷融資餘額；融資為零時顯示空白。籌碼資料不參與目前的 RS 排名或篩選。切換個股會更新右側資訊；頂部「K線量能／法人／資券」可切換查看；五分鐘自動刷新與全部更新也會重查籌碼。")
            catalog,futures_note=load_futures()
            st.caption(futures_note)
            if catalog:
                with st.expander("完整股期標的／商品代碼（含非普通股池標的）"):
                    st.dataframe(pd.DataFrame([{"標的":k,"商品代碼":v} for k,v in catalog.items()]),hide_index=True,height=260)
    universe=pd.DataFrame();quotes={};groups={};missing=[];source="";valid=0
    effective_label=mode;frozen=False;update_error=None
    period=periods
    snapshot_key=repr(("snapshot9",mode,period,grouping,str(taipei_now().date()),feed_path if mode=="券商即時報價檔" else "",max_age if mode in ("全市場盤中快照","券商即時報價檔","Yahoo 延遲盤中掃描") else None,st.session_state.get("yahoo_align16")))
    with st.spinner("讀取行情並套用顯示條件…"):
        try:
            universe=market_universe()
            stock_names.update(dict(zip(universe.code,universe.name)))
            def load_scan():
                local_quotes={};label=mode;yahoo_diag=None
                if force_refresh:
                    for fn in (yahoo_scan16,public_quotes,closing_quotes):fn.clear()
                if mode=="原15族群多日":
                    table,market,stamp,excluded,local_groups=screening_snapshot(period)
                    price=float(market.Close.iloc[-1]) if not market.empty else None
                    date=str(market.index[-1].date()) if not market.empty else "待齊"
                    src=f"原15族群 · {period}日 RS · 日線"
                    count=len({t for g in local_groups.values() for t in g['members']})
                else:
                    day=None
                    if mode=="全市場收盤":
                        day=expected_session()
                        if day is None:raise ValueError("交易日曆待確認")
                        local_quotes,errors,src=closing_quotes(day)
                    elif mode=="Yahoo 延遲盤中掃描":
                        clock_now=taipei_now()
                        live=expected_session(clock_now.replace(hour=14,minute=0,second=0,microsecond=0))==clock_now.date() and time(9)<=clock_now.time()<time(13,30)
                        if live:
                            # 盤中優先用證交所 MIS（延遲約 5 秒、每次 50 檔，全市場約 10～20 秒）；
                            # MIS 取不到或覆蓋不到六成（例如雲端主機被擋）才改用 Yahoo 分鐘資料（延遲約 20 分鐘、逐檔下載較慢）
                            mis_error=None
                            try:
                                local_quotes,errors,src,day,label=session_quote_snapshot(universe,max_age)
                                if len(local_quotes)<0.6*len(universe):raise ValueError(f"MIS 只回傳 {len(local_quotes)} 檔")
                                label="MIS 盤中快照"
                            except Exception as exc:
                                mis_error=str(exc)
                                try:
                                    local_quotes,errors,src,day,label,yahoo_diag=load_yahoo16(universe,max_age,alignment)
                                    errors=[f"MIS 未取得，改用 Yahoo：{mis_error}"]+list(errors)
                                except Exception as yexc:
                                    raise ValueError(f"MIS：{mis_error}；Yahoo：{yexc}")
                        else:local_quotes,errors,src,day,label=session_quote_snapshot(universe,max_age)  # 盤前／盤後／休市：官方收盤，整批取得、不受 Yahoo 限流
                    elif mode=="券商即時報價檔":local_quotes,errors,src=broker_quotes(feed_path,max_age=max_age)
                    else:local_quotes,errors,src,day,label=session_quote_snapshot(universe,max_age)
                    try:
                        table,local_groups,excluded,count=multiday_market_tables(universe,local_quotes,period,max_age=max_age,closing_day=day,grouping=grouping)
                    except Exception as exc:
                        table=pd.DataFrame(columns=["趨勢","族群板塊","動能(%)","漲幅(%)","覆蓋","資料日"])
                        local_groups={};excluded=["RS計算未完成："+str(exc)];count=0
                    excluded.extend(errors)
                    m=local_quotes.get('^TWII');price=m['price'] if m else None
                    date=m['timestamp'].strftime('%m/%d %H:%M') if m else "無有效報價"
                    stamp=taipei_now().strftime('%H:%M:%S')
                return dict(all_sectors=table,groups=local_groups,missing=excluded,valid=count,quotes=local_quotes,
                            market_price=price,asof=date,stamp=stamp,source=src,effective_label=label,yahoo_diagnostic=yahoo_diag)
            scan,frozen,update_error=async_snapshot18(st.session_state,snapshot_key,load_scan,force_refresh)
            all_sectors=scan['all_sectors'];groups=scan['groups'];missing=list(scan['missing']);valid=scan['valid'];quotes=scan['quotes']
            market_price=scan['market_price'];asof=scan['asof'];stamp=scan['stamp'];source=scan['source'];effective_label=scan['effective_label']
            if frozen:
                effective_label="保留結果 · 非即時"
                source=f"更新失敗 · 保留 {stamp} 結果（非即時）"
                missing.append(f"更新失敗：{update_error}")
        except Exception as exc:
            all_sectors=pd.DataFrame(columns=["趨勢","族群板塊","動能(%)","漲幅(%)","覆蓋","資料日"])
            market_price=None;asof="未取得";stamp=taipei_now().strftime('%H:%M:%S');missing=[str(exc)]
            source=mode+" · 來源未就緒";effective_label="來源未就緒"
    first_load=bool(st.session_state.get('scan_jobs18',{}).get('active')) and not quotes
    splash_on=first_load and not st.session_state.get('cqr_skip_splash')
    st.session_state['cqr_splash_on']=splash_on
    scan_status18()
    if splash_on:
        return  # 載入畫面（已在最上方送出）繼續顯示，等 scan_status18 偵測到完成後重繪
    splash_ph.empty()
    st.session_state['cqr_first_done']=True
    periods=period
    sectors=all_sectors.copy()
    strong_count=int((all_sectors['動能(%)']>0).sum())
    total=len(universe) if mode!="原15族群多日" else len({t for a in sector_stocks.values() for t in a})
    nsectors=15 if mode=="原15族群多日" else (len(sector_groups(universe,grouping)) if not universe.empty else 0)
    price_text=f"{market_price:,.2f}" if market_price is not None else "—"
    initial_loading=bool(st.session_state.get('scan_jobs18',{}).get('active')) and not quotes
    rank_text='載入中' if initial_loading else f'{valid:,} / {total:,}'
    sector_text='—' if initial_loading else f'{strong_count} / {len(all_sectors)} / {nsectors}'
    ratio='—' if initial_loading else (f"{valid/total:.1%}" if total else "—")
    cards=[("加權指數 · "+escape(asof),price_text,""),("進入板塊排名 / 全市場",rank_text,"gold"),
           ("強勢 / 有效 / 全族群" if grouping=="產業鏈細分" else "強勢 / 有效 / 全產業",sector_text,""),(escape(effective_label)+" · 排名覆蓋",ratio,"")]
    kpi_html=lambda items:'<div class="metric-row">'+"".join(f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value {cls}">{value}</div></div>' for label,value,cls in items)+'</div>'
    if mobile:st.markdown(kpi_html(cards),unsafe_allow_html=True)   # 手機：2×2
    else:
        kpi_left,kpi_right=st.columns([.40,.60],gap="medium")
        with kpi_left:st.markdown(kpi_html(cards[:2]),unsafe_allow_html=True)
        with kpi_right:st.markdown(kpi_html(cards[2:]),unsafe_allow_html=True)
    warm_chip_reports()
    left,right=st.columns([.40,.60],gap="medium")
    code=None;rs=None;selected=None
    sig_row=None;sig_stamp="—"
    with left:
        strategy=module=="量價訊號"
        if strategy:
            with st.container(key="pick_head"):head_l,head_r=st.columns([1.25,1],gap="small",vertical_alignment="center")
            with head_r:
                focus=st.segmented_control("族群範圍",["偏好族群","全部族群"],default="偏好族群",key="sig_focus",label_visibility="collapsed",
                                           help="偏好族群＝電子、重電、綠能（老師的選股範圍；v3 回測只做這些）") or "偏好族群"
            with head_l:section("","前十強板塊",f"{periods}日 RS · 前五強",cls="lead")
        else:section("","板塊相對強弱",f"{periods}日 RS · 全部板塊",cls="lead")
        if sectors.empty:
            st.info("首次載入中，完成後自動顯示排名。" if st.session_state.get("scan_jobs18",{}).get("active") and not quotes else "尚無可比較板塊：報價、歷史資料或板塊覆蓋率尚未達標。")
            if missing:st.warning(str(missing[0]))
            if mode in ("全市場盤中快照","券商即時報價檔"):st.caption("盤中來源失敗不改用昨收；盤後改讀正式收盤資料。尚無成功結果時，請確認來源或稍後更新。")
        elif strategy:
            pool=sectors[sectors["族群板塊"].map(industry_chain.is_preferred)] if focus=="偏好族群" else sectors
            top,picks=strongest_picks(pool,groups,catalog,quotes,periods,n_sec=10,n=5)
            states={}
            if not picks.empty:
                srs=dict(zip(top["族群板塊"],top["動能(%)"]))
                official=dict(zip(universe.code,universe.sector))
                cands=[dict(code=r["代號"],ticker=r["_ticker"],name=r["名稱"],sector=r["_sector"],official=official.get(r["代號"],""),
                            sector_rs=float(srs[r["_sector"]]),stock_rs=float(r["動能(%)"]))
                       for r in picks.drop_duplicates("代號").to_dict("records")]
                with st.spinner("計算前十強板塊個股的日線量價狀態…"):
                    try:states,sig_stamp=xiao_panel.scan_states(cands)
                    except Exception as exc:missing.append(f"量價狀態暫不可用：{exc}")
                picks["狀態"]=picks["代號"].map(lambda c:xiao_panel.state_label(states.get(c)))
            count=lambda s,k:int(sum(1 for c in set(picks.loc[picks["_sector"]==s,"代號"]) if (states.get(c) or {}).get("state")==k)) if not picks.empty else 0
            sec_tbl=top[[c for c in ("趨勢","族群板塊","動能(%)","漲幅(%)","成交值(億)","資料日") if c in top]].copy()
            sec_tbl["入選"]=[int((picks["_sector"]==s).sum()) if not picks.empty else 0 for s in sec_tbl["族群板塊"]]
            sec_tbl["訊號"]=[count(s,"signal3")+count(s,"signal") for s in sec_tbl["族群板塊"]]
            sec_tbl["整理"]=[count(s,"setup") for s in sec_tbl["族群板塊"]]
            selected=ranking_grid(sec_tbl.reset_index(drop=True),f"sig_sectors_{mode}_{periods}",rank_height,"族群板塊")
            section("","前五強股票 ／ 股期",f"{selected} · 強於族群 · 股價≥50 · 成交值≥2億")
            sub=picks[picks["_sector"]==selected].drop(columns=["板塊"]) if not picks.empty else picks
            if sub.empty:
                st.info("此板塊沒有可交易的強勢個股（強於族群、股價≥50、今日成交值≥2億）。")
            else:
                code=ranking_grid(sub.reset_index(drop=True),f"sig_stocks_{mode}_{selected}_{periods}",rank_height,"代號")
                rs=float(sub.loc[sub['代號']==code,'動能(%)'].iloc[0])
                sig_row=states.get(code)
        else:
            selected=ranking_grid(sectors,f"sectors9_{mode}_{periods}",rank_height,"族群板塊")
            section("","族群成分股",selected)
            stocks=leader_table(groups[selected],catalog,periods,rising_only,futures_only,rs_filter)
            if stocks.empty:
                if futures_only and catalog is None:st.warning("股期名單待核對，暫停股期篩選。")
                else:st.info("此族群無符合顯示條件的個股；可關閉股期／上漲限制，或選擇全部 RS。")
            else:
                code=ranking_grid(stocks,f"stocks9_{mode}_{selected}_{periods}_{rising_only}_{futures_only}_{rs_filter}",rank_height,"代號")
                rs=float(stocks.loc[stocks['代號']==code,'動能(%)'].iloc[0])
        note=f"{source} · 排除 {len(missing)} 筆"
        if not universe.empty:note+=f" · 名單 {roc_date(universe.list_date.min()).date()}"
        st.markdown(f'<div class="note-line" title="{escape("；".join(missing))}">{escape(note)}</div>',unsafe_allow_html=True)
    with right:
        if code:
            row=universe.loc[universe.code==code]
            name=stock_names.get(code,code)
            market=row.iloc[0].market if len(row) else ("上櫃" if any(code+'.TWO' in g['members'] for g in groups.values()) else "上市")
            if panel=="帳務資訊":
                huanan_panel.render_account(workspace)
            elif panel=="前瞻紀錄":
                # 有排程掃描檔就直接讀；沒有（例如雲端）才即時算候選股
                has_scan=(xiao_panel.LOG_DIR/"latest_scan.csv").exists()
                xiao_panel.render_v2([] if has_scan else signal_candidates(all_sectors,groups,quotes,periods,code),code,workspace)
            elif panel=="板塊選股":
                if not IS_CLOUD and not mobile:huanan_panel.render_ticket(code,name)
                else:st.markdown(f'<div class="stock-head"><h2>{escape(name)}</h2><span class="stock-code">{escape(code)}</span></div>',unsafe_allow_html=True)
                xiao_panel.render_status(sig_row,sig_stamp)
                marks=(sig_row or {}).get("marks",())
                stop=(sig_row or {}).get("stop")
                levels=(((float(stop),"停損 "+f"{stop:,.2f}","#ff8a8a"),) if sig_row and sig_row.get("state") in ("signal3","signal","setup") and stop==stop else ())
                render_chart(code,rs,chart_space-(0 if mobile else 92),quote=quotes.get(code),stock_name=name,ticker=row.iloc[0].ticker if len(row) else None,
                             rs_period=periods,show_head=False,marks=marks,levels=levels)
            elif panel=="K線量能":
                if not IS_CLOUD and not mobile:huanan_panel.render_ticket(code,name)
                render_chart(code,rs,chart_space,quote=quotes.get(code),stock_name=name,ticker=row.iloc[0].ticker if len(row) else None,rs_period=periods,show_head=IS_CLOUD or mobile)
            else:
                render_chip_trends(code,name,row.iloc[0].ticker if len(row) else code+'.TW',market,'institution' if panel=='法人' else 'margin',quotes.get(code),workspace-12)

        else:
            st.info("排名不足仍可檢查已取得報價的個股；這不代表該股已通過RS篩選。")
            available=[c for c in quotes if c!='^TWII']
            if available:
                inspect_code=st.selectbox('獨立檢視已收到的個股',available,format_func=lambda c:c+' '+stock_names.get(c,c))
                matched=universe.loc[universe.code==inspect_code]
                render_chart(inspect_code,None,chart_space,quote=quotes[inspect_code],ticker=matched.iloc[0].ticker if len(matched) else None)
            if not universe.empty:
                old={t.split('.')[0] for a in sector_stocks.values() for t in a};active=len(old&set(universe.code))
                st.markdown(f"目前名單 **{len(universe):,} 檔／{universe.sector.nunique()} 產業**。原池 108 檔中，有 {active} 檔符合本次普通股名單，股數覆蓋率 **{active/len(universe):.2%}**。")


SPLASH_CSS="""<style>
.st-key-cqr_splash{position:fixed!important;inset:0;z-index:99990;background:#05070b}
.st-key-cqr_splash [data-testid="stVideo"],.st-key-cqr_splash [data-testid="stElementContainer"]{position:static!important}
.st-key-cqr_splash video{position:fixed!important;inset:0;width:100vw!important;height:100vh!important;max-width:none!important;object-fit:cover;pointer-events:none;background:#05070b}
.st-key-cqr_splash video::-webkit-media-controls,.st-key-cqr_splash video::-webkit-media-controls-enclosure,.st-key-cqr_splash video::-webkit-media-controls-panel{display:none!important}
.cqr-scrim{position:fixed;inset:0;z-index:99991;pointer-events:none;background:linear-gradient(to top,rgba(5,7,11,.94) 0%,rgba(5,7,11,.62) 26%,rgba(5,7,11,0) 56%),radial-gradient(ellipse at center,rgba(5,7,11,0) 55%,rgba(5,7,11,.55) 100%)}
.cqr-splash-text{position:fixed;left:0;right:0;bottom:11vh;z-index:99992;text-align:center;pointer-events:none}
.cqr-eyebrow{letter-spacing:7px;color:#d7bf84;font-size:13px;margin-bottom:8px}
.cqr-title{font-size:clamp(30px,4vw,56px);font-weight:700;color:#f6ecca;letter-spacing:3px;text-shadow:0 2px 24px rgba(0,0,0,.8)}
.cqr-sub{margin-top:10px;color:#cdd6e4;font-size:17px;text-shadow:0 1px 10px rgba(0,0,0,.9)}
.cqr-bar{width:min(440px,60vw);height:3px;margin:20px auto 0;background:rgba(255,255,255,.16);overflow:hidden;border-radius:3px}
.cqr-bar i{display:block;width:38%;height:100%;background:linear-gradient(90deg,transparent,#d7bf84,transparent);animation:cqr-slide 1.7s infinite ease-in-out}
@keyframes cqr-slide{0%{transform:translateX(-120%)}100%{transform:translateX(330%)}}
.cqr-elapsed{position:fixed;left:0;right:0;bottom:6vh;z-index:99992;text-align:center;color:#aebbcd;font-size:14px;text-shadow:0 1px 8px rgba(0,0,0,.9);pointer-events:none}
.st-key-cqr_skip{position:fixed!important;right:28px;bottom:24px;z-index:99993;width:auto!important}
.st-key-cqr_skip button{background:rgba(10,14,20,.55)!important;border:1px solid rgba(215,191,132,.5)!important;color:#e9d9a8!important;backdrop-filter:blur(4px)}
.st-key-cqr_skip button:hover{background:rgba(215,191,132,.22)!important}
.block-container{animation:cqr-fade .55s ease-out}
@keyframes cqr-fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
</style>"""


LAYOUT_CSS="""<style>
.block-container{padding:14px 22px 6px!important}
[data-testid="stHorizontalBlock"]:has(.brand){align-items:center!important}
.stElementContainer:has(.brand){height:56px!important;min-height:56px!important}
.brand{height:56px!important;padding:0!important;margin:0!important;border:0!important;align-items:center}
[data-testid="stHorizontalBlock"]:has(.brand) [data-testid="stButton"] button,[data-testid="stHorizontalBlock"]:has(.brand) [data-testid="stPopover"] button{height:42px!important;min-height:42px!important;padding:0 12px!important}
[data-testid="stHorizontalBlock"]:has(.brand) [data-testid="stButton"] button p,[data-testid="stHorizontalBlock"]:has(.brand) [data-testid="stPopover"] button p{font-size:16px!important}
[data-testid="stHorizontalBlock"]:has(.brand) [data-testid="stButtonGroup"] button{height:40px!important;min-height:40px!important;padding:0 14px!important}
[data-testid="stHorizontalBlock"]:has(.brand) [data-testid="stButtonGroup"] button p{font-size:15px!important}
[data-testid="stMarkdownContainer"]:has(.metric-row),[data-testid="stMarkdownContainer"]:has(.hn-head){margin-bottom:0!important}
.metric-row{display:grid!important;grid-template-columns:1fr 1fr!important;gap:12px!important;height:auto!important;margin:0!important}
.metric{min-height:0!important;height:72px;padding:10px 16px!important;display:flex;flex-direction:column;justify-content:center;border-left:3px solid #35435a!important}
.metric:first-child{border-left-color:#d7bf84!important}
.metric-label{font-size:13px!important;line-height:1.3!important}
.metric-value{font-size:25px!important;line-height:1.3!important}
.stElementContainer:has(.metric-row){height:auto!important;min-height:0!important}
.stElementContainer:has(.note-line){height:22px!important;min-height:22px!important}
.section.lead{height:46px!important}.stElementContainer:has(.section.lead){height:46px!important;min-height:46px!important}
.section{align-items:center!important}
.note-line{height:22px!important;line-height:22px!important;font-size:12px!important;color:#7f8ea3!important;border-top:1px solid #1d2733;margin-top:2px;padding-top:2px}
@media(max-width:1000px){.metric-row{grid-template-columns:repeat(2,minmax(0,1fr))!important}}
.st-key-pick_head [data-testid="stButtonGroup"]{justify-content:flex-end}
.st-key-pick_head [data-testid="stButtonGroup"] button{height:34px!important;min-height:34px!important;padding:0 12px!important}
.st-key-pick_head [data-testid="stButtonGroup"] button p{font-size:15px!important}
.brand-title{white-space:nowrap}
@media(max-width:1480px){.brand-title{font-size:24px!important}.st-key-module_nav [data-testid="stButtonGroup"] button{padding:0 10px!important}}
.st-key-module_nav [data-testid="stButtonGroup"]{justify-content:flex-end}
.st-key-module_nav [data-testid="stButtonGroup"] button{height:40px!important;min-height:40px!important;padding:0 16px!important;border-color:#4a3f27!important}
.st-key-module_nav [data-testid="stButtonGroup"] button p{font-size:15px!important;font-weight:650!important;letter-spacing:1px}
.st-key-module_nav [data-testid="stButtonGroup"] button[aria-checked="true"],.st-key-module_nav [data-testid="stButtonGroup"] button[kind$="Active"]{background:linear-gradient(180deg,#d7bf84,#b99a58)!important;border-color:#d7bf84!important}
.st-key-module_nav [data-testid="stButtonGroup"] button[aria-checked="true"] p,.st-key-module_nav [data-testid="stButtonGroup"] button[kind$="Active"] p{color:#15110a!important}
/* ---- 字級：全面放大小字（最小 14px），維持既有版面高度 ---- */
.eyebrow{font-size:12px!important}
.metric-label{font-size:15px!important;color:#a9b6c8!important}
.metric-value{font-size:28px!important}
.section-title{font-size:21px!important}
.section-note{font-size:15px!important;color:#9aa8bb!important}
.note-line{font-size:14px!important;color:#93a2b6!important}
.price-details{font-size:17px!important;color:#b3c0d1!important}
.strip{font-size:15px!important}
.stock-code{font-size:16px!important}
[data-testid="stHorizontalBlock"]:has(.brand) [data-testid="stButtonGroup"] button p,.st-key-m_view [data-testid="stButtonGroup"] button p{font-size:17px!important}
[data-testid="stHorizontalBlock"]:has(.brand) [data-testid="stButton"] button p,[data-testid="stHorizontalBlock"]:has(.brand) [data-testid="stPopover"] button p{font-size:17px!important}
.st-key-module_nav [data-testid="stButtonGroup"] button p{font-size:17px!important}
[data-testid="stCaptionContainer"] p,[data-testid="stMarkdownContainer"] p,[data-testid="stMarkdownContainer"] li{font-size:16px}
/* ---- 手機版（< 700px）---- */
@media(max-width:700px){
.block-container{padding:10px 12px 16px!important}
.st-key-m_head [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:8px!important}
.st-key-m_head [data-testid="stColumn"]{min-width:0!important;width:auto!important;flex:1 1 0!important}
.st-key-m_head [data-testid="stColumn"]:first-child{flex:5 1 0!important}
.st-key-m_head .stElementContainer:has(.brand),.st-key-m_head .brand{height:48px!important;min-height:48px!important}
.st-key-m_head .monogram{width:38px;height:38px;font-size:21px}
.st-key-m_head .eyebrow{font-size:10px!important;letter-spacing:2px}
.st-key-m_head .brand-title{font-size:21px!important}
.st-key-m_head [data-testid="stButton"] button,.st-key-m_head [data-testid="stPopover"] button{height:44px!important;min-height:44px!important;padding:0!important}
.st-key-m_head [data-testid="stButton"] button p,.st-key-m_head [data-testid="stPopover"] button p{font-size:20px!important}
.st-key-m_nav .stElementContainer,.st-key-m_view .stElementContainer{width:100%!important;max-width:none!important}
.st-key-m_nav [data-testid="stButtonGroup"],.st-key-m_view [data-testid="stButtonGroup"]{display:block!important;width:100%!important;max-width:none!important}
.st-key-m_nav [role="radiogroup"],.st-key-m_view [role="radiogroup"]{display:flex!important;width:100%!important;max-width:none!important;min-width:100%!important;flex-wrap:nowrap!important}
.stElementContainer:has(.price-line){height:auto!important;min-height:0!important;overflow:visible!important}
[data-testid="stMarkdownContainer"]:has(.price-line){margin-bottom:0!important}
.price-line{flex-wrap:wrap!important;row-gap:0!important}.price-details{flex-basis:100%}
.st-key-m_nav [data-testid="stButtonGroup"] button,.st-key-m_view [data-testid="stButtonGroup"] button{flex:1 1 0!important;min-width:0!important;height:44px!important;min-height:44px!important;padding:0 6px!important}
.st-key-module_nav [data-testid="stButtonGroup"]{justify-content:stretch!important}
.metric-row{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:8px!important}
.metric{height:68px!important;padding:8px 12px!important}
.metric-label{font-size:13px!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.metric-value{font-size:22px!important}
.section.lead,.stElementContainer:has(.section.lead){height:40px!important;min-height:40px!important}
.section-title{font-size:19px!important}.section-note{font-size:13px!important}
.stock-head h2{font-size:26px!important}.last-price{font-size:36px!important}.price-details{font-size:14px!important}
.strip{font-size:13px!important}
.note-line{height:auto!important;line-height:1.4!important;white-space:normal!important}
.stElementContainer:has(.note-line){height:auto!important}
.sx-bar{height:auto!important;gap:6px}.sx-top{flex-wrap:wrap}.sx-note{flex-basis:100%;order:3;white-space:normal}.sx-chips{flex-wrap:wrap}
.sig-cards{grid-template-columns:repeat(2,minmax(0,1fr))!important}
.sig-wrap{max-height:none!important}
.chip-grid,.acct-cards{grid-template-columns:repeat(2,minmax(0,1fr))!important}
}
</style>"""


GATE_CSS="""<style>
.st-key-cqr_gate{max-width:420px;margin:16vh auto 0;padding:26px 28px 22px;border:1px solid #2c3746;border-radius:14px;background:linear-gradient(145deg,#141c27,#0d131c);box-shadow:0 24px 60px rgba(0,0,0,.55)}
.st-key-cqr_gate [data-testid="stBaseButton-primaryFormSubmit"] p{color:#15110a!important;font-weight:700;font-size:17px}
.cqr-gate-title{font-size:24px;font-weight:700;color:#f1e6c4;letter-spacing:1px;margin:2px 0 4px}.cqr-gate-sub{color:#8fa0b6;font-size:14px;margin-bottom:10px}
</style>"""


def auth_gate():
    """選用的密碼閘門：在雲端的 Secrets 設定 APP_PASSWORD 才會啟用；沒設定則直接放行（本機使用）。"""
    try:
        expected=str(st.secrets.get("APP_PASSWORD",""))
    except Exception:
        expected=""
    if not expected or st.session_state.get("cqr_authed"):return True
    st.markdown(GATE_CSS,unsafe_allow_html=True)
    with st.container(key="cqr_gate"):
        st.markdown('<div class="cqr-gate-title">全市場動能決策臺</div><div class="cqr-gate-sub">請輸入存取密碼</div>',unsafe_allow_html=True)
        with st.form("cqr_gate_form",border=False):
            entered=st.text_input("密碼",type="password",label_visibility="collapsed",placeholder="密碼")
            submitted=st.form_submit_button("進入",use_container_width=True,type="primary")
        if submitted:
            if hmac.compare_digest(entered.encode("utf-8"),expected.encode("utf-8")):
                st.session_state["cqr_authed"]=True
                st.rerun()
            clock.sleep(1.2)  # 稍微拖慢連續猜測
            st.error("密碼不正確")
    return False


def main():
    st.set_page_config(page_title="CQR｜全市場動能決策臺",page_icon="◈",layout="wide",initial_sidebar_state="collapsed")
    # 各段 CSS 合併為單一 <style>：用 </style><style> 直接相接時，瀏覽器會把中間當成文字，每段的第一條規則都會被吃掉。
    merged="".join(re.sub(r"</?style>","",block) for block in (CSS,COMPACT_CSS,READABLE_CSS,CHIP_CSS,SPLASH_CSS,huanan_panel.CSS,xiao_panel.CSS,LAYOUT_CSS))
    st.markdown(("<style>"+merged+"</style>").replace("\n\n","\n"),unsafe_allow_html=True)
    if not auth_gate():return
    with st.container(key="dimensions"):
        viewport=viewport_component()(key="cq_dimensions",default={"width":1440,"height":900})
    dashboard(int(viewport.get("width",1440)),int(viewport.get("height",900)))


if __name__=="__main__":
    main()