import os
import time
import requests
import pandas as pd
import jdatetime

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# =========================================================
# PATHS
#
# All paths are relative to this file's own location instead of a
# hardcoded Windows path, so the exact same code works locally,
# inside a GitHub Actions runner, and on Streamlit Cloud.
# =========================================================

BASE_FOLDER = os.path.dirname(os.path.abspath(__file__))

DATA_FOLDER = os.path.join(BASE_FOLDER, "data")

MARKET_FILE = os.path.join(
    DATA_FOLDER,
    "MarketWatchPlus-1404_10_22.xlsx"
)

OUTPUT_FOLDER = os.path.join(
    DATA_FOLDER,
    "shareholders"
)


# =========================================================
# SETTINGS
# =========================================================

API_BASE = "https://cdn.tsetmc.com/api"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}

REQUEST_DELAY_SECONDS = 0.7

# ستون‌هایی که تاریخ نیستند
META_COLUMNS = [
    "سهامدار",
    "shareHolderID",
    "shareHolderShareID",
    "insCode",
    "تعداد سهام",
    "تغییر سهام",
]


# =========================================================
# HTTP
# =========================================================

def build_session():
    """
    One Session per run: reuses the TCP/TLS connection across
    every request instead of paying the handshake cost each
    time, and retries transient failures automatically.
    """

    session = requests.Session()

    session.headers.update(HEADERS)

    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
    )

    adapter = HTTPAdapter(max_retries=retries)

    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


def get_json(session, url):

    try:

        response = session.get(
            url,
            timeout=20
        )

        response.raise_for_status()

        return response.json()

    except Exception as e:

        print(f"API Error: {e}")

        return None


# =========================================================
# READ MARKET WATCH
# =========================================================

def read_stock_list():

    if not os.path.exists(MARKET_FILE):

        raise FileNotFoundError(
            f"فایل MarketWatch پیدا نشد:\n{MARKET_FILE}"
        )

    df = pd.read_excel(
        MARKET_FILE
    )

    possible_columns = [
        "نماد",
        "نام نماد",
        "اسم سهم",
        "نام",
        "lVal18AFC",
        "Ticker",
        "Symbol",
    ]

    stock_column = None

    for column in possible_columns:

        if column in df.columns:

            stock_column = column
            break

    if stock_column is None:

        raise ValueError(
            "ستون نام نماد در فایل MarketWatch پیدا نشد.\n"
            f"ستون‌های موجود:\n{list(df.columns)}"
        )

    stocks = (
        df[stock_column]
        .dropna()
        .astype(str)
        .str.strip()
    )

    stocks = stocks[stocks != ""]

    stocks = stocks.drop_duplicates()

    return stocks.tolist()


# =========================================================
# FIND STOCK IN TSETMC
# =========================================================

def find_stock(session, stock_name):

    url = (
        f"{API_BASE}/Instrument/"
        f"GetInstrumentSearch/"
        f"{requests.utils.quote(stock_name)}"
    )

    data = get_json(session, url)

    if not data:

        return None

    if isinstance(data, list):

        results = data

    elif isinstance(data, dict):

        results = (
            data.get("instrumentSearch")
            or data.get("instrument")
            or data.get("data")
            or data.get("items")
            or []
        )

    else:

        results = []

    if not results:

        return None

    for item in results:

        names = [
            str(item.get("lVal18AFC", "")).strip(),
            str(item.get("lVal30", "")).strip(),
            str(item.get("name", "")).strip(),
            str(item.get("symbol", "")).strip(),
        ]

        if stock_name.strip() in names:

            return item

    return results[0]


# =========================================================
# GET SHAREHOLDERS
# =========================================================

def get_shareholders(session, ins_code):

    url = (
        f"{API_BASE}/Shareholder/"
        f"GetInstrumentShareHolderLast/"
        f"{ins_code}"
    )

    data = get_json(session, url)

    if not data:

        return []

    if isinstance(data, list):

        return data

    if isinstance(data, dict):

        return (
            data.get("shareHolder")
            or data.get("shareHolders")
            or data.get("data")
            or []
        )

    return []


# =========================================================
# JALALI DATE
# =========================================================

def get_today_jalali():

    today = jdatetime.date.today()

    return today.strftime("%Y/%m/%d")


# =========================================================
# DATE COLUMNS
# =========================================================

def get_date_columns(df):

    return [
        column
        for column in df.columns
        if column not in META_COLUMNS
    ]


# =========================================================
# UPDATE ONE STOCK FILE
# =========================================================

