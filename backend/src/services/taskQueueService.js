const getJobQueue = require("../queues/jobQueue");

/**
 * Enqueue a task into BullMQ and return job metadata.
 * @param {string} taskType - e.g. 'SYNC_GREENHOUSE' or 'SYNC_LEVER'
 * @param {object} payload - self-contained payload for worker
 */
const enqueueTask = async (taskType, payload) => {
  const job = await getJobQueue().add(taskType, payload, {
    removeOnComplete: true,
    removeOnFail: false
  });

  return {
    id: job.id,
    name: job.name
  };
};

module.exports = {
  enqueueTask
};
