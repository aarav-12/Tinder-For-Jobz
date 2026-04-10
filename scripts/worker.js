require("dotenv").config();

const mongoose = require("mongoose");
const Task = require("../models/Task");
const axios = require("axios");
const Job = require("../models/Job");
// connect DB (reuse your config)
const connectDB = require("../config/db");

console.log("🚀 Worker started...");

// core worker loop
const runWorker = async () => {
  while (true) {
    try {
      const task = await Task.findOneAndUpdate(
        { status: "pending" },
        { status: "running" },
        { returnDocument: "after" }
      );

      if (!task) {
        // no work → wait 3 sec
        await new Promise((res) => setTimeout(res, 3000));
        continue;
      }

      console.log("⚙️ Processing task:", task._id);

      try {
        if (task.type === "SYNC_JOBS") {
          await processSyncJobs(task);
        }

        task.status = "completed";
        await task.save();

        console.log("✅ Task completed:", task._id);
      } catch (err) {
        console.error("❌ Task failed:", err.message);

        task.attempts += 1;

        if (task.attempts < 3) {
          task.status = "pending"; // retry
          console.log("🔁 Retrying task:", task._id);
        } else {
          task.status = "failed";
          console.log("💀 Task permanently failed:", task._id);
        }

        await task.save();
      }
    } catch (err) {
      console.error("❌ Worker error:", err);
    }
  }
};

const processSyncJobs = async (task) => {
  const { company } = task.payload;

  try {
    console.log(`📦 Fetching jobs for: ${company}`);

    let allJobs = [];
    let page = 1;
    let hasMore = true;

    while (hasMore) {
      const url = `https://boards-api.greenhouse.io/v1/boards/${company}/jobs?page=${page}`;

      const response = await axios.get(url);

      const jobs = response.data.jobs;

      if (!jobs || jobs.length === 0) {
        hasMore = false;
        break;
      }

      console.log(`📄 Page ${page}: ${jobs.length} jobs`);

      allJobs = [...allJobs, ...jobs];
      page++;
    }

    console.log(`🔢 Total jobs fetched: ${allJobs.length}`);

    for (let job of allJobs) {
      await Job.findOneAndUpdate(
        { greenhouseJobId: job.id },
        {
          title: job.title,
          company: company,
          location: job.location?.name || "N/A",
          applyUrl: job.absolute_url,
        },
        { upsert: true, returnDocument: "after" }
      );
    }

    console.log(`✅ Stored all jobs for ${company}`);
  } catch (err) {
    console.error("❌ Error fetching jobs:", err.message);
    throw err;
  }
};

const start = async () => {
  await connectDB();
  await runWorker();
};

start();