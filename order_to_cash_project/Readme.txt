# Order-to-Cash Revenue Leakage Detection

## About the Project

This project is about finding errors in a company's order and payment records.

In a normal sales process, a customer places an order, the company delivers the products, an invoice is generated and the payment is collected. Sometimes these records don't match, which can lead to financial problems.

I built a system that compares these records and identifies mismatches. I used Python to process the data, SQLite to store the records and Streamlit to display the results.

## Tools Used

- Python - For data processing and checking transactions
- SQLite - For storing transaction records
- SQL - For comparing records in the database
- Pandas - For working with datasets
- Streamlit - For the dashboard
- Plotly - For charts and graphs
- VS Code - For writing and running the code

## Project Setup

I developed the project using Python in VS Code.

### Step 1: Install the Required Libraries

Open the project folder in VS Code and run:

```bash
python -m pip install pandas numpy faker sqlalchemy streamlit plotly pytest
```

### Step 2: Generate the Dataset

I used synthetic data because I didn't have access to real company transaction records.

To generate the full dataset, run:

```bash
python src/generate_full_dataset.py
```

### Step 3: Validate the Dataset

After generating the data, I checked whether the records were connected properly and whether the values were consistent.

```bash
python src/validate_full_dataset.py
```

### Step 4: Create the Database

The generated data is loaded into an SQLite database.

```bash
python src/load_full_database.py
```

To check whether the database was created correctly:

```bash
python src/validate_full_database.py
```

### Step 5: Test Anomaly Detection

I created a separate copy of the database and deliberately introduced five errors to test the detection rules.

```bash
python src/inject_full_anomalies.py
```

Then I ran the detection program:

```bash
python src/detect_full_anomalies.py
```

### Step 6: Run the Dashboard

To start the dashboard:

```bash
python -m streamlit run dashboard/app.py
```

The dashboard can be opened at:

http://localhost:8501

## Dataset Details

The generated dataset contains:

| Data | Number of Records |
|---|---:|
| Quotations | 10,000 |
| Sales Orders | 7,000 |
| Invoices | 8,000 |
| Payments | 15,000 |
| Status Events | 125,000 |

The dataset also includes customer accounts, shipments, invoice details, payment allocations and disputes.

All records were generated for testing purposes.

## Data Validation

After generating the dataset, I ran validation checks to make sure the records were consistent.

I checked whether:

- Orders, shipments and invoices were connected correctly.
- Delivered quantities matched the expected quantities.
- Payment allocations were calculated correctly.
- Invoice balances were consistent.
- Database relationships were valid.
- Dispute records matched their related transactions.

The full dataset passed the validation checks.

The SQLite database validation also passed without foreign key violations or financial reconciliation errors.

## Regenerating and Comparing the Dataset

One of the requirements was to check whether the same data could be generated more than once.

I generated the dataset twice using the same random seed and configuration.

After both runs, I compared the generated CSV files using SHA-256 hashes. These hashes help check whether the contents of two files are identical.

There were 16 CSV files in total.

**Comparison Results:**

- Total files compared: 16
- Files that matched: 16
- Files with differences: 0

This confirmed that the dataset generation process was reproducible.

## Anomaly Detection

The system currently checks for five types of errors.

1. **Invoice mismatch:** When an invoice includes more items than were delivered.
2. **Duplicate payment allocation:** When the same payment allocation is recorded more than once.
3. **Unpaid closed order:** When an order is marked as closed even though payment is still pending.
4. **Missing shipment status:** When an important status update is skipped.
5. **Receivables mismatch:** When the recorded outstanding amount does not match the expected amount for a disputed invoice.

## Testing and Results

To test the detection rules, I used two versions of the database.

The first was the original clean database, without any deliberately introduced errors.

The second was a copy containing five known anomalies.

I ran the detection program on both databases and compared the results.

| Test | Result |
|---|---|
| Anomalies found in clean database | 0 |
| Anomalies introduced in test database | 5 |
| Anomalies detected | 5 |
| Missed anomalies | 0 |
| Additional findings | 0 |
| Precision | 100% |
| Recall | 100% |
| F1-score | 100% |

The system identified all five introduced anomalies.

These results are based on the five controlled test cases. More testing would be needed to evaluate performance on real company data.

## Reports

The project includes validation outputs and anomaly evaluation reports.

The validation programs check whether the generated data and database records are consistent.

The anomaly evaluation report compares the errors introduced into the test database with the errors found by the detection program.

The evaluation results are saved in:

`reports/full_anomaly_evaluation.json`

The dashboard also allows users to view and download selected transaction information as CSV files.

## Dashboard

I created a Streamlit dashboard to make it easier to view the results.

The dashboard includes:

- An overview of the transaction data
- Outstanding invoice amounts
- Payment reconciliation details
- Detected anomalies
- Dispute information
- Transaction records
- Filters and CSV downloads

The dashboard can display information from the clean database and the database containing the test anomalies.

## Prompt History

During development, I used AI assistance to understand database relationships, generate Python and SQL code, resolve errors and review the results.

Some of the main questions I worked through were:

1. How should orders, deliveries, invoices and payments be connected?
2. How can I generate sample transaction data with consistent relationships?
3. What checks are needed to validate the generated data?
4. How can I identify duplicate payments and invoice mismatches?
5. How can I test the detection rules using known errors?
6. How can I compare two generated datasets?

This is a short summary of the main topics discussed during development.

## What I Learned

While working on this project, I learned how to connect different transaction records in a database and compare them using Python and SQL.

I also gained experience in generating sample data, checking its consistency and testing detection rules using known errors.

The reproducibility test helped me understand why using the same configuration and random seed is important when generating datasets.

## Future Improvements

The current system uses predefined rules to detect transaction inconsistencies.

In the future, I would like to add more detailed time-based delay detection, test the system with more varied anomalies and explore machine learning methods.

## Conclusion

I was able to generate a large synthetic dataset, store it in SQLite, validate the records and test the anomaly detection rules.

The dataset passed the validation and reproducibility checks. All 16 CSV files matched when the data was regenerated, and the system detected all five introduced anomalies.

The dashboard makes it easier to review transaction information and detection results without checking each database record manually.

The project currently focuses on financial discrepancies and process-control errors. Detailed time-based delay detection remains an area for further development.
