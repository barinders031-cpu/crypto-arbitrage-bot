import yfinance as yf
import pandas as pd

def download_btc_2024():
    print("Downloading BTC-USD Daily data (2024-01-01 to 2024-12-31)...")
    df = yf.download(tickers='BTC-USD', start='2024-01-01', end='2024-12-31', interval='1d')
    
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
    
    df.to_csv("e:/nse/btc_daily_2024.csv", index=False)
    print(f"Saved {len(df)} daily candles to e:/nse/btc_daily_2024.csv")

if __name__ == "__main__":
    download_btc_2024()
