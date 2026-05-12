import pandas as pd
df = pd.read_csv('api/data/ksl_training/ksl_dataset.csv')
print(df['label'].unique().tolist())
