import yfinance as yf
import pandas as pd

def download_btc():
    print("Downloading BTC-USD 5-minute data (last 60 days)...")
    df = yf.download(tickers='BTC-USD', period='60d', interval='5m')
    
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
        
    df = df.reset_index()
    
    # Rename columns to lower case for consistency
    df.rename(columns={
        'Datetime': 'timestamp',
        'Open': 'open',
        'High': 'high',
        'Low': 'low',
        'Close': 'close',
        'Volume': 'volume'
    }, inplace=True)
    
    df.to_csv("e:/nse/btc_5min.csv", index=False)
    print(f"Saved {len(df)} 5-minute candles to e:/nse/btc_5min.csv")

if __name__ == "__main__":
    download_btc()
