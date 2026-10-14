import csv
import sys

def process_transactions(input_file, output_file):
    """Processes transactions from a CSV file and writes a summary report."""
    try:
        with open(input_file, 'r') as f:
            reader = csv.DictReader(f)
            
            # Check if the CSV is empty or has no header
            if not reader.fieldnames or not reader.fieldnames[0]:
                print("Error: Input CSV file is empty or has no header.", file=sys.stderr)
                sys.exit(1)
            
            # Check for required columns
            required_columns = ['category', 'amount']
            if not all(col in reader.fieldnames for col in required_columns):
                missing_cols = [col for col in required_columns if col not in reader.fieldnames]
                print(f"Error: Missing required columns: {', '.join(missing_cols)}", file=sys.stderr)
                sys.exit(1)
            
            summary = {}
            for row in reader:
                category = row['category']
                amount_str = row['amount']
                
                try:
                    amount = float(amount_str)
                except ValueError:
                    print(f"Error: Invalid amount '{amount_str}' for category '{category}'.", file=sys.stderr)
                    sys.exit(1)
                
                if category not in summary:
                    summary[category] = 0.0
                summary[category] += amount
            
            if not summary:
                print("Error: No valid transactions found in the CSV file.", file=sys.stderr)
                sys.exit(1)
            
            with open(output_file, 'w') as f:
                f.write("# Transaction Summary\n\n")
                for category, total in summary.items():
                    f.write(f"- **{category.capitalize()}**: {total:.2f}\n")
                
                grand_total = sum(summary.values())
                f.write(f"\n- **Grand Total**: {grand_total:.2f}\n")
                
    except FileNotFoundError:
        print(f"Error: Input file '{input_file}' not found.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    INPUT_FILE = 'transactions.csv'
    OUTPUT_FILE = 'report.md'
    
    process_transactions(INPUT_FILE, OUTPUT_FILE)
    print(f"Report successfully generated at {OUTPUT_FILE}")