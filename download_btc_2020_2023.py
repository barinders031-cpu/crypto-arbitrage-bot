import yfinance as yf
import pandas as pd

def download_btc_daily():
    print("Downloading BTC-USD Daily data (2020-01-01 to 2023-12-31)...")
    df = yf.download(tickers='BTC-USD', start='2020-01-01', end='2023-12-31', interval='1d')
    
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
        
    df = df.reset_index()
    
    # Rename columns to lower case for consistency
    df.rename(columns={
        'Date': 'timestamp',
        'Open': 'open',
        'High': 'high',
        'Low': 'low',
        'Close': 'close',
        'Volume': 'volume'
    }, inplace=True)
    
    df.to_csv("e:/nse/btc_daily_2020_2023.csv", index=False)
    print(f"Saved {len(df)} daily candles to e:/nse/btc_daily_2020_2023.csv")

if __name__ == "__main__":
    download_btc_daily()