def update_stock_file(
    stock_name,
    shareholders,
    ins_code
):
    """
    Merges today's shareholder snapshot into the stock's history file.

    The previous version re-filtered old_df (df[df["col"] == name])
    once per shareholder name -> O(n^2) for a file with n rows.
    Here old_df is converted once into a name -> row dict, so each
    lookup is O(1) and the whole merge is O(n).
    """

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    file_path = os.path.join(
        OUTPUT_FOLDER,
        f"{stock_name}.xlsx"
    )

    today = get_today_jalali()

    if os.path.exists(file_path):

        old_df = pd.read_excel(file_path)

    else:

        old_df = pd.DataFrame(columns=META_COLUMNS)

    for column in META_COLUMNS:

        if column not in old_df.columns:

            old_df[column] = None

    date_columns = get_date_columns(old_df)

    # ---------------------------------------------------
    # Build a single O(1)-lookup index instead of filtering
    # the DataFrame once per shareholder name.
    # ---------------------------------------------------

    old_df = old_df.copy()

    old_df["سهامدار"] = (
        old_df["سهامدار"]
        .dropna()
        .astype(str)
    )

    old_lookup = (
        old_df
        .dropna(subset=["سهامدار"])
        .drop_duplicates(subset=["سهامدار"], keep="first")
        .set_index("سهامدار")
        .to_dict("index")
    )

    current_data = {}

    for shareholder in shareholders:

        name = shareholder.get("shareHolderName")

        if not name:

            continue

        name = str(name).strip()

        current_data[name] = {
            "shareHolderID": shareholder.get("shareHolderID"),
            "shareHolderShareID": shareholder.get("shareHolderShareID"),
            "insCode": ins_code,
            "تعداد سهام": shareholder.get("numberOfShares", 0),
            "تغییر سهام": shareholder.get("change", 0),
            "درصد": shareholder.get("perOfShares", 0),
        }

    all_names = set(old_lookup.keys()) | set(current_data.keys())

    rows = []

    for name in all_names:

        old_row = old_lookup.get(name)

        if old_row is not None:

            row = {
                column: old_row.get(column)
                for column in META_COLUMNS
            }

            for date in date_columns:

                row[date] = old_row.get(date)

        else:

            row = {column: None for column in META_COLUMNS}

        row["سهامدار"] = name

        if name in current_data:

            info = current_data[name]

            row["shareHolderID"] = info["shareHolderID"]
            row["shareHolderShareID"] = info["shareHolderShareID"]
            row["insCode"] = info["insCode"]
            row["تعداد سهام"] = info["تعداد سهام"]
            row["تغییر سهام"] = info["تغییر سهام"]
            row[today] = info["درصد"]

        else:

            row[today] = 0
            row["تغییر سهام"] = 0

        rows.append(row)

    new_df = pd.DataFrame(rows)

    final_columns = META_COLUMNS.copy()

    previous_dates = [
        date for date in date_columns if date != today
    ]

    previous_dates.append(today)

    final_columns.extend(previous_dates)

    final_columns = [
        column for column in final_columns if column in new_df.columns
    ]

    new_df = new_df[final_columns]

    new_df = new_df.sort_values(by="سهامدار", na_position="last")

    new_df.to_excel(file_path, index=False)


# =========================================================
# UPDATE ALL STOCKS
# =========================================================

def update_all_stocks(progress_callback=None):

    stocks = read_stock_list()

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    total = len(stocks)

    results = {
        "total": total,
        "success": 0,
        "failed": 0,
        "errors": [],
    }

    session = build_session()

    try:

        for index, stock_name in enumerate(stocks, start=1):

            try:

                if progress_callback:

                    progress_callback(index, total, stock_name)

                print(f"[{index}/{total}] {stock_name}")

                instrument = find_stock(session, stock_name)

                if not instrument:

                    raise Exception("نماد در TSETMC پیدا نشد")

                ins_code = (
                    instrument.get("insCode")
                    or instrument.get("ins_code")
                )

                if not ins_code:

                    raise Exception("insCode پیدا نشد")

                shareholders = get_shareholders(session, ins_code)

                if not shareholders:

                    raise Exception("اطلاعات سهامداران پیدا نشد")

                update_stock_file(stock_name, shareholders, ins_code)

                results["success"] += 1

            except Exception as e:

                results["failed"] += 1

                results["errors"].append({
                    "نماد": stock_name,
                    "خطا": str(e),
                })

                print(f"❌ {stock_name}: {e}")

            time.sleep(REQUEST_DELAY_SECONDS)

    finally:

        session.close()

    return results


# =========================================================
# Standalone
# =========================================================

if __name__ == "__main__":

    result = update_all_stocks()

    print()
    print("================================")
    print("Finished")
    print("================================")

    print(f"Total: {result['total']}")
    print(f"Success: {result['success']}")
    print(f"Failed: {result['failed']}")

    if result["errors"]:

        print("\nErrors:")

        for error in result["errors"]:

            print(f"{error['نماد']} -> {error['خطا']}")
