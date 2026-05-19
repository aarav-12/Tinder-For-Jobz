const jobQueue = require("../queues/jobQueue");

const enqueueJobIngestion = async (jobs, uploadedBy) => {
  const job = await jobQueue.add(
    "bulk-job-ingestion",
    {
      jobs,
      uploadedBy
    },
    {
      removeOnComplete: true,
      removeOnFail: false
    }
  );

  return job.id;
};

module.exports = {
  enqueueJobIngestion
};