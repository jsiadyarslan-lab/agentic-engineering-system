import os
import sys
import tempfile
import shutil

# Add parent directory to path to import create_test_file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from create_test_file import create_file, read_file, file_exists, verify_file

def test_create_file():
    """Test file creation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = os.path.join(tmpdir, "test.txt")
        content = "hi"
        
        # Test create_file
        assert create_file(test_path, content) == True
        assert file_exists(test_path) == True
        assert read_file(test_path) == content
        print("test_create_file PASSED")

def test_verify_file():
    """Test file verification."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = os.path.join(tmpdir, "test.txt")
        content = "hi"
        
        # Create file first
        create_file(test_path, content)
        
        # Test verify_file
        result = verify_file(test_path, content)
        assert result["exists"] == True
        assert result["content_matches"] == True
        assert result["actual_content"] == content
        assert result["expected_content"] == content
        print("test_verify_file PASSED")

def test_verify_nonexistent_file():
    """Test verification of non-existent file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = os.path.join(tmpdir, "nonexistent.txt")
        content = "hi"
        
        result = verify_file(test_path, content)
        assert result["exists"] == False
        assert result["content_matches"] == False
        assert result["actual_content"] == ""
        assert result["expected_content"] == content
        print("test_verify_nonexistent_file PASSED")

def test_verify_wrong_content():
    """Test verification with wrong content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = os.path.join(tmpdir, "test.txt")
        content = "hi"
        wrong_content = "hello"
        
        create_file(test_path, content)
        result = verify_file(test_path, wrong_content)
        assert result["exists"] == True
        assert result["content_matches"] == False
        assert result["actual_content"] == content
        assert result["expected_content"] == wrong_content
        print("test_verify_wrong_content PASSED")

def test_main_integration():
    """Integration test for main function."""
    with tempfile.TemporaryDirectory() as tmpdir:
        original_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            # Import and run main
            import create_test_file
            # We can't easily test main without capturing stdout/stderr
            # but we can test the functions it uses
            assert create_test_file.create_file("test.txt", "hi") == True
            result = create_test_file.verify_file("test.txt", "hi")
            assert result["exists"] == True
            assert result["content_matches"] == True
            print("test_main_integration PASSED")
        finally:
            os.chdir(original_cwd)

def run_all_tests():
    """Run all tests."""
    test_create_file()
    test_verify_file()
    test_verify_nonexistent_file()
    test_verify_wrong_content()
    test_main_integration()
    print("\nAll tests PASSED!")

if __name__ == "__main__":
    run_all_tests()
