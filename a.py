# campaign_ui.py

import streamlit as st
import pandas as pd
import re
import io

# --- Config ---
EXCEL_FILE = r"C:\Users\SUBARNA MONDAL\Desktop\New folder (2)\Domain Leads151025(OLD_USA).xlsx"
TEMPLATE_FILE = r"C:\Users\SUBARNA MONDAL\Desktop\New folder (2)\campaign-template.csv"

# --- Load Data ---
@st.cache_data
def load_data():
    df_excel = pd.read_excel(EXCEL_FILE, dtype=str)
    df_template = pd.read_csv(TEMPLATE_FILE, dtype=str)
    return df_excel, df_template

df_excel, df_template = load_data()

# --- Phone Cleaner ---
def clean_us_phone(phone):
    if pd.isna(phone):
        return ""
    digits = re.sub(r'\D', '', str(phone))
    if digits.startswith("1") and len(digits) == 11:
        return digits
    elif len(digits) == 10:
        return f"1{digits}"
    return digits

# --- Extract Function ---
def extract_batch(start, end):
    selected = df_excel.iloc[start:end].copy()

    for col in ['domain_name', 'registrant_name', 'registrant_phone']:
        if col not in selected.columns:
            raise KeyError(f"Missing column: {col}")

    selected['registrant_phone'] = selected['registrant_phone'].apply(clean_us_phone)

    new_data = pd.DataFrame({
        'number': selected['registrant_phone'],
        'name': selected['registrant_name'],
        'another_var': selected['domain_name']
    })

    df_clean_template = df_template[
        ~df_template['name'].astype(str).str.lower().isin(['john doe', 'jane smith', 'bob johnson'])
    ]

    combined = pd.concat([df_clean_template, new_data], ignore_index=True)
    combined = combined[['number', 'name', 'another_var']]
    return combined

# --- Streamlit UI ---
st.title("📞 Campaign Data Extractor")
st.write("Generate batches of 10 leads with cleaned phone numbers (starting with 1).")

# Persistent counter using Streamlit session state
if "start_index" not in st.session_state:
    st.session_state.start_index = 500  # initial starting point

start = st.session_state.start_index
end = start + 10

st.write(f"**Current Batch:** Rows {start + 1} → {end}")

# Extract batch
try:
    batch_df = extract_batch(start, end)
except Exception as e:
    st.error(f"Error: {e}")
    st.stop()

# Show preview
st.dataframe(batch_df)

# --- Buttons ---
col1, col2 = st.columns(2)

# Download button
csv_buffer = io.StringIO()
batch_df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
csv_bytes = csv_buffer.getvalue().encode('utf-8-sig')

col1.download_button(
    label="📥 Download This Batch",
    data=csv_bytes,
    file_name=f"campaign-output-{start+1}-{end}.csv",
    mime="text/csv"
)

# Next batch button
if col2.button("➡️ Next Batch"):
    st.session_state.start_index += 10
    st.rerun()
