const computeMatchScore = require("../utils/matchScore")
const mongoose = require("mongoose")
const User = require("../models/User")
const Job = require("../models/Job")
const Swipe = require("../models/Swipe")

function toObjectId(value) {
  if (value instanceof mongoose.Types.ObjectId) {
    return value
  }

  if (typeof value === "string" && mongoose.Types.ObjectId.isValid(value)) {
    return new mongoose.Types.ObjectId(value)
  }

  return null
}

async function getJobFeed(candidateId) {

  if (mongoose.connection.readyState === 0) {
    throw new Error("Database is not connected")
  }

  const candidateObjectId = toObjectId(candidateId)
  if (!candidateObjectId) {
    throw new Error("Invalid candidate user ID")
  }

  // 1) Candidate profile fetch
  const candidate = await User.findById(candidateObjectId).lean()

  if (!candidate) {
    throw new Error("Candidate profile not found")
  }

  const candidateSkills = candidate.skills || []


  // 2) Already swiped jobs
  const swipes = await Swipe.find({ userId: candidateObjectId }).select("jobId").lean()

  const swipedJobIds = swipes
    .map((s) => toObjectId(s.jobId))
    .filter(Boolean)


  // 3) Candidate pool fetch (NOT all jobs)
  const jobQuery = {
    requiredSkills: { $in: candidateSkills }
  }

  if (swipedJobIds.length > 0) {
    jobQuery._id = { $nin: swipedJobIds }
  }

  const jobs = await Job.find(jobQuery).limit(200).lean()


  // 4) Compute matchScore
  const scoredJobs = jobs.map(job => ({
    ...job,
    matchScore: computeMatchScore(candidate, job)
  }))


  // 5) Sort by best match
  scoredJobs.sort((a, b) => b.matchScore - a.matchScore)


  // 6) Return top 20
  return scoredJobs.slice(0, 20)
}

module.exports = { getJobFeed }