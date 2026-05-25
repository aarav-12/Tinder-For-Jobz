// src/queues/jobQueue.js

const { Queue } = require("bullmq");
const redisClient = require("../config/redisClient");

let jobQueue;

const getJobQueue = () => {
  if (!jobQueue) {
    jobQueue = new Queue("job-processing", {
      connection: redisClient
    });
  }

  return jobQueue;
};

module.exports = getJobQueue;