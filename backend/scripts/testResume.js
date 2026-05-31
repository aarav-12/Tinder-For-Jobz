const fs = require('fs');
const path = require('path');
const axios = require('axios');
const FormData = require('form-data');

async function main() {
  const resumePath = process.argv[2];
  const userId = process.argv[3] || 'test-user';

  if (!resumePath) {
    console.error('Usage: npm run test:resume -- "C:\\path\\to\\resume.pdf" [userId]');
    process.exit(1);
  }

  const absolutePath = path.resolve(resumePath);

  if (!fs.existsSync(absolutePath)) {
    console.error(`File not found: ${absolutePath}`);
    process.exit(1);
  }

  const form = new FormData();
  form.append('file', fs.createReadStream(absolutePath));
  form.append('user_id', userId);

  const baseUrl = process.env.RAG_SERVICE_URL || 'http://127.0.0.1:8000';

  try {
    const response = await axios.post(`${baseUrl}/analyze`, form, {
      headers: form.getHeaders(),
      timeout: Number(process.env.RAG_SERVICE_TIMEOUT_MS || 120000),
      maxBodyLength: Infinity,
      maxContentLength: Infinity,
    });

    console.log(JSON.stringify(response.data, null, 2));
  } catch (error) {
    if (error.response) {
      console.error('Request failed with status:', error.response.status);
      console.error(JSON.stringify(error.response.data, null, 2));
    } else {
      console.error('Request failed:', error.message);
    }
    process.exit(1);
  }
}

main();
