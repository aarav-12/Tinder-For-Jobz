const axios = require("axios");
const FormData = require("form-data");

const ragBaseUrl = process.env.RAG_SERVICE_URL || "http://127.0.0.1:8000";

const requestTimeout = Number(process.env.RAG_SERVICE_TIMEOUT_MS || 120000);

const getHealth = async () => {
  const response = await axios.get(`${ragBaseUrl}/health`, {
    timeout: 10000,
  });

  return response.data;
};

const analyzeResume = async ({ fileBuffer, filename, contentType, userId }) => {
  const form = new FormData();
  form.append("file", fileBuffer, {
    filename: filename || "resume.pdf",
    contentType: contentType || "application/pdf",
  });

  if (userId) {
    form.append("user_id", userId);
  }

  const response = await axios.post(`${ragBaseUrl}/analyze`, form, {
    headers: form.getHeaders(),
    timeout: requestTimeout,
    maxBodyLength: Infinity,
    maxContentLength: Infinity,
  });

  return response.data;
};

const retrieveJobs = async ({ query, top_k, filters }) => {
  const response = await axios.post(
    `${ragBaseUrl}/retrieve`,
    { query, top_k, filters },
    { timeout: requestTimeout }
  );

  return response.data;
};

const embedJob = async ({ job_id, title, skills, description, metadata }) => {
  const response = await axios.post(
    `${ragBaseUrl}/embed-job`,
    { job_id, title, skills, description, metadata },
    { timeout: requestTimeout }
  );

  return response.data;
};

const scoreJobQuality = async (payload) => {
  const response = await axios.post(
    `${ragBaseUrl}/score-job-quality`,
    payload,
    { timeout: requestTimeout }
  );

  return response.data;
};

const explainMatch = async (payload) => {
  const response = await axios.post(
    `${ragBaseUrl}/explain-match`,
    payload,
    { timeout: requestTimeout }
  );

  return response.data;
};

const getRetrievalStats = async () => {
  const response = await axios.get(`${ragBaseUrl}/debug/retrieval-stats`, {
    timeout: 10000,
  });

  return response.data;
};

const clearRetrievalCache = async () => {
  const response = await axios.post(`${ragBaseUrl}/debug/clear-cache`, {}, {
    timeout: 10000,
  });

  return response.data;
};

module.exports = {
  getHealth,
  analyzeResume,
  retrieveJobs,
  embedJob,
  scoreJobQuality,
  explainMatch,
  getRetrievalStats,
  clearRetrievalCache,
};