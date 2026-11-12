Order-to-Cash Revenue Leakage and Process Delay Detection System

About the Project

The main idea behind this project is to find mistakes that happen during a company's sales and payment process.

For example, a company might deliver 80 products but accidentally generate a bill for 100. Sometimes payments may be recorded more than once, or an order may be marked as completed even though the payment is still pending.

When a company handles thousands of transactions, finding these issues manually takes a lot of time.

This project helps identify such problems by comparing orders, deliveries, invoices and payments.

I used Python to process the data, SQLite to store the records and Streamlit to create a dashboard where the results can be viewed easily.

Tools and Technologies

I used the following tools while building the project:

-Python: To write the main logic and check the transactions.
-SQLite: To store all the transaction details.
-SQL: To retrieve and compare information from the database.
-Pandas: To work with the datasets.
-Streamlit: To build the dashboard.
-Plotly: To display charts and graphs.
-VS Code: To write and run the code.

Project Setup

These are the steps to set up and run the project on a computer.

Step 1: Install Python

First, install Python and check whether it is working.

Open the terminal and type:

bash
python --version


If the Python version appears, the installation is working.

Step 2: Install the Required Libraries

Open the project folder in VS Code.

In the terminal, run:

bash
python -m pip install pandas numpy faker sqlalchemy streamlit plotly pytest


This installs the libraries required for the project.

Step 3: Generate the Dataset

Since I didn't have access to real company transaction data, I used synthetic data for testing.

The dataset includes customer accounts, quotations, orders, deliveries, invoices, payments and disputes.

To generate it, run:

bash
python src/generate_full_dataset.py


Step 4: Check the Dataset

After generating the data, I added validation checks to make sure the records were properly connected and the values were consistent.

Run:

bash
python src/validate_full_dataset.py


Step 5: Create the Database

The generated data is stored in an SQLite database so that the records can be accessed and compared.

Run:

bash
python src/load_full_database.py


To check whether the database was created correctly:

bash
python src/validate_full_database.py


Step 6: Test the Anomaly Detection

To test whether the system could find mistakes, I used a separate database containing five deliberately introduced errors.

First, create the test database:

bash
python src/inject_full_anomalies.py


Then run the detection program:

bash
python src/detect_full_anomalies.py


The program checks the transactions and reports the errors it finds.

Step 7: Run the Dashboard

Once the data and database are ready, launch the dashboard using:

bash
python -m streamlit run dashboard/app.py


The dashboard can be opened at:

http://localhost:8501

It shows the transaction information, payment details, outstanding amounts and detected anomalies.

Dataset Details

For testing, I generated a dataset containing:

- 10,000 quotations
- 7,000 sales orders
- 8,000 invoices
- 15,000 payments
- 125,000 status events

All of this is sample data generated for the project. No real customer or company financial records were used.

What the System Checks

The system currently looks for five types of problems:

1. Overbilling: When an invoice contains a higher quantity than what was delivered.
2. Duplicate payment allocation: When the same payment allocation is recorded more than once.
3. Unpaid closed orders: When an order is marked as closed even though payment is still pending.
4. Missing status updates: When an important shipment status is skipped.
5. Receivables mismatch: When the recorded outstanding amount does not match the expected amount for a disputed invoice.

These checks help identify records that may need further investigation.

Prompt History and ChatGPT Assistance

I used ChatGPT during development whenever I needed help understanding a concept, planning the next step, writing code or checking the results.

Instead of building everything at once, I worked on the project in stages and tested each part before moving forward.

Below is a summary of the main prompts and topics I discussed with ChatGPT. These are simplified versions of the conversations, not an exact transcript.

1. Understanding the project

"Can you explain the Order-to-Cash process and what kind of mistakes can happen between receiving an order and collecting payment?"

This helped me understand the overall problem and what the system needed to check.

2. Planning the project

"How can I build this project using Python and a database? What should I work on first?"

This helped me divide the project into smaller stages.

3. Understanding the database

"How should I connect customer details, orders, shipments, invoices and payments in a database?"

This helped with planning the database structure.

4. Preparing sample data

"How can I generate sample company transactions that look realistic and can be used for testing?"

This helped with creating synthetic data and understanding how related records should be generated.

5. Checking the data

"What checks should I perform to make sure the generated data is correct and consistent?"

This helped with validating the records before using them for anomaly detection.

6. Finding transaction errors

"How can I compare delivery, invoice and payment records to identify possible financial mistakes?"

This helped with developing the detection rules.

7. Testing the detection system

"How can I introduce a few known errors into the data and check whether my program finds them?"

This helped with setting up controlled test cases.

8. Understanding the results

"How do precision, recall and F1-score work, and how can I use them to evaluate my results?"

This helped me understand the evaluation metrics.

9. Creating the dashboard

"How can I display the transaction details and detected errors in a simple dashboard using Streamlit?"

This helped with developing the user interface.

10. Final verification

"How can I check whether the database, anomaly detection program and dashboard are working correctly together?"

This helped with reviewing the completed implementation.

How I Used ChatGPT:

ChatGPT helped me understand technical concepts, plan the project structure, generate Python and SQL code, troubleshoot issues and interpret the results.

I used the suggested code in my local project, ran the scripts in VS Code and checked the outputs as I progressed.

Testing and Results:

After setting up the database and detection rules, I tested the system using five deliberately introduced anomalies.

The system identified all five errors without reporting additional cases in that controlled test.

The results were:

- Precision: 100%
- Recall: 100%
- F1-score: 100%

These results are based only on the five synthetic test cases. More testing would be required to evaluate how well the system performs on real company data.

What I Learned:

While working on this project, I gained practical experience in:

- Working with relational databases
- Generating and validating datasets
- Writing SQL queries
- Using Python for data analysis
- Building rule-based anomaly detection
- Evaluating detection results
- Creating interactive dashboards with Streamlit

I also learned why it is important to validate data before performing analysis, since incorrect records can lead to misleading results.

Future Improvements:

There are a few features that could be added later, such as machine learning-based anomaly detection, more detailed process delay tracking and financial risk scoring.

These would help extend the system beyond its current rule-based approach.

Conclusion:

This project helped me understand how different parts of a company's sales process are connected and how small mistakes in transaction records can affect financial reporting.

The system is able to compare related records, identify certain inconsistencies and display the findings in a dashboard.

Although it currently uses synthetic data, the project provides a foundation for building a more advanced transaction monitoring system in the future.