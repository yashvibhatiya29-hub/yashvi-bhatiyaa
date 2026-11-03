# GST Rate Finder

BBA FinTech Practical Assignment - a Streamlit web app that tells you whether GST applies
to a goods or service, the GST rate and its HSN / SAC code.

**Live app:** _add your Streamlit link here_

## Features
- Search by name, synonym, Hindi name (chawal, doodh) or HSN / SAC code
- Clear status: **GST Applicable** / **GST Not Applicable (Nil / Exempt)** / **Outside GST**
- Spelling correction ("lapotp" finds Laptop) and a proper "Item not found" message
- Goods **and services (SAC)**, CGST / SGST / IGST split, source notification on every result
- Voice search, browse by category or rate, GST calculator (before / including GST), CSV download
- `gst_parser.py`: cleans and validates the rate CSV, with an issues report and CSV upload

## Data sources
Rates as on 3 November 2026, after GST rate rationalisation (56th GST Council, effective 22-09-2025):
- Notification 9/2025-Central Tax (Rate) - goods rates
- Notification 10/2025-Central Tax (Rate) - exempt goods
- Notification 15/2025 and 16/2025-Central Tax (Rate) - services rates and exemptions
- Tobacco amendment effective 01-02-2026; 2/2026, 3/2026, 6/2026-Central Tax (Rate) effective 01-11-2026
- https://taxinformation.cbic.gov.in/ · https://cbic-gst.gov.in/gst-goods-services-rates.html

## Files
| File | Purpose |
|------|---------|
| `app.py` | Streamlit app |
| `gst_parser.py` | Reads and validates `gst_data.csv` |
| `gst_data.csv` | GST database (one row per goods / service) |
| `requirements.txt` | Python libraries |
| `.streamlit/config.toml` | App theme |

## Run locally
```
pip install -r requirements.txt
streamlit run app.py
```

## Deploy
1. Create a public GitHub repository and upload all files above (keep the `.streamlit` folder).
2. Go to https://share.streamlit.io, sign in with GitHub, click **Create app**.
3. Pick the repository, branch `main`, main file `app.py`, then **Deploy**.

## Disclaimer
Educational use only. Verify all GST information with the latest official notifications.
Not a substitute for professional tax or legal advice.
