# campaign_ui.py
import streamlit as st
import pandas as pd
import re
import io

# --- Page Setup ---
st.set_page_config(page_title="Campaign Batch Extractor", layout="wide", page_icon="📞")
st.title("📞 Campaign Batch Extractor")
st.markdown("Easily extract batches of 10 leads from your uploaded Excel file. You can also delete individual rows before downloading.")

# --- Phone Cleaner ---
def clean_us_phone(phone):
    """Ensure phone numbers are 10 or 11 digits and start with 1."""
    if pd.isna(phone):
        return ""
    digits = re.sub(r'\D', '', str(phone))
    if len(digits) == 10:
        return f"1{digits}"
    elif digits.startswith("1") and len(digits) == 11:
        return digits
    return digits

# --- File Upload ---
uploaded_excel = st.file_uploader("📤 Upload Excel file (with columns: domain_name, registrant_name, registrant_phone)", type=["xlsx"])
uploaded_template = st.file_uploader("📤 Upload Template CSV (with columns: number, name, another_var)", type=["csv"])

if not uploaded_excel or not uploaded_template:
    st.info("⬆️ Please upload both the Excel and Template CSV files to begin.")
    st.stop()

# --- Load Data ---
try:
    df_excel = pd.read_excel(uploaded_excel, dtype=str)
    df_template = pd.read_csv(uploaded_template, dtype=str)
except Exception as e:
    st.error(f"❌ Error reading files: {e}")
    st.stop()

# --- Check Columns ---
required_cols = ['domain_name', 'registrant_name', 'registrant_phone']
missing_cols = [col for col in required_cols if col not in df_excel.columns]
if missing_cols:
    st.error(f"❌ Missing columns in Excel file: {', '.join(missing_cols)}")
    st.stop()

# --- Session State for Pagination & Deletions ---
if "start_index" not in st.session_state:
    st.session_state.start_index = 0
if "deleted_indices" not in st.session_state:
    st.session_state.deleted_indices = set()

# --- User Input for Start Row ---
start_input = st.number_input(
    "📍 Start from row number:",
    min_value=1, max_value=len(df_excel), value=st.session_state.start_index + 1, step=1
)
st.session_state.start_index = start_input - 1

# --- Define Range ---
batch_size = 10
start = st.session_state.start_index
end = min(start + batch_size, len(df_excel))

# --- Extract Batch ---
selected = df_excel.iloc[start:end].copy()
selected["index_in_file"] = selected.index  # keep original index reference
selected["registrant_phone"] = selected["registrant_phone"].apply(clean_us_phone)

# --- Prepare Output ---
new_data = pd.DataFrame({
    "number": selected["registrant_phone"],
    "name": selected["registrant_name"],
    "another_var": selected["domain_name"],
    "orig_index": selected["index_in_file"]
})

df_clean_template = df_template[
    ~df_template["name"].astype(str).str.lower().isin(["john doe", "jane smith", "bob johnson"])
]

# Filter out deleted rows
new_data = new_data[~new_data["orig_index"].isin(st.session_state.deleted_indices)]

# Combine
combined = pd.concat([df_clean_template, new_data], ignore_index=True)[["number", "name", "another_var"]]

# --- Display Table with Delete Buttons ---
st.subheader(f"📋 Showing rows {start + 1} to {end} of {len(df_excel)}")
st.write("You can delete unwanted rows before downloading 👇")

for i, row in new_data.iterrows():
    col1, col2, col3, col4 = st.columns([3, 3, 3, 1])
    col1.write(row["name"])
    col2.write(row["number"])
    col3.write(row["another_var"])
    if col4.button("❌ Delete", key=f"delete_{row['orig_index']}"):
        st.session_state.deleted_indices.add(row["orig_index"])
        st.rerun()

if new_data.empty:
    st.warning("⚠️ All rows in this batch were deleted.")

# --- Buttons ---
colA, colB, colC = st.columns(3)

# Previous Batch
if colA.button("⬅️ Previous Batch") and st.session_state.start_index >= batch_size:
    st.session_state.start_index -= batch_size
    st.session_state.deleted_indices.clear()
    st.rerun()

# Download
csv_buffer = io.StringIO()
combined.to_csv(csv_buffer, index=False, encoding="utf-8-sig")
csv_bytes = csv_buffer.getvalue().encode("utf-8-sig")

colB.download_button(
    label="📥 Download This Batch",
    data=csv_bytes,
    file_name=f"campaign-output-{start+1}-{end}.csv",
    mime="text/csv"
)

# Next Batch
if colC.button("➡️ Next Batch") and end < len(df_excel):
    st.session_state.start_index += batch_size
    st.session_state.deleted_indices.clear()
    st.rerun()

st.caption("Developed for marketing automation — ready for deployment 🚀")
