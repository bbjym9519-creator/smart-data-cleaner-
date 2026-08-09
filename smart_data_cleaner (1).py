import io
import os
import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="Smart Data Cleaner", page_icon="🧹", layout="wide")

st.title("🧹 Smart Data Cleaner")
st.caption("ارفع Excel أو CSV → افحص البيانات → نظّفها → حمّل الملف النظيف")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

uploaded = st.file_uploader(
    "ارفع ملف البيانات",
    type=["csv", "xlsx", "xls"],
    help="يدعم CSV وExcel"
)

def load_file(file):
    name = file.name.lower()
    if name.endswith(".csv"):
        # يحاول أكثر من encoding شائع
        for enc in ["utf-8-sig", "utf-8", "cp1256", "latin1"]:
            try:
                file.seek(0)
                return pd.read_csv(file, encoding=enc)
            except Exception:
                pass
        raise ValueError("تعذر قراءة ملف CSV. جرّب حفظه بصيغة UTF-8.")
    file.seek(0)
    return pd.read_excel(file)

def profile(df):
    rows = []
    for c in df.columns:
        s = df[c]
        rows.append({
            "column": str(c),
            "dtype": str(s.dtype),
            "missing": int(s.isna().sum()),
            "missing_pct": round(float(s.isna().mean() * 100), 2),
            "unique": int(s.nunique(dropna=True)),
            "duplicates": int(s.duplicated().sum()),
        })
    return pd.DataFrame(rows)

def clean_dataframe(df):
    out = df.copy()
    actions = []

    # توحيد أسماء الأعمدة
    old_cols = list(out.columns)
    new_cols = []
    seen = {}
    for c in old_cols:
        n = re.sub(r"\s+", "_", str(c).strip())
        n = re.sub(r"[^\w\u0600-\u06FF]+", "_", n).strip("_")
        if not n:
            n = "column"
        seen[n] = seen.get(n, 0) + 1
        if seen[n] > 1:
            n = f"{n}_{seen[n]}"
        new_cols.append(n)
    if new_cols != old_cols:
        out.columns = new_cols
        actions.append(f"تم تنظيف أسماء {len(old_cols)} عمودًا وتوحيدها.")

    # إزالة الصفوف المكررة بالكامل
    before = len(out)
    out = out.drop_duplicates()
    removed = before - len(out)
    if removed:
        actions.append(f"تم حذف {removed:,} صف مكرر بالكامل.")

    # تنظيف النصوص والمسافات
    for c in out.select_dtypes(include=["object", "string"]).columns:
        before_values = out[c].copy()
        out[c] = out[c].astype("string").str.strip()
        out[c] = out[c].replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
        if not out[c].equals(before_values.astype("string")):
            actions.append(f"تم تنظيف المسافات والقيم النصية في العمود: {c}")

    # محاولة تحويل أعمدة تبدو رقمية
    for c in out.columns:
        if out[c].dtype == "object" or str(out[c].dtype) == "string":
            raw = out[c].astype("string").str.replace(",", "", regex=False)
            converted = pd.to_numeric(raw, errors="coerce")
            non_null = out[c].notna().sum()
            if non_null and converted.notna().sum() / non_null >= 0.9:
                out[c] = converted
                actions.append(f"تم تحويل العمود {c} إلى نوع رقمي مناسب.")

    # تعويض القيم المفقودة رقميًا بالوسيط، والنصية بـ Unknown
    for c in out.columns:
        missing = int(out[c].isna().sum())
        if missing == 0:
            continue
        if pd.api.types.is_numeric_dtype(out[c]):
            med = out[c].median()
            if pd.notna(med):
                out[c] = out[c].fillna(med)
                actions.append(f"تم تعويض {missing:,} قيمة مفقودة في {c} بالوسيط ({med:g}).")
        else:
            out[c] = out[c].fillna("Unknown")
            actions.append(f"تم تعويض {missing:,} قيمة مفقودة في {c} بـ Unknown.")

    return out, actions

if uploaded:
    try:
        df = load_file(uploaded)
    except Exception as e:
        st.error(f"خطأ في قراءة الملف: {e}")
        st.stop()

    st.success(f"تم تحميل الملف: {uploaded.name} — {len(df):,} صف × {len(df.columns):,} عمود")

    c1, c2, c3 = st.columns(3)
    c1.metric("Rows", f"{len(df):,}")
    c2.metric("Columns", f"{len(df.columns):,}")
    c3.metric("Missing Values", f"{int(df.isna().sum().sum()):,}")

    tab1, tab2, tab3 = st.tabs(["🔎 التشخيص", "🧹 التنظيف", "📥 التحميل"])

    with tab1:
        st.subheader("ملخص جودة البيانات")
        p = profile(df)
        st.dataframe(p, use_container_width=True)
        st.subheader("عينة من البيانات")
        st.dataframe(df.head(20), use_container_width=True)

        if df.duplicated().sum():
            st.warning(f"يوجد {df.duplicated().sum():,} صف مكرر.")
        if df.isna().sum().sum():
            st.warning(f"يوجد {int(df.isna().sum().sum()):,} قيمة مفقودة.")

    if "cleaned" not in st.session_state:
        st.session_state.cleaned = None
        st.session_state.actions = None

    with tab2:
        st.write("التنظيف الافتراضي محافظ نسبيًا: تكرارات، مسافات، أنواع بيانات، وقيم مفقودة.")
        if st.button("🧹 نظّف البيانات الآن", type="primary"):
            cleaned, actions = clean_dataframe(df)
            st.session_state.cleaned = cleaned
            st.session_state.actions = actions
            st.rerun()

        if st.session_state.cleaned is not None:
            cleaned = st.session_state.cleaned
            st.success("اكتمل التنظيف.")
            st.metric("عدد التغييرات", len(st.session_state.actions))
            for a in st.session_state.actions:
                st.write("•", a)
            st.dataframe(cleaned.head(20), use_container_width=True)

    with tab3:
        cleaned = st.session_state.cleaned
        if cleaned is None:
            st.info("نظّف البيانات أولًا، ثم ارجع لهذه الصفحة للتحميل.")
        else:
            csv_bytes = cleaned.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "⬇️ تحميل CSV النظيف",
                data=csv_bytes,
                file_name="cleaned_data.csv",
                mime="text/csv",
            )

            xlsx = io.BytesIO()
            with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
                cleaned.to_excel(writer, index=False, sheet_name="Cleaned_Data")
                pd.DataFrame({"Action": st.session_state.actions}).to_excel(
                    writer, index=False, sheet_name="Cleaning_Log"
                )
            st.download_button(
                "⬇️ تحميل Excel النظيف + سجل التغييرات",
                data=xlsx.getvalue(),
                file_name="cleaned_data.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    st.divider()
    st.subheader("🤖 تحليل ذكي اختياري")
    st.caption("يمكن إضافة OpenAI لاحقًا لشرح مشاكل البيانات واقتراح قواعد تنظيف مخصصة. لا نرسل كامل الملف تلقائيًا؛ الأفضل إرسال schema/ملخص بعد موافقتك.")

    if OPENAI_API_KEY:
        st.success("تم العثور على OPENAI_API_KEY في بيئة التشغيل.")
    else:
        st.info("لم يتم العثور على OPENAI_API_KEY. الأداة تعمل بالتنظيف المحلي بدون AI.")
else:
    st.info("ارفع ملف CSV أو Excel للبدء.")
