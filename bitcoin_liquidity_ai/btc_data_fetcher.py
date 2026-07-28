import yfinance as yf
import pandas as pd
import os

def fetch_historical_data(symbol="BTC-USD", interval="5m", period="60d", output_csv="btc_5m_data.csv"):
    """
    Fetches historical data for a given symbol and interval using yfinance.
    Saves the data to a CSV file.
    """
    print(f"Fetching {period} of {interval} data for {symbol}...")
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        
        if df.empty:
            print("No data fetched. Please check the symbol or parameters.")
            return None
        
        # Keep only necessary columns
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
        
        # Save to CSV
        df.to_csv(output_csv)
        print(f"Successfully saved {len(df)} rows to {output_csv}")
        return df
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

if __name__ == "__main__":
    fetch_historical_data(symbol="BTC-USD", interval="5m", period="60d", output_csv="btc_5m_data.csv")
    fetch_historical_data(symbol="BTC-USD", interval="15m", period="60d", output_csv="btc_15m_data.csv")
