import os
import sys
import json
import pandas as pd
import streamlit as st
import plotly.express as px


# =========================================================
# PATHS
#
# نسبت به محل خود فایل، نه یک مسیر ثابت ویندوزی — همین کد بدون
# تغییر هم لوکال، هم داخل GitHub Actions، و هم روی Streamlit
# Cloud کار می‌کند.
# =========================================================

BASE_FOLDER = os.path.dirname(os.path.abspath(__file__))

DATA_FOLDER = os.path.join(BASE_FOLDER, "data", "shareholders")

COLLECTOR_FILE = os.path.join(BASE_FOLDER, "collector.py")

# فایل ذخیره لیست سهامداران مورد نظر کاربر (بین اجراهای مختلف باقی می‌ماند)
WATCHED_HOLDERS_FILE = os.path.join(BASE_FOLDER, "data", "watched_holders.json")


# =========================================================
# Metadata
# =========================================================

META_COLUMNS = [
    "سهامدار",
    "shareHolderID",
    "shareHolderShareID",
    "insCode",
    "تعداد سهام",
    "تغییر سهام",
]


# =========================================================
# Page
# =========================================================

st.set_page_config(
    page_title="TSETMC Shareholder Dashboard",
    page_icon="📊",
    layout="wide"
)


# =========================================================
# Small helpers
# =========================================================

def to_numeric(series):
    """Common pattern used everywhere below: coerce to numeric, NaN on failure."""
    return pd.to_numeric(series, errors="coerce")


@st.cache_data
def get_stock_files():

    if not os.path.exists(DATA_FOLDER):

        return []

    return sorted([
        file
        for file in os.listdir(DATA_FOLDER)
        if file.endswith(".xlsx")
    ])


@st.cache_data
def load_stock(file_name):

    path = os.path.join(DATA_FOLDER, file_name)

    return pd.read_excel(path)


def get_stock_name(file_name):

    return os.path.splitext(file_name)[0]


def get_date_columns(df):

    return [
        column
        for column in df.columns
        if column not in META_COLUMNS
    ]


def load_watched_holders():

    if not os.path.exists(WATCHED_HOLDERS_FILE):

        return []

    try:

        with open(WATCHED_HOLDERS_FILE, "r", encoding="utf-8") as f:

            data = json.load(f)

        if isinstance(data, list):

            return data

        return []

    except Exception:

        return []


def save_watched_holders(holders_list):

    try:

        os.makedirs(os.path.dirname(WATCHED_HOLDERS_FILE), exist_ok=True)

        with open(WATCHED_HOLDERS_FILE, "w", encoding="utf-8") as f:

            json.dump(holders_list, f, ensure_ascii=False, indent=2)

    except Exception as e:

        st.error(f"❌ خطا در ذخیره لیست سهامداران مورد نظر:\n{e}")


# =========================================================
# UPDATE DATA
# =========================================================

def update_data():

    try:

        if BASE_FOLDER not in sys.path:

            sys.path.insert(0, BASE_FOLDER)

        import collector

        progress = st.progress(0)
        status = st.empty()

        def callback(current, total, stock_name):

            percent = current / total if total else 0

            progress.progress(percent)

            status.info(
                f"در حال دریافت: {stock_name} ({current}/{total})"
            )

        result = collector.update_all_stocks(progress_callback=callback)

        progress.progress(1.0)
        status.success("✅ دریافت اطلاعات به پایان رسید.")

        return result

    except Exception as e:

        st.error(f"❌ خطا در دریافت اطلاعات:\n{e}")

        return None


# =========================================================
# Calculate changes
# =========================================================

def calculate_changes(df):

    date_columns = get_date_columns(df)

    if len(date_columns) < 2:

        return {
            "increases": 0,
            "decreases": 0,
            "net_change": 0,
            "total_change": 0,
        }

    previous_date = date_columns[-2]
    latest_date = date_columns[-1]

    previous = to_numeric(df[previous_date]).fillna(0)
    latest = to_numeric(df[latest_date]).fillna(0)

    changes = latest - previous

    return {
        "increases": int((changes > 0).sum()),
        "decreases": int((changes < 0).sum()),
        "net_change": float(changes.sum()),
        "total_change": float(changes.abs().sum()),
    }


# =========================================================
# Watchlist
# =========================================================

