import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from transformers import DistilBertTokenizer, DistilBertForSequenceClassification, Trainer, TrainingArguments
import torch
from torch.utils.data import Dataset
import warnings
warnings.filterwarnings('ignore')

print("🚀 Starting Severity Model Training...")
print("="*50)

# STEP 1: LOAD DATA
print("\n📂 Step 1: Loading data...")
df = pd.read_csv('bug_reports_FINAL_v7.csv')
print(f"✅ Loaded {len(df)} bugs")

# STEP 2: PREPARE TEXT
print("\n📝 Step 2: Preparing text...")
df['text'] = df['title'] + " " + df['description']
print("✅ Created combined text field")

# STEP 3: ENCODE LABELS
print("\n🏷️ Step 3: Encoding labels...")
label_encoder = LabelEncoder()
df['label'] = label_encoder.fit_transform(df['severity'])
for i, label in enumerate(label_encoder.classes_):
    print(f"   {label} -> {i}")

# STEP 4: SPLIT DATA
print("\n✂️ Step 4: Splitting data...")
train_texts, test_texts, train_labels, test_labels = train_test_split(
    df['text'].tolist(), 
    df['label'].tolist(), 
    test_size=0.2, 
    random_state=42,
    stratify=df['label']
)
print(f"✅ Training: {len(train_texts)} samples")
print(f"✅ Testing: {len(test_texts)} samples")

print("\n🔤 Step 5: Loading DistilBERT tokenizer...")

# Load tokenizer
tokenizer = DistilBertTokenizer.from_pretrained('distilbert-base-uncased')
print("✅ Tokenizer loaded successfully!")

# Tokenize all texts
train_encodings = tokenizer(train_texts, truncation=True, padding=True, max_length=128)
test_encodings = tokenizer(test_texts, truncation=True, padding=True, max_length=128)

print(f"✅ Tokenized {len(train_texts)} training samples")
print(f"✅ Tokenized {len(test_texts)} testing samples")
print("   Max length: 128 tokens")

# Create custom Dataset class
class BugDataset(torch.utils.data.Dataset):
    def __init__(self, encodings, labels):
        self.encodings = encodings
        self.labels = labels

    def __getitem__(self, idx):
        item = {key: torch.tensor(val[idx]) for key, val in self.encodings.items()}
        item['labels'] = torch.tensor(self.labels[idx])
        return item

    def __len__(self):
        return len(self.labels)

# Create dataset objects
train_dataset = BugDataset(train_encodings, train_labels)
test_dataset = BugDataset(test_encodings, test_labels)

print("\n✅ Datasets created successfully!")
print(f"   Training dataset size: {len(train_dataset)}")
print(f"   Testing dataset size: {len(test_dataset)}")

print("\n🤖 Step 6: Loading DistilBERT model...")

# Load pre-trained DistilBERT model for classification
model = DistilBertForSequenceClassification.from_pretrained(
    'distilbert-base-uncased', 
    num_labels=4  # Critical, High, Medium, Low
)
print("✅ Model loaded successfully!")

# Set up training arguments
training_args = TrainingArguments(
    output_dir='./results',          # Where to save results
    num_train_epochs=3,              # Number of training epochs
    per_device_train_batch_size=8,   # Batch size for training
    per_device_eval_batch_size=8,    # Batch size for evaluation
    warmup_steps=100,                 # Number of warmup steps
    weight_decay=0.01,                # Strength of weight decay
    logging_dir='./logs',             # Directory for logs
    logging_steps=10,                  # Log every 10 steps
    eval_strategy="epoch",       # Evaluate after each epoch
    save_strategy="epoch",              # Save after each epoch
    load_best_model_at_end=True,       # Load best model at end
)

print("✅ Training arguments configured")

# Create Trainer
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=test_dataset,
)

print("\n🎯 Starting training... (this will take 5-10 minutes)")
print("="*50)

# Train the model
trainer.train()

print("\n✅ Training complete!")
print("="*50)

# Evaluate the model
print("\n📊 Evaluating model on test data...")
results = trainer.evaluate()
print("\n✅ Evaluation Results:")
for key, value in results.items():
    if isinstance(value, float):
        print(f"   {key}: {value:.4f}")
    else:
        print(f"   {key}: {value}")

# Calculate accuracy manually
from sklearn.metrics import accuracy_score

print("\n📊 Calculating detailed metrics...")
predictions = trainer.predict(test_dataset)
preds = np.argmax(predictions.predictions, axis=-1)

# Calculate accuracy
accuracy = accuracy_score(test_labels, preds)
print(f"\n✅ Model Accuracy: {accuracy:.2%}")

# Detailed classification report
from sklearn.metrics import classification_report
print("\n📋 Detailed Classification Report:")
print(classification_report(test_labels, preds, target_names=['Critical', 'High', 'Low', 'Medium']))

# Save the model and tokenizer
model.save_pretrained('./bug_severity_model')
tokenizer.save_pretrained('./bug_severity_model')
print("\n💾 Model saved to './bug_severity_model'")

# Test with a new bug
print("\n🔍 Testing with a new bug report...")
test_bug = "Login page crashes when I click submit"
inputs = tokenizer(test_bug, return_tensors="pt", truncation=True, padding=True, max_length=128)
outputs = model(**inputs)
predicted_class = torch.argmax(outputs.logits, dim=1).item()
severity_map = {0: "Critical", 1: "High", 2: "Low", 3: "Medium"}
print(f"\nNew bug: '{test_bug}'")
print(f"Predicted severity: {severity_map[predicted_class]}")

print("\n🎉 MODEL BUILD SUCCESSFUL!")