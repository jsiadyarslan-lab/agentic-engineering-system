import unittest
import os
import sys
from unittest.mock import patch
from io import StringIO

class TestTool(unittest.TestCase):
    
    def setUp(self):
        # Create a dummy transactions.csv for testing
        with open('transactions.csv', 'w') as f:
            f.write("category,amount\nfood,10.00\ntravel,20.00\n")
        # Create a dummy report.md to be overwritten
        with open('report.md', 'w') as f:
            f.write("dummy report")
    
    def tearDown(self):
        # Clean up created files
        if os.path.exists('transactions.csv'):
            os.remove('transactions.csv')
        if os.path.exists('report.md'):
            os.remove('report.md')
    
    def test_case_1_valid_input(self):
        """Test with valid input data."""
        # Import the tool module
        import tool
        
        # Run the main function
        with patch.object(sys, 'argv', ['tool.py']):
            with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
                tool.process_transactions('transactions.csv', 'report.md')
                output = mock_stdout.getvalue().strip()
                
        # Check if the report was created and contains expected content
        self.assertTrue(os.path.exists('report.md'))
        with open('report.md', 'r') as f:
            report_content = f.read()
            self.assertIn('# Transaction Summary', report_content)
            self.assertIn('**Food**: 10.00', report_content)
            self.assertIn('**Travel**: 20.00', report_content)
            self.assertIn('**Grand Total**: 30.00', report_content)
        self.assertEqual(output, "Report successfully generated at report.md")
    
    def test_case_2_empty_csv(self):
        """Test with an empty CSV file."""
        # Create an empty CSV file
        with open('empty_transactions.csv', 'w') as f:
            f.write("")
        
        import tool
        
        # Run the main function and expect it to exit with non-zero code
        with patch.object(sys, 'argv', ['tool.py']):
            with patch('sys.stderr', new_callable=StringIO) as mock_stderr:
                with self.assertRaises(SystemExit) as cm:
                    tool.process_transactions('empty_transactions.csv', 'report.md')
                self.assertNotEqual(cm.exception.code, 0)
                error_output = mock_stderr.getvalue().strip()
                self.assertIn("Error: Input CSV file is empty or has no header.", error_output)
        
        # Clean up
        if os.path.exists('empty_transactions.csv'):
            os.remove('empty_transactions.csv')
    
    def test_case_3_invalid_amount(self):
        """Test with a CSV containing an invalid amount."""
        # Create a CSV with an invalid amount
        with open('invalid_transactions.csv', 'w') as f:
            f.write("category,amount\nfood,ten\ntravel,20.00\n")
        
        import tool
        
        # Run the main function and expect it to exit with non-zero code
        with patch.object(sys, 'argv', ['tool.py']):
            with patch('sys.stderr', new_callable=StringIO) as mock_stderr:
                with self.assertRaises(SystemExit) as cm:
                    tool.process_transactions('invalid_transactions.csv', 'report.md')
                self.assertNotEqual(cm.exception.code, 0)
                error_output = mock_stderr.getvalue().strip()
                self.assertIn("Error: Invalid amount 'ten' for category 'food'.", error_output)
        
        # Clean up
        if os.path.exists('invalid_transactions.csv'):
            os.remove('invalid_transactions.csv')

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
