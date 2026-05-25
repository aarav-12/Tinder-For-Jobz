require("dotenv").config()

const connectDB = require("../config/db")
const { getJobFeed } = require("../services/feedService")

async function testFeed() {

  try {
    await connectDB()

    const candidateId = process.env.TEST_CANDIDATE_ID
    if (!candidateId) {
      throw new Error("Set TEST_CANDIDATE_ID in .env before running this script")
    }

    const feed = await getJobFeed(candidateId)

    console.log("Feed Results:")
    console.log(feed)

  } catch (error) {

    console.error("Error testing feed:", error)

  } finally {
    const mongoose = require("mongoose")
    if (mongoose.connection.readyState !== 0) {
      await mongoose.disconnect()
    }

  }
}

testFeed()