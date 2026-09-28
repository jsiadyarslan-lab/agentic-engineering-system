const fs = require('fs/promises');
const path = require('path');

async function createTestFile() {
  const filePath = path.join(process.cwd(), 'test.txt');
  const content = 'hi';
  
  try {
    await fs.writeFile(filePath, content, 'utf-8');
    console.log(`Successfully created ${filePath} with content: '${content}'`);
    return { success: true, filePath };
  } catch (error) {
    console.error('Error creating test.txt:', error.message);
    return { success: false, error: error.message };
  }
}

createTestFile();