def create_watchlist(stock_files):

    rows = []

    for file_name in stock_files:

        df = load_stock(file_name)

        date_columns = get_date_columns(df)

        if not date_columns:

            continue

        changes = calculate_changes(df)

        stock_name = get_stock_name(file_name)

        if changes["net_change"] > 0:
            status = "🟢 افزایش"
        elif changes["net_change"] < 0:
            status = "🔴 کاهش"
        else:
            status = "⚪ بدون تغییر"

        rows.append({
            "نماد": stock_name,
            "وضعیت": status,
            "افزایش‌دهنده": changes["increases"],
            "کاهش‌دهنده": changes["decreases"],
            "تغییر خالص (%)": round(changes["net_change"], 3),
            "آخرین تاریخ": date_columns[-1],
        })

    return pd.DataFrame(rows)


# =========================================================
# Shareholder Index
#
# Rewritten to avoid the row-by-row Python loop (df.iterrows())
# from the original version: each file's data is now built as a
# small vectorized DataFrame and the files are concatenated once
# at the end, instead of appending one dict per shareholder row.
# =========================================================

@st.cache_data
def build_shareholder_index(stock_files):

    frames = []

    for file_name in stock_files:

        df = load_stock(file_name)

        if "سهامدار" not in df.columns:

            continue

        date_columns = get_date_columns(df)

        if not date_columns:

            continue

        latest_date = date_columns[-1]
        previous_date = date_columns[-2] if len(date_columns) >= 2 else None

        stock_name = get_stock_name(file_name)

        working = df.copy()

        working["سهامدار"] = working["سهامدار"].astype(str).str.strip()
        working = working[working["سهامدار"] != ""]

        latest = to_numeric(working[latest_date])
        valid = latest.notna()

        working = working[valid]
        latest = latest[valid]

        if previous_date:

            previous = to_numeric(working[previous_date])
            daily_change = latest - previous

        else:

            daily_change = pd.Series(pd.NA, index=working.index)

        frame = pd.DataFrame({
            "سهامدار": working["سهامدار"].values,
            "نماد": stock_name,
            "درصد مالکیت": latest.values,
            "تغییر مالکیت روزانه": daily_change.values,
            "تعداد سهام": to_numeric(working.get("تعداد سهام")).values,
            "تغییر سهام": to_numeric(working.get("تغییر سهام")).values,
            "تاریخ": latest_date,
        })

        frames.append(frame)

    if not frames:

        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


# =========================================================
# Header
# =========================================================

st.title("📊 TSETMC Shareholder Dashboard")
st.caption("بررسی سهامداران عمده و تغییرات روزانه")


# =========================================================
# Sidebar - Data update
# =========================================================

with st.sidebar:

    st.header("⚙️ مدیریت اطلاعات")

    st.write("منبع نمادها:")
    st.code("MarketWatchPlus-1404_10_22.xlsx")

    st.write("محل ذخیره:")
    st.code(DATA_FOLDER)

    st.divider()

    st.subheader("🔄 دریافت اطلاعات جدید")

    st.caption(
        "در نسخه‌ی مستقر روی GitHub، این کار هر روز به صورت "
        "خودکار توسط GitHub Actions انجام می‌شود. این دکمه "
        "بیشتر برای اجرای دستی/لوکال است."
    )

    update_enabled = st.checkbox(
        "فعال کردن دریافت اطلاعات جدید",
        value=False
    )

    if update_enabled:

        st.warning(
            "با اجرای دریافت، اطلاعات سهامداران "
            "برای تمام نمادهای فایل MarketWatch "
            "از TSETMC دریافت می‌شود."
        )

        if st.button("🚀 دریافت اطلاعات جدید", use_container_width=True):

            with st.spinner("در حال دریافت اطلاعات..."):

                result = update_data()

            if result:

                st.success(f"موفق: {result['success']}")
                st.error(f"ناموفق: {result['failed']}")

                st.cache_data.clear()
                st.rerun()

    st.divider()

    if st.button("🔄 Refresh داشبورد", use_container_width=True):

        st.cache_data.clear()
        st.rerun()


# =========================================================
# Load files
# =========================================================

stock_files = get_stock_files()

# Tuple instead of list: cheaper and more consistent hashing key
# for st.cache_data on the two functions that take this as an arg.
stock_files_key = tuple(stock_files)

if not stock_files:

    st.warning("هنوز هیچ فایل سهامداری وجود ندارد.")

    st.info(
        "از Sidebar گزینه "
        "«فعال کردن دریافت اطلاعات جدید» "
        "را فعال کنید و سپس روی "
        "«دریافت اطلاعات جدید» کلیک کنید."
    )

    st.stop()

