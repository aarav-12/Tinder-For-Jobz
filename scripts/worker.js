require("dotenv").config();

const Task = require("../models/Task");
const connectDB = require("../config/db");

const { processLeverJobs } = require("../services/lever");
const { processGreenhouseJobs } = require("../services/greenhouse");

console.log("🚀 Worker started...");
console.log("🧠 Worker loop running...");

async function markTaskAsFailed(taskId) {
  await Task.findByIdAndUpdate(taskId, { status: "failed" });
}

const runWorker = async () => {
  while (true) {
    try {
      const task = await Task.findOneAndUpdate(
        { status: "pending" },
        { status: "running" },
        { returnDocument: "after" }
      );

      if (!task) {
        await new Promise((res) => setTimeout(res, 3000));
        continue;
      }

      console.log("⚙️ Processing task:", task._id);

      try {
        if (task.type === "SYNC_GREENHOUSE") {
          await processGreenhouseJobs(task.payload.company);
        }

        if (task.type === "SYNC_LEVER") {
          await processLeverJobs(task.payload.company);
        }

        task.status = "completed";
        await task.save();

        console.log("✅ Task completed:", task._id);
        console.log("📊 Task stats:", {
          id: task._id,
          attempts: task.attempts,
          status: task.status
        });

      } catch (err) {
        const company = task.payload?.company;
        if (err.response && err.response.status === 404) {
          console.log("🚫 Invalid company, skipping:", company);

          await markTaskAsFailed(task._id);

          continue; // DO NOT retry
        }

        console.error("❌ Task failed:", err.message);

        task.attempts += 1;

        if (task.attempts < 3) {
          task.status = "pending";

          await new Promise(res => setTimeout(res, 5000));

          console.log("🔁 Retrying task after delay:", task._id);
        } else {
          task.status = "failed";
          console.log("💀 Task permanently failed:", task._id);
        }

        await task.save();

        console.log("📊 Task stats:", {
          id: task._id,
          attempts: task.attempts,
          status: task.status
        });
      }

    } catch (err) {
      console.error("❌ Worker error:", err);
    }
  }
};

const start = async () => {
  await connectDB();
  await runWorker();
};

start();