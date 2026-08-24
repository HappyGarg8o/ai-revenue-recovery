"""
Generates a synthetic batch of customers + failed transactions to build and
demo the decision engine against, before any real Razorpay webhook is wired in.

Run: python3 generate_synthetic_data.py
Output: data/customers.csv, data/transactions.csv — the columns match the
Supabase tables exactly, so setup_database.py can load them straight in.
"""

import csv
import os
import random
import uuid
from datetime import datetime, timedelta

random.seed(42)  # reproducible batch — same numbers every demo run

# reason_code -> diagnosis category. This mapping IS your diagnosis engine
# for the first pass — the decision engine step 3 builds the action tier on top of it.
REASON_CATEGORY_MAP = {
    "insufficient_funds": "customer_action",
    "card_expired": "customer_action",
    "invalid_otp": "customer_action",
    "bank_timeout": "retryable",
    "processing_error": "retryable",
    "network_error": "retryable",
    "risk_flagged": "fraud_risk",
}
REASON_CODES = list(REASON_CATEGORY_MAP.keys())
REASON_WEIGHTS = [0.28, 0.18, 0.08, 0.20, 0.15, 0.06, 0.05]  # rough real-world distribution

FIRST_NAMES = ["Rohan", "Priya", "Amit", "Sneha", "Vikram", "Ananya", "Karan", "Divya",
               "Rahul", "Neha", "Arjun", "Pooja", "Sanjay", "Kavya", "Manoj"]
LAST_NAMES = ["Sharma", "Verma", "Patel", "Gupta", "Reddy", "Nair", "Iyer", "Singh", "Kumar", "Rao"]


def gen_customers(n=15):
    customers = []
    for i in range(n):
        segment = random.choice(["b2c_subscription", "b2c_subscription", "b2b_invoice"])
        ltv_tier = random.choices(["low", "mid", "high"], weights=[0.4, 0.4, 0.2])[0]
        customers.append({
            "id": str(uuid.uuid4()),
            "name": f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
            "phone": f"+91{random.randint(7000000000, 9999999999)}",
            "email": f"customer{i + 1}@example.com",
            "segment": segment,
            "ltv_tier": ltv_tier,
        })
    return customers


def amount_for_tier(tier):
    if tier == "low":
        return round(random.uniform(200, 999), 2)
    if tier == "mid":
        return round(random.uniform(1000, 4999), 2)
    return round(random.uniform(5000, 25000), 2)


def gen_transactions(customers, n=40):
    transactions = []
    for _ in range(n):
        customer = random.choice(customers)
        reason = random.choices(REASON_CODES, weights=REASON_WEIGHTS)[0]
        category = REASON_CATEGORY_MAP[reason]
        amount = amount_for_tier(customer["ltv_tier"])
        attempt_count = random.choices([0, 1, 2, 3], weights=[0.4, 0.3, 0.2, 0.1])[0]
        created = datetime.now() - timedelta(days=random.randint(0, 10), hours=random.randint(0, 23))
        transactions.append({
            "id": str(uuid.uuid4()),
            "customer_id": customer["id"],
            "amount": amount,
            "currency": "INR",
            "failure_reason_code": reason,
            "diagnosis_category": category,
            "attempt_count": attempt_count,
            "status": "failed",
            "created_at": created.isoformat(),
        })
    return transactions


def write_csv(rows, path, fieldnames):
    """Write via a temp file and swap. A DictWriter that raises partway
    through would otherwise leave a truncated file where a good one was."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    customers = gen_customers(15)
    transactions = gen_transactions(customers, 40)

    write_csv(customers, "data/customers.csv", ["id", "name", "phone", "email", "segment", "ltv_tier"])
    write_csv(transactions, "data/transactions.csv",
              ["id", "customer_id", "amount", "currency",
               "failure_reason_code", "diagnosis_category", "attempt_count",
               "status", "created_at"])

    total_at_risk = sum(t["amount"] for t in transactions)
    print(f"Generated {len(customers)} customers and {len(transactions)} transactions.")
    print(f"Total amount at risk: Rs {total_at_risk:,.2f}")
    print("Files written: data/customers.csv, data/transactions.csv")