# سهامداران‌ایندکس یک‌بار محاسبه می‌شود تا هم در تب «مالکیت شرکت‌ها»
# و هم در تب «سهامداران مورد نظر من» استفاده شود.
shareholder_index = build_shareholder_index(stock_files_key)

all_known_holders = sorted(
    shareholder_index["سهامدار"].dropna().unique().tolist()
) if not shareholder_index.empty else []

if "watched_holders" not in st.session_state:

    st.session_state.watched_holders = load_watched_holders()


# =========================================================
# Tabs
# =========================================================

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Watchlist",
    "📈 بررسی نماد",
    "🏢 مالکیت شرکت‌ها",
    "⭐ سهامداران مورد نظر من",
])


# =========================================================
# TAB 1
# =========================================================

with tab1:

    st.subheader("📊 وضعیت کلی نمادها")

    watchlist = create_watchlist(stock_files_key)

    if watchlist.empty:

        st.warning("اطلاعات کافی وجود ندارد.")

    else:

        total = len(watchlist)
        increasing = int((watchlist["تغییر خالص (%)"] > 0).sum())
        decreasing = int((watchlist["تغییر خالص (%)"] < 0).sum())
        unchanged = int((watchlist["تغییر خالص (%)"] == 0).sum())

        c1, c2, c3, c4 = st.columns(4)

        c1.metric("تعداد نمادها", total)
        c2.metric("افزایش", increasing)
        c3.metric("کاهش", decreasing)
        c4.metric("بدون تغییر", unchanged)

        st.dataframe(watchlist, use_container_width=True, hide_index=True)


# =========================================================
# TAB 2
# =========================================================

