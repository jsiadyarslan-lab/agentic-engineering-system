import os

def verify_greeting_file():
    path = 'greeting.txt'
    expected_content = 'hello from factory'
    
    if not os.path.exists(path):
        print(f'FAIL: File {path} does not exist')
        return False
    
    with open(path, 'r', encoding='utf-8') as f:
        actual_content = f.read()
    
    if actual_content == expected_content:
        print(f'PASS: File {path} exists with correct content')
        print(f'Content: {actual_content}')
        return True
    else:
        print(f'FAIL: Content mismatch')
        print(f'Expected: {expected_content}')
        print(f'Actual: {actual_content}')
        return False

if __name__ == '__main__':
    success = verify_greeting_file()
    exit(0 if success else 1)
