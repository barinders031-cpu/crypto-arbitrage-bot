import pandas as pd
import yfinance as yf
import os

print("Loading Nifty 5-min data...")
nifty_file = 'nifty_1y_5min.csv'
if not os.path.exists(nifty_file):
    print(f"Error: {nifty_file} not found!")
    exit(1)

df = pd.read_csv(nifty_file)
df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True).dt.tz_convert('Asia/Kolkata')

start_date = df['timestamp'].min().strftime('%Y-%m-%d')
end_date = (df['timestamp'].max() + pd.Timedelta(days=1)).strftime('%Y-%m-%d')

print(f"Nifty Data Range: {start_date} to {end_date}")

print("Downloading India VIX data...")
# ^INDIAVIX is the ticker for India VIX on Yahoo Finance
vix_data = yf.download('^INDIAVIX', start=start_date, end=end_date)
vix_data.reset_index(inplace=True)

# Format VIX data
if isinstance(vix_data.columns, pd.MultiIndex):
    vix_data.columns = [c[0] for c in vix_data.columns]
    
vix_data['Date'] = pd.to_datetime(vix_data['Date']).dt.tz_localize('Asia/Kolkata')
vix_data['vix'] = vix_data['Close']

print(f"Downloaded {len(vix_data)} days of VIX data.")

# Merge by date
df['date'] = df['timestamp'].dt.normalize()
vix_data['date'] = vix_data['Date'].dt.normalize()

# Merge VIX
df_merged = pd.merge(df, vix_data[['date', 'vix']], on='date', how='left')

# Forward fill in case of missing VIX dates
df_merged['vix'] = df_merged['vix'].ffill()

# Drop temporary date column
df_merged.drop(columns=['date'], inplace=True)

output_file = 'nifty_vix_1y_5min.csv'
df_merged.to_csv(output_file, index=False)
print(f"Successfully saved merged data to {output_file}")