with tab2:

    st.subheader("📈 بررسی یک نماد")

    stock_names = [get_stock_name(file) for file in stock_files]

    selected_stock = st.selectbox("نماد:", stock_names)

    df = load_stock(selected_stock + ".xlsx")

    date_columns = get_date_columns(df)

    if not date_columns:

        st.warning("اطلاعات تاریخی وجود ندارد.")
        st.stop()

    latest_date = date_columns[-1]

    # -----------------------------------------------------
    # Metrics
    # -----------------------------------------------------

    changes = calculate_changes(df)

    if changes["net_change"] > 0:
        st.success(f"🟢 تغییر خالص در {latest_date} مثبت است.")
    elif changes["net_change"] < 0:
        st.error(f"🔴 تغییر خالص در {latest_date} منفی است.")
    else:
        st.info("⚪ تغییر خالص وجود ندارد.")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("افزایش‌دهندگان", changes["increases"])
    c2.metric("کاهش‌دهندگان", changes["decreases"])
    c3.metric("تغییر خالص", f"{changes['net_change']:.3f}%")
    c4.metric("مجموع تغییر", f"{changes['total_change']:.3f}%")

    # -----------------------------------------------------
    # Table
    # -----------------------------------------------------

    st.subheader("👥 سهامداران عمده")

    display_columns = [
        col for col in
        ["سهامدار", "تعداد سهام", "تغییر سهام", latest_date]
        if col in df.columns
    ]

    display_df = (
        df[display_columns]
        .copy()
        .sort_values(latest_date, ascending=False)
    )

    st.dataframe(display_df, use_container_width=True, hide_index=True)

    # -----------------------------------------------------
    # Single holder chart
    # -----------------------------------------------------

    st.subheader("👤 تاریخچه یک سهامدار")

    holders = (
        df["سهامدار"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    selected_holder = st.selectbox("سهامدار:", holders)

    holder_row = df[df["سهامدار"].astype(str) == selected_holder]

    if not holder_row.empty:

        row = holder_row.iloc[0]

        chart_df = pd.DataFrame({
            "تاریخ": date_columns,
            "درصد مالکیت": to_numeric(row[date_columns]).values,
        })

        fig = px.line(
            chart_df,
            x="تاریخ",
            y="درصد مالکیت",
            markers=True,
            title=selected_holder
        )

        st.plotly_chart(fig, use_container_width=True)

    # -----------------------------------------------------
    # Multiple holders
    #
    # Rewritten with pandas.melt instead of a nested Python loop
    # (holder x date) building one dict per cell.
    # -----------------------------------------------------

    st.subheader("📊 مقایسه چند سهامدار")

    selected_holders = st.multiselect(
        "سهامداران:",
        holders,
        default=holders[:5]
    )

    if selected_holders:

        subset = df[df["سهامدار"].astype(str).isin(selected_holders)].copy()
        subset["سهامدار"] = subset["سهامدار"].astype(str)
        subset = subset.drop_duplicates(subset=["سهامدار"], keep="first")

        chart_df = subset.melt(
            id_vars="سهامدار",
            value_vars=date_columns,
            var_name="تاریخ",
            value_name="درصد مالکیت",
        )

        chart_df["درصد مالکیت"] = to_numeric(chart_df["درصد مالکیت"])

        fig = px.line(
            chart_df,
            x="تاریخ",
            y="درصد مالکیت",
            color="سهامدار",
            markers=True
        )

        st.plotly_chart(fig, use_container_width=True)

    # -----------------------------------------------------
    # Daily changes
    # -----------------------------------------------------

    if len(date_columns) >= 2:

        st.subheader("🔄 تغییرات روزانه")

        previous_date = date_columns[-2]

        changes_df = df[["سهامدار", previous_date, latest_date]].copy()

        changes_df["تغییر"] = (
            to_numeric(changes_df[latest_date]).fillna(0)
            - to_numeric(changes_df[previous_date]).fillna(0)
        )

        changes_df = changes_df.sort_values("تغییر", ascending=False)

        st.dataframe(changes_df, use_container_width=True, hide_index=True)


# =========================================================
# TAB 3
# =========================================================

with tab3:

    st.subheader("🏢 نمادهایی که یک سهامدار در آن‌ها سهامدار عمده است")

    if shareholder_index.empty:

        st.warning("اطلاعات سهامداران وجود ندارد.")
        st.stop()

    selected_company = st.selectbox("شرکت / سهامدار عمده:", all_known_holders)

    company_df = shareholder_index[
        shareholder_index["سهامدار"] == selected_company
    ].copy()

    # -----------------------------------------------------
    # Search
    # -----------------------------------------------------

    search = st.text_input("🔎 جستجوی نماد")

    if search:

        company_df = company_df[
            company_df["نماد"].astype(str).str.contains(
                search, case=False, na=False
            )
        ]

    # -----------------------------------------------------
    # Filter
    # -----------------------------------------------------

    change_filter = st.selectbox(
        "فیلتر تغییر:",
        ["همه", "افزایش مالکیت", "کاهش مالکیت", "بدون تغییر"]
    )

    if change_filter == "افزایش مالکیت":
        company_df = company_df[company_df["تغییر مالکیت روزانه"] > 0]
    elif change_filter == "کاهش مالکیت":
        company_df = company_df[company_df["تغییر مالکیت روزانه"] < 0]
    elif change_filter == "بدون تغییر":
        company_df = company_df[company_df["تغییر مالکیت روزانه"] == 0]

    company_df = company_df.sort_values("درصد مالکیت", ascending=False)

    # -----------------------------------------------------
    # Metrics
    # -----------------------------------------------------

    if company_df.empty:

        st.warning("نمادی مطابق فیلتر پیدا نشد.")

    else:

        c1, c2, c3, c4 = st.columns(4)

        c1.metric("تعداد نمادها", len(company_df))
        c2.metric("بیشترین مالکیت", f"{company_df['درصد مالکیت'].max():.3f}%")
        c3.metric("افزایش", int((company_df["تغییر مالکیت روزانه"] > 0).sum()))
        c4.metric("کاهش", int((company_df["تغییر مالکیت روزانه"] < 0).sum()))

        # -------------------------------------------------
        # Table
        # -------------------------------------------------

        st.subheader(f"📋 پرتفوی {selected_company}")

        table_df = company_df[[
            "نماد",
            "درصد مالکیت",
            "تغییر مالکیت روزانه",
            "تعداد سهام",
            "تغییر سهام",
            "تاریخ",
        ]].rename(columns={
            "تغییر مالکیت روزانه": "تغییر مالکیت (واحد درصد)"
        })

        st.dataframe(
            table_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "درصد مالکیت": st.column_config.NumberColumn(format="%.3f%%"),
                "تغییر مالکیت (واحد درصد)": st.column_config.NumberColumn(format="%.3f"),
                "تعداد سهام": st.column_config.NumberColumn(format="%d"),
                "تغییر سهام": st.column_config.NumberColumn(format="%d"),
            }
        )

        # -------------------------------------------------
        # Ownership chart
        # -------------------------------------------------

        st.subheader("📊 درصد مالکیت")

        ownership_chart = company_df[["نماد", "درصد مالکیت"]].sort_values("درصد مالکیت")

        fig = px.bar(
            ownership_chart,
            x="درصد مالکیت",
            y="نماد",
            orientation="h",
            title=f"درصد مالکیت {selected_company}"
        )

        st.plotly_chart(fig, use_container_width=True)

        # -------------------------------------------------
        # Daily change chart
        # -------------------------------------------------

        st.subheader("📈 تغییر روزانه مالکیت")

        change_chart = company_df[["نماد", "تغییر مالکیت روزانه"]].sort_values("تغییر مالکیت روزانه")

        fig = px.bar(
            change_chart,
            x="تغییر مالکیت روزانه",
            y="نماد",
            orientation="h",
            title="تغییر مالکیت نسبت به روز قبل"
        )

        st.plotly_chart(fig, use_container_width=True)


# =========================================================
# TAB 4 — سهامداران مورد نظر من
#
# هر تعداد سهامدار که کاربر بخواهد اضافه می‌کند؛ زیر نام هر
# سهامدار یک جدول با نمادهایی که در آن‌ها سهامدار است، درصد
# مالکیت و مقدار تغییر نمایش داده می‌شود. لیست در یک فایل JSON
# ذخیره می‌شود تا بعد از بستن برنامه هم باقی بماند.
# =========================================================

with tab4:

    st.subheader("⭐ سهامداران مورد نظر من")

    if shareholder_index.empty:

        st.warning("اطلاعات سهامداران وجود ندارد.")
        st.stop()

    # -----------------------------------------------------
    # افزودن سهامدار جدید
    # -----------------------------------------------------

    remaining_holders = [
        holder
        for holder in all_known_holders
        if holder not in st.session_state.watched_holders
    ]

    col_add1, col_add2 = st.columns([4, 1])

    with col_add1:

        new_holder = st.selectbox(
            "افزودن سهامدار:",
            remaining_holders,
            index=None,
            placeholder="نام سهامدار را جستجو و انتخاب کنید...",
            key="new_holder_to_add"
        )

    with col_add2:

        st.write("")
        st.write("")

        if st.button("➕ افزودن", use_container_width=True, disabled=not new_holder):

            st.session_state.watched_holders.append(new_holder)
            save_watched_holders(st.session_state.watched_holders)
            st.rerun()

    st.divider()

    # -----------------------------------------------------
    # نمایش هر سهامدار به همراه جدول سهامش
    # -----------------------------------------------------

    if not st.session_state.watched_holders:

        st.info("هنوز سهامداری اضافه نکرده‌اید. از بالا یک سهامدار انتخاب و اضافه کنید.")

    else:

        for holder in list(st.session_state.watched_holders):

            header_col, remove_col = st.columns([6, 1])

            header_col.markdown(f"### 👤 {holder}")

            if remove_col.button("🗑 حذف", key=f"remove_{holder}"):

                st.session_state.watched_holders.remove(holder)
                save_watched_holders(st.session_state.watched_holders)
                st.rerun()

            holder_df = shareholder_index[
                shareholder_index["سهامدار"] == holder
            ][[
                "نماد",
                "درصد مالکیت",
                "تغییر مالکیت روزانه",
                "تعداد سهام",
                "تغییر سهام",
                "تاریخ",
            ]].rename(columns={
                "تغییر مالکیت روزانه": "تغییر مالکیت (واحد درصد)"
            }).sort_values("درصد مالکیت", ascending=False)

            if holder_df.empty:

                st.caption("این سهامدار در هیچ نمادی یافت نشد.")

            else:

                s1, s2, s3 = st.columns(3)

                s1.metric("تعداد نمادها", len(holder_df))
                s2.metric("بیشترین مالکیت", f"{holder_df['درصد مالکیت'].max():.3f}%")
                s3.metric(
                    "افزایش‌یافته",
                    int((holder_df["تغییر مالکیت (واحد درصد)"] > 0).sum())
                )

                st.dataframe(
                    holder_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "درصد مالکیت": st.column_config.NumberColumn(format="%.3f%%"),
                        "تغییر مالکیت (واحد درصد)": st.column_config.NumberColumn(format="%.3f"),
                        "تعداد سهام": st.column_config.NumberColumn(format="%d"),
                        "تغییر سهام": st.column_config.NumberColumn(format="%d"),
                    }
                )

            st.divider()
