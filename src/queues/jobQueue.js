// src/queues/jobQueue.js

const { Queue } = require("bullmq");
const redisClient = require("../config/redisClient");

const jobQueue = new Queue("job-processing", {
  connection: redisClient
});

module.exports = jobQueue;