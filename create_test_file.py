import os
import sys

def create_file(path: str, content: str) -> bool:
    """Create file at path with content."""
    try:
        with open(path, 'w') as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"Error creating file: {e}", file=sys.stderr)
        return False

def read_file(path: str) -> str:
    """Read file content."""
    try:
        with open(path, 'r') as f:
            return f.read()
    except Exception as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        return ""

def file_exists(path: str) -> bool:
    """Check if file exists."""
    return os.path.exists(path)

def verify_file(path: str, expected_content: str) -> dict:
    """Verify file exists and contains correct content."""
    exists = file_exists(path)
    actual_content = read_file(path) if exists else ""
    content_matches = actual_content == expected_content
    
    return {
        "exists": exists,
        "content_matches": content_matches,
        "actual_content": actual_content,
        "expected_content": expected_content
    }

def main():
    target_path = "test.txt"
    content = "hi"
    
    # Create file
    print(f"Creating {target_path} with content: '{content}'")
    success = create_file(target_path, content)
    
    if not success:
        print("Failed to create file", file=sys.stderr)
        sys.exit(1)
    
    # Verify file
    print(f"Verifying {target_path}...")
    result = verify_file(target_path, content)
    
    print(f"File exists: {result['exists']}")
    print(f"Content matches: {result['content_matches']}")
    print(f"Actual content: '{result['actual_content']}'")
    print(f"Expected content: '{result['expected_content']}'")
    
    if result['exists'] and result['content_matches']:
        print("SUCCESS: File created and verified successfully")
        sys.exit(0)
    else:
        print("FAILURE: Verification failed", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
