const fs = require('fs/promises');
const path = require('path');

async function verifyTestFile() {
  const filePath = path.join(process.cwd(), 'test.txt');
  const expectedContent = 'hi';
  
  try {
    // Check if file exists
    await fs.access(filePath);
    
    // Read file content
    const actualContent = await fs.readFile(filePath, 'utf-8');
    
    // Verify content matches
    const matchesExpected = actualContent === expectedContent;
    
    if (matchesExpected) {
      console.log(`Verification successful: test.txt contains '${actualContent}'`);
      return { verified: true, actualContent, matchesExpected: true };
    } else {
      console.error(`Content mismatch: expected '${expectedContent}', got '${actualContent}'`);
      return { verified: false, actualContent, matchesExpected: false, error: 'Content mismatch' };
    }
  } catch (error) {
    if (error.code === 'ENOENT') {
      console.error('Verification failed: test.txt does not exist');
      return { verified: false, error: 'File does not exist' };
    }
    console.error('Verification error:', error.message);
    return { verified: false, error: error.message };
  }
}

verifyTestFile();
