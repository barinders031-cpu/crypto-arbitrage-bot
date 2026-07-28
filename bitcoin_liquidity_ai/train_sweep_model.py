import pandas as pd
import numpy as np
import json

class SimpleLogisticRegression:
    def __init__(self, learning_rate=0.01, num_iterations=1000):
        self.learning_rate = learning_rate
        self.num_iterations = num_iterations
        self.weights = None
        self.bias = None

    def sigmoid(self, z):
        # Clip z to avoid overflow
        z = np.clip(z, -250, 250)
        return 1 / (1 + np.exp(-z))

    def fit(self, X, y):
        num_samples, num_features = X.shape
        self.weights = np.zeros(num_features)
        self.bias = 0

        # Gradient Descent
        for _ in range(self.num_iterations):
            linear_model = np.dot(X, self.weights) + self.bias
            y_predicted = self.sigmoid(linear_model)

            dw = (1 / num_samples) * np.dot(X.T, (y_predicted - y))
            db = (1 / num_samples) * np.sum(y_predicted - y)

            self.weights -= self.learning_rate * dw
            self.bias -= self.learning_rate * db

    def predict(self, X, threshold=0.5):
        linear_model = np.dot(X, self.weights) + self.bias
        y_predicted = self.sigmoid(linear_model)
        y_predicted_cls = [1 if i > threshold else 0 for i in y_predicted]
        return np.array(y_predicted_cls)

    def predict_proba(self, X):
        linear_model = np.dot(X, self.weights) + self.bias
        return self.sigmoid(linear_model)

def train_model(csv_file='backtest_results.csv', model_output='sweep_model.json'):
    print("Loading data...")
    df = pd.read_csv(csv_file)
    
    df['Target_Class'] = df['Outcome'].apply(lambda x: 1 if x == 'Win' else 0)
    
    features = ['RSI', 'Vol_Spike', 'Wick_Ratio', 'Hour']
    X = df[features].fillna(df[features].mean()).values
    y = df['Target_Class'].values
    
    print(f"Total samples: {len(df)}")
    print(f"Wins (Class 1): {np.sum(y)} ({(np.sum(y)/len(y))*100:.2f}%)")
    
    # Normalize features
    X_mean = np.mean(X, axis=0)
    X_std = np.std(X, axis=0)
    X_scaled = (X - X_mean) / X_std
    
    # Simple Train-Test split (80-20)
    split_idx = int(0.8 * len(X_scaled))
    X_train, X_test = X_scaled[:split_idx], X_scaled[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]
    
    # Since classes are imbalanced, we can weight the positive class by oversampling or adjusting threshold
    # But for pure numpy, let's just train and adjust threshold at prediction.
    
    print("Training Numpy Logistic Regression Model...")
    model = SimpleLogisticRegression(learning_rate=0.1, num_iterations=2000)
    model.fit(X_train, y_train)
    
    # Evaluate
    # Lower threshold to catch more wins since they are rare (Class Imbalance handling)
    y_pred = model.predict(X_test, threshold=0.15) 
    
    # Custom Accuracy
    accuracy = np.mean(y_pred == y_test)
    print("\n--- Test Set Evaluation ---")
    print(f"Accuracy: {accuracy:.4f}")
    
    true_positives = np.sum((y_test == 1) & (y_pred == 1))
    false_positives = np.sum((y_test == 0) & (y_pred == 1))
    false_negatives = np.sum((y_test == 1) & (y_pred == 0))
    
    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
    print(f"Precision: {precision:.4f}")
    print(f"Recall: {recall:.4f}")
    
    print("\n--- Feature Weights ---")
    for feature, weight in zip(features, model.weights):
        print(f"{feature}: {weight:.4f}")
        
    # Save Model (Memory) to JSON to avoid pickle/DLL issues entirely
    model_data = {
        'weights': model.weights.tolist(),
        'bias': float(model.bias),
        'features': features,
        'mean': X_mean.tolist(),
        'std': X_std.tolist(),
        'threshold': 0.15
    }
    
    with open(model_output, 'w') as f:
        json.dump(model_data, f, indent=4)
    print(f"\nModel saved to {model_output} (AI Memory Updated)")

if __name__ == "__main__":
    train_model()
