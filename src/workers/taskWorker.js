const path = require("path");
require("dotenv").config({ path: path.resolve(__dirname, "../../.env") });

const { Worker } = require("bullmq");
const Task = require("../../models/Task");
const connectDB = require("../../config/db");
const { processLeverJobs } = require("../../services/lever");
const { processGreenhouseJobs } = require("../../services/greenhouse");
const redisClient = require("../../src/config/redisClient");

console.log("🚀 Task worker starting...");

const startWorker = async () => {
  await connectDB();

  const worker = new Worker(
    "job-processing",
    async (job) => {
      console.log(`⚙️  Worker received job: ${job.id} (${job.name})`);

      // Find persistent Task record if it exists
      let taskDoc = null;
      try {
        taskDoc = await Task.findOne({ jobId: String(job.id) });
        if (taskDoc) {
          taskDoc.status = "running";
          await taskDoc.save();
        }
      } catch (err) {
        console.error("Failed to update Task doc status to running:", err.message);
      }

      try {
        switch (job.name) {
          case "SYNC_GREENHOUSE":
            await processGreenhouseJobs(job.data.company || job.data.payload?.company || job.data.payload);
            break;
          case "SYNC_LEVER":
            await processLeverJobs(job.data.company || job.data.payload?.company || job.data.payload);
            break;
          default:
            console.log("⚠️ Unknown job type:", job.name);
        }

        if (taskDoc) {
          taskDoc.status = "completed";
          await taskDoc.save();
        }

        console.log(`✅ Job ${job.id} processed`);
      } catch (err) {
        console.error(`❌ Job ${job.id} failed:`, err.message || err);

        if (taskDoc) {
          taskDoc.attempts = (taskDoc.attempts || 0) + 1;

          if (taskDoc.attempts < 3) {
            taskDoc.status = "pending";
          } else {
            taskDoc.status = "failed";
          }

          await taskDoc.save();
        }

        throw err; // let BullMQ record the failure
      }
    },
    { connection: redisClient }
  );

  worker.on("completed", (job) => {
    console.log(`Worker completed job ${job.id}`);
  });

  worker.on("failed", (job, err) => {
    console.error(`Worker failed job ${job.id}:`, err?.message || err);
  });

  console.log("Worker listening on job-processing queue");
};

startWorker().catch(err => {
  console.error("Worker failed to start:", err);
  process.exit(1);
});
