require("dotenv").config();

const Task = require("../models/Task");
const connectDB = require("../config/db");
const { greenhouse, lever } = require("../config/companies");

async function seedTasks() {
  await connectDB();

  try {
    // greenhouse
    for (const company of greenhouse) {
      const existing = await Task.findOne({
        type: "SYNC_GREENHOUSE",
        "payload.company": company,
        status: { $in: ["pending", "running"] }
      });

      if (!existing) {
        const taskQueueService = require("../src/services/taskQueueService");
        const jobMeta = await taskQueueService.enqueueTask("SYNC_GREENHOUSE", { company });

        await Task.create({
          type: "SYNC_GREENHOUSE",
          status: "pending",
          attempts: 0,
          payload: { company },
          jobId: String(jobMeta.id)
        });

        console.log(`✅ Task created for ${company} (job ${jobMeta.id})`);
      }
    }

    // lever
    for (const company of lever) {
      const existing = await Task.findOne({
        type: "SYNC_LEVER",
        "payload.company": company,
        status: { $in: ["pending", "running"] }
      });

      if (!existing) {
        const taskQueueService = require("../src/services/taskQueueService");
        const jobMeta = await taskQueueService.enqueueTask("SYNC_LEVER", { company });

        await Task.create({
          type: "SYNC_LEVER",
          status: "pending",
          attempts: 0,
          payload: { company },
          jobId: String(jobMeta.id)
        });

        console.log(`✅ Lever task created for ${company} (job ${jobMeta.id})`);
      }
    }
  } finally {
    await require("mongoose").disconnect();
  }
}

seedTasks().catch((error) => {
  console.error("❌ Seed failed:", error);
  process.exit(1);
});