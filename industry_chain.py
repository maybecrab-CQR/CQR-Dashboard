"""櫃買中心「產業價值鏈資訊平台」（ic.tpex.org.tw）產業鏈分類：抓取、快取、轉成族群。
用法：python industry_chain.py        重新抓取並寫入 research/data/industry_chain.csv（建議每月一次）

每條產業鏈（例：半導體）底下有多個細項（例：IC 設計、IC 封裝測試），每個細項列出上市櫃公司。
一檔股票可能出現在多條鏈、多個細項（例：台光電同時屬於 PCB 與 AI 伺服器）。
族群的組成方式見 groups()：細項成分夠多就用細項（名稱「細項｜產業鏈」），太少就併回所屬產業鏈。
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
CACHE = HERE / "industry_chain.csv"          # 放在專案根目錄，雲端上傳包也一併帶上
MAX_AGE_DAYS = 30
BASE = "https://ic.tpex.org.tw/"
UA = {"User-Agent": "Mozilla/5.0"}


def _get(url):
    for k in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            r.encoding = "utf-8"
            return r.text
        except Exception:
            if k == 2:
                raise
            time.sleep(2 * (k + 1))


def chain_ids():
    html = _get(BASE + "index.php")
    return list(dict.fromkeys(re.findall(r"introduce\.php\?ic=([0-9A-Z]{4})", html)))


def parse_chain(ic):
    html = _get(f"{BASE}introduce.php?ic={ic}")
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    title = unescape(m.group(1)).strip() if m else ic
    name = re.split(r"[-|｜]", title)[0].strip() or ic
    name = re.sub(r"^.*>\s*", "", name)                       # 「產業價值鏈資訊平台 > 半導體產業鏈簡介」
    name = re.sub(r"(產業)?產業鏈簡介$|產業鏈簡介$", "", name).strip() or ic
    rows = []
    for seg_id, seg_name, body in re.findall(r'<div id="companyList_([0-9A-Z]+)" title="([^"]*)"[^>]*>(.*?)</table>', html, re.S):
        for code in re.findall(r"stk_code=(\d{4})\b", body):
            rows.append({"chain_id": ic, "chain": name, "seg_id": seg_id, "segment": unescape(seg_name).strip(), "code": code})
    return rows


def fetch():
    ids = chain_ids()
    with ThreadPoolExecutor(max_workers=4) as pool:
        parts = list(pool.map(parse_chain, ids))
    df = pd.DataFrame([r for p in parts for r in p]).drop_duplicates()
    if df.empty or df.chain_id.nunique() < 20:
        raise RuntimeError(f"產業鏈資料異常：只取得 {df.chain_id.nunique() if not df.empty else 0} 條鏈")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CACHE, index=False, encoding="utf-8-sig")
    return df


_MEMO = {}


def load():
    """讀快取；超過 30 天嘗試重抓，抓不到就用舊檔。"""
    if "df" in _MEMO:
        return _MEMO["df"]
    df = None
    if CACHE.exists():
        df = pd.read_csv(CACHE, dtype={"code": str, "seg_id": str, "chain_id": str})
        if time.time() - CACHE.stat().st_mtime > MAX_AGE_DAYS * 86400:
            try:
                df = fetch()
            except Exception:
                pass
    else:
        df = fetch()
    _MEMO["df"] = df
    return df


def short(name):
    """族群顯示名稱：去掉括號說明（例「網路設備(如數據機、網路卡…)」→「網路設備」）。"""
    return re.sub(r"[（(][^)）]*[)）]", "", name).strip()


def is_preferred(group_name, official=None):
    """族群名稱屬於偏好範圍（電子、重電、綠能）：產業鏈名稱或官方產業別任一符合。"""
    from xiao_swing import PREFERRED
    return chain_of(group_name) in PREFERRED_CHAINS or group_name in PREFERRED or (official in PREFERRED if official else False)


# 老師偏好的範圍（電子、重電、綠能）對應到產業鏈
PREFERRED_CHAINS = {"半導體", "印刷電路板", "電腦及週邊設備", "通信網路", "被動元件", "連接器", "平面顯示器", "觸控面板",
                    "LED照明", "人工智慧", "雲端運算", "大數據", "資通訊安全", "軟體服務", "電機機械", "智慧電網", "太陽能",
                    "風力發電", "能源元件", "電動車輛", "自動化", "太空衛星科技", "體驗科技"}


def chain_of(group_name):
    """族群名稱 → 產業鏈。名稱格式為「細項｜產業鏈」或單獨的「產業鏈」。"""
    return group_name.split("｜")[-1]


def groups(universe_codes, min_members=6):
    """回傳 {族群名: [代號...]}。
    細項（例「PCB／銅箔基板」）在名單中有 ≥ min_members 檔就自成一個族群；不足的細項併回所屬產業鏈（例「PCB」）。
    同一族群內代號去重；一檔可屬於多個族群。"""
    codes_in = frozenset(universe_codes)
    key = ("groups", hash(codes_in), min_members)
    if key in _MEMO:
        return _MEMO[key]
    df = load()
    df = df[df.code.isin(codes_in) & (df.chain != "其他")]          # 「其他」是雜項，不當族群
    out = {}
    for (chain, segment), g in df.groupby(["chain", "segment"]):
        codes = sorted(set(g.code))
        key = f"{short(segment)}｜{chain}" if len(codes) >= min_members else chain   # 細項在前：表格截斷時仍看得到
        out.setdefault(key, set()).update(codes)
    res = {k: sorted(v) for k, v in out.items() if len(v) >= 3}
    _MEMO[key] = res
    return res


if __name__ == "__main__":
    d = fetch()
    print(f"產業鏈 {d.chain_id.nunique()} 條、細項 {d.seg_id.nunique()} 個、公司 {d.code.nunique()} 家、對應 {len(d)} 筆")
    print(d.groupby("chain").code.nunique().sort_values(ascending=False).to_string())
